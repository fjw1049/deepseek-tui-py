"""Workflow IR validation tests."""

from __future__ import annotations

import pytest

from deepseek_tui.workflow.models import WorkflowValidationError, parse_workflow_spec


def _minimal_spec(**overrides: object) -> dict:
    base = {
        "version": 1,
        "meta": {"name": "test_flow", "description": "test"},
        "policy": {},
        "phases": [
            {
                "id": "p1",
                "title": "Phase 1",
                "steps": [
                    {
                        "id": "a1",
                        "type": "agent",
                        "label": "worker",
                        "prompt": "do work",
                    }
                ],
            }
        ],
    }
    base.update(overrides)
    return base


def test_parse_minimal_agent_step() -> None:
    spec = parse_workflow_spec(_minimal_spec())
    assert spec.meta.name == "test_flow"
    assert len(spec.phases) == 1
    assert spec.phases[0].steps[0].type == "agent"


def test_parse_wraps_spec_key() -> None:
    spec = parse_workflow_spec({"spec": _minimal_spec()})
    assert spec.meta.name == "test_flow"


def test_synthesis_must_reference_prior_step() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "syn",
            "type": "synthesis",
            "label": "merge",
            "prompt_template": "use {{outputs.missing}}",
        }
    ]
    with pytest.raises(WorkflowValidationError, match="unknown output"):
        parse_workflow_spec(raw)


def test_agent_prompt_output_refs_are_validated() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "a1",
            "type": "agent",
            "label": "worker",
            "prompt": "use {{outputs.missing}}",
        }
    ]
    with pytest.raises(WorkflowValidationError, match="unknown output"):
        parse_workflow_spec(raw)


def test_fanout_concurrency_must_be_integer() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "fan",
            "type": "fanout",
            "items": ["a"],
            "concurrency": "many",
            "agent": {"prompt_template": "x {{item}}"},
        }
    ]
    with pytest.raises(WorkflowValidationError, match="concurrency"):
        parse_workflow_spec(raw)


def test_fanout_items_max() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "fan",
            "type": "fanout",
            "items": [str(i) for i in range(20)],
            "agent": {"prompt_template": "x {{item}}"},
        }
    ]
    with pytest.raises(WorkflowValidationError, match="exceeds max"):
        parse_workflow_spec(raw)


def test_fanout_accepts_flat_agent_config() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "fan",
            "type": "fanout",
            "items": ["engine", "tools"],
            "label_template": "inspect {{item}}",
            "agent_type": "explore",
            "prompt_template": "Inspect {{item}}.",
        }
    ]

    spec = parse_workflow_spec(raw)

    step = spec.phases[0].steps[0]
    assert step.type == "fanout"
    assert step.agent.label_template == "inspect {{item}}"
    assert step.agent.agent_type == "explore"
    assert step.agent.prompt_template == "Inspect {{item}}."


def test_fanout_merges_flat_fields_into_partial_agent() -> None:
    """When agent={type:explore} exists but prompt_template is on step, merge."""
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "fan",
            "type": "fanout",
            "items": ["goal", "workflow", "tools"],
            "agent": {"type": "explore"},
            "label_template": "check_{{item}}",
            "prompt_template": "Inspect {{item}} directory.",
        }
    ]
    spec = parse_workflow_spec(raw)
    step = spec.phases[0].steps[0]
    assert step.type == "fanout"
    assert step.agent.agent_type == "explore"
    assert step.agent.prompt_template == "Inspect {{item}} directory."
    assert step.agent.label_template == "check_{{item}}"


def test_duplicate_step_id_rejected() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"].append(
        {
            "id": "a1",
            "type": "agent",
            "label": "dup",
            "prompt": "again",
        }
    )
    with pytest.raises(WorkflowValidationError, match="duplicate"):
        parse_workflow_spec(raw)


