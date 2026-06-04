"""Workflow IR validation tests."""

from __future__ import annotations

import pytest

from deepseek_tui.workflow.validate import WorkflowValidationError, parse_workflow_spec


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
