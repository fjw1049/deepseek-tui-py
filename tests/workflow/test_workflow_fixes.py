"""Regression tests for workflow status / synthesis source_policy / result summary."""

from __future__ import annotations

import json
from typing import Any

import pytest

from deepseek_tui.workflow.dag import compile_workflow_graph
from deepseek_tui.workflow.models import (
    AgentStep,
    SynthesisStep,
    WorkflowMeta,
    WorkflowPhase,
    WorkflowPolicy,
    WorkflowRunResult,
    WorkflowSnapshot,
    WorkflowSpec,
    WorkflowStepError,
    make_step_output,
    parse_workflow_spec,
)
from deepseek_tui.workflow.runtime import (
    format_workflow_result_body,
    resolve_workflow_terminal_status,
    run_workflow,
)


class FakeRunner:
    def __init__(self, replies: dict[str, Any] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[str] = []

    async def run(self, *, prompt: str, label: str, **kwargs: Any) -> Any:
        self.calls.append(label)
        raw = self.replies.get(label, self.replies.get("*", "ok"))
        if isinstance(raw, Exception):
            raise raw
        if raw is None:
            return None
        if isinstance(raw, dict):
            return make_step_output(json.dumps(raw), raw)
        return make_step_output(str(raw))


def test_synthesis_source_policy_parsed_and_serialized() -> None:
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "syn", "description": "d"},
            "policy": {},
            "graph": {
                "nodes": [
                    {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
                    {
                        "id": "s",
                        "type": "synthesis",
                        "label": "sum",
                        "source_policy": "success",
                        "prompt_template": "{{outputs.a}}",
                    },
                ],
                "edges": [{"from": "a", "to": "s"}],
            },
        }
    )
    g = compile_workflow_graph(spec)
    step = g.nodes["s"]
    assert isinstance(step, SynthesisStep)
    assert step.source_policy == "success"
    assert g.ready_ids(set(), {"a"}, set()) == []
    assert g.ready_ids({"a"}, set(), set()) == ["s"]


def test_synthesis_partial_requires_at_least_one_completed_pred() -> None:
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "syn", "description": "d"},
            "policy": {},
            "graph": {
                "nodes": [
                    {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
                    {
                        "id": "s",
                        "type": "synthesis",
                        "label": "sum",
                        "source_policy": "partial",
                        "prompt_template": "{{outputs.a}}",
                    },
                ],
                "edges": [{"from": "a", "to": "s"}],
            },
        }
    )
    g = compile_workflow_graph(spec)
    # All preds failed → not ready (no successful source to join).
    assert g.ready_ids(set(), {"a"}, set()) == []


@pytest.mark.asyncio
async def test_linear_chain_skips_synthesis_when_only_pred_failed() -> None:
    """plan→inspect→final: inspect failure must not run final under partial."""
    runner = FakeRunner({"planner": None})
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="repo_like", description="d"),
        policy=WorkflowPolicy(on_error="continue", max_agents=8, concurrency=2),
        phases=[
            WorkflowPhase(
                id="plan",
                title="Plan",
                steps=[
                    AgentStep(
                        id="plan",
                        type="agent",
                        label="planner",
                        prompt="plan",
                    )
                ],
            ),
            WorkflowPhase(
                id="inspect",
                title="Inspect",
                steps=[
                    AgentStep(
                        id="inspect",
                        type="agent",
                        label="inspect",
                        prompt="inspect {{previous}}",
                    )
                ],
            ),
            WorkflowPhase(
                id="synthesis",
                title="Synthesis",
                steps=[
                    SynthesisStep(
                        id="final",
                        type="synthesis",
                        label="final summary",
                        prompt_template="Plan:\n{{outputs.plan}}\nInspect:\n{{outputs.inspect}}",
                        source_policy="partial",
                    )
                ],
            ),
        ],
    )
    result = await run_workflow(spec, runner=runner, task="review")
    assert "final summary" not in runner.calls
    assert "planner" in runner.calls
    assert result.snapshot.error_count >= 1
    assert result.snapshot.done_count == 0
    assert resolve_workflow_terminal_status(result) == "failed"


@pytest.mark.asyncio
async def test_synthesis_success_policy_blocks_on_failed_pred() -> None:
    runner = FakeRunner({"a": None, "sum": "should-not-run"})
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "syn", "description": "d"},
            "policy": {"on_error": "continue"},
            "graph": {
                "nodes": [
                    {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
                    {
                        "id": "s",
                        "type": "synthesis",
                        "label": "sum",
                        "source_policy": "success",
                        "prompt_template": "{{outputs.a}}",
                    },
                ],
                "edges": [{"from": "a", "to": "s"}],
            },
        }
    )
    result = await run_workflow(spec, runner=runner, task="t")
    assert runner.calls == ["a"]
    assert resolve_workflow_terminal_status(result) == "failed"


def test_resolve_terminal_status_partial_success_stays_completed() -> None:
    snap = WorkflowSnapshot(
        name="x",
        description="d",
        done_count=1,
        error_count=1,
        agent_count=2,
    )
    result = WorkflowRunResult(
        meta=WorkflowMeta(name="x", description="d"),
        result={"ok": True},
        snapshot=snap,
        logs=[],
        duration_ms=1,
        errors=[WorkflowStepError(step_id="a", error="boom")],
    )
    assert resolve_workflow_terminal_status(result) == "completed"


def test_format_workflow_result_body_caps_findings() -> None:
    body = format_workflow_result_body(
        {
            "ok": False,
            "verdict": "x" * 400,
            "findings": [f"finding-{i} " + ("y" * 80) for i in range(8)],
        }
    )
    assert "ok: False" in body
    assert "verdict:" in body
    assert body.count("finding-") == 3
    assert "+5 more" in body
    assert len(body) < 2000