def test_fanout_items_from_ok() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "plan",
            "type": "agent",
            "label": "planner",
            "prompt": "plan {{task}}",
            "output_schema": {"type": "object"},
        },
        {
            "id": "fan",
            "type": "fanout",
            "items_from": {"step": "plan", "path": "$.targets"},
            "agent": {"prompt_template": "inspect {{item}}"},
        },
    ]
    spec = parse_workflow_spec(raw)
    step = spec.phases[0].steps[1]
    assert step.type == "fanout"
    assert step.items is None
    assert step.items_from is not None
    assert step.items_from.step == "plan"
    assert step.items_from.path == "$.targets"


def test_fanout_items_and_items_from_mutually_exclusive() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "fan",
            "type": "fanout",
            "items": ["a"],
            "items_from": {"step": "plan", "path": "$.targets"},
            "agent": {"prompt_template": "x {{item}}"},
        }
    ]
    with pytest.raises(WorkflowValidationError, match="mutually exclusive"):
        parse_workflow_spec(raw)


def test_fanout_items_from_unknown_step() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "fan",
            "type": "fanout",
            "items_from": {"step": "missing", "path": "$.targets"},
            "agent": {"prompt_template": "x {{item}}"},
        }
    ]
    with pytest.raises(WorkflowValidationError, match="unknown step"):
        parse_workflow_spec(raw)


def test_fanout_items_from_before_source() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "fan",
            "type": "fanout",
            "items_from": {"step": "plan", "path": "$.targets"},
            "agent": {"prompt_template": "x {{item}}"},
        },
        {
            "id": "plan",
            "type": "agent",
            "label": "planner",
            "prompt": "plan",
        },
    ]
    with pytest.raises(WorkflowValidationError, match="before it runs"):
        parse_workflow_spec(raw)


def test_fanout_items_from_invalid_path() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "plan",
            "type": "agent",
            "label": "planner",
            "prompt": "plan",
        },
        {
            "id": "fan",
            "type": "fanout",
            "items_from": {"step": "plan", "path": "targets"},
            "agent": {"prompt_template": "x {{item}}"},
        },
    ]
    with pytest.raises(WorkflowValidationError, match="items_from.path"):
        parse_workflow_spec(raw)


def test_loop_step_parses() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "lp",
            "type": "loop",
            "max_rounds": 3,
            "until": {"path": "$.done", "equals": True},
            "steps": [
                {
                    "id": "chk",
                    "type": "agent",
                    "label": "check",
                    "prompt": "round {{round}}",
                    "output_schema": {"type": "object"},
                }
            ],
        }
    ]
    spec = parse_workflow_spec(raw)
    step = spec.phases[0].steps[0]
    assert step.type == "loop"
    assert step.max_rounds == 3
    assert step.until is not None
    assert step.until.path == "$.done"
    assert len(step.steps) == 1


def test_nested_loop_rejected() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"] = [
        {
            "id": "lp",
            "type": "loop",
            "max_rounds": 2,
            "steps": [
                {
                    "id": "inner",
                    "type": "loop",
                    "max_rounds": 2,
                    "steps": [
                        {
                            "id": "a",
                            "type": "agent",
                            "label": "x",
                            "prompt": "y",
                        }
                    ],
                }
            ],
        }
    ]
    with pytest.raises(WorkflowValidationError, match="nested loop"):
        parse_workflow_spec(raw)


def test_agent_step_timeout_seconds_parsed() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"][0]["timeout_seconds"] = 30
    spec = parse_workflow_spec(raw)
    step = spec.phases[0].steps[0]
    assert step.type == "agent"
    assert step.timeout_seconds == 30


def test_agent_step_timeout_seconds_out_of_range() -> None:
    raw = _minimal_spec()
    raw["phases"][0]["steps"][0]["timeout_seconds"] = 0
    with pytest.raises(WorkflowValidationError, match="timeout_seconds"):
        parse_workflow_spec(raw)

    raw2 = _minimal_spec()
    raw2["phases"][0]["steps"][0]["timeout_seconds"] = 3601
    with pytest.raises(WorkflowValidationError, match="timeout_seconds"):
        parse_workflow_spec(raw2)
