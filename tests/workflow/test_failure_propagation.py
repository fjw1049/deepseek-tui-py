"""Regression tests for scheduler failure propagation (#1, #2).

#1: on_error=continue must skip non-partial successors of a failed node
    instead of leaving them deadlocked in the ready-set. Partial
    reduce/synthesis successors must still be admitted so they can run on
    the remaining completed predecessors.

#2: fanout/pipeline item-level failures must be recorded in
    ctx.failed_step_ids (as step_id:item keys) so resume can
    distinguish "not yet run" from "ran and failed".
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deepseek_tui.workflow.models import (
    StepOutput,
    make_step_output,
    parse_workflow_spec,
)
from deepseek_tui.workflow.runtime import run_workflow


class _FakeRunner:
    """Fake runner whose per-label behavior is configurable."""

    def __init__(
        self,
        *,
        fail_labels: set[str] | None = None,
        none_labels: set[str] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.prompts: list[str] = []
        self._fail = fail_labels or set()
        self._none = none_labels or set()

    async def run(
        self,
        *,
        prompt: str,
        label: str,
        agent_type: str = "general",
        model: str | None = None,
        allowed_tools: list[str] | None = None,
        output_schema: dict | None = None,
        policy: object = None,
        cancel_event: asyncio.Event | None = None,
        on_agent_id: object = None,
        timeout_seconds: float | None = None,
    ) -> StepOutput | None:
        self.calls.append(label)
        self.prompts.append(prompt)
        if label in self._fail:
            raise RuntimeError(f"boom:{label}")
        if label in self._none:
            return None
        if callable(on_agent_id):
            on_agent_id(f"aid-{label}")
        return make_step_output(f"done:{label}")


def _v2_spec(nodes: list[dict], edges: list[dict], **policy: Any):
    spec_raw: dict[str, Any] = {
        "version": 2,
        "meta": {"name": "failprop", "description": "d"},
        "policy": {"on_error": "continue", **policy},
        "graph": {"nodes": nodes, "edges": edges},
    }
    return parse_workflow_spec(spec_raw)


# ---------------------------------------------------------------------------
# #1a: continue mode - failed agent's plain successor is skipped, not deadlocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_continue_skips_plain_successor_of_failed_node() -> None:
    """a (fails) -> b (plain agent). b must be skipped, not run.

    Before the fix, b's ready_ids check required a in (completed|skipped),
    but a was in failed_step_ids only - b never became ready and was only
    force-skipped by the terminal cleanup, making it look like a silent
    no-op rather than an intentional skip.
    """
    runner = _FakeRunner(fail_labels={"a"})
    spec = _v2_spec(
        nodes=[
            {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
            {"id": "b", "type": "agent", "label": "b", "prompt": "B after a"},
        ],
        edges=[{"from": "a", "to": "b"}],
    )
    result = await run_workflow(spec, runner=runner)

    assert "a" in runner.calls
    assert "b" not in runner.calls, "plain successor of failed node must be skipped"
    node_status = {n.id: n.status for n in result.snapshot.nodes}
    assert node_status["a"] == "error"
    assert node_status["b"] == "skipped"


# ---------------------------------------------------------------------------
# #1b: continue mode - partial reduce still runs after a predecessor fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_continue_partial_reduce_runs_after_pred_failure() -> None:
    """a (ok) + b (fails) -> reduce (partial). reduce must still run.

    The fix to _mark_successors_skipped must NOT skip partial joins - they
    are admitted by ready_ids when at least one predecessor completed.
    """
    runner = _FakeRunner(fail_labels={"b"})
    spec = _v2_spec(
        nodes=[
            {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
            {"id": "b", "type": "agent", "label": "b", "prompt": "B"},
            {
                "id": "r",
                "type": "reduce",
                "label": "merge",
                "from": ["a", "b"],
                "prompt_template": "merge {{outputs}}",
                "source_policy": "partial",
            },
        ],
        edges=[
            {"from": "a", "to": "r"},
            {"from": "b", "to": "r"},
        ],
    )
    result = await run_workflow(spec, runner=runner)

    assert "a" in runner.calls
    assert "b" in runner.calls
    assert "merge" in runner.calls, "partial reduce must run despite b failure"
    node_status = {n.id: n.status for n in result.snapshot.nodes}
    assert node_status["a"] == "done"
    assert node_status["b"] == "error"
    assert node_status["r"] == "done"


# ---------------------------------------------------------------------------
# #1c: continue mode - non-partial synthesis is skipped when pred fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_continue_success_synthesis_skipped_when_pred_fails() -> None:
    """a (fails) -> synthesis (source_policy=success). synthesis must be skipped."""
    runner = _FakeRunner(fail_labels={"a"})
    spec = _v2_spec(
        nodes=[
            {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
            {
                "id": "s",
                "type": "synthesis",
                "label": "sum",
                "prompt_template": "sum {{outputs}}",
                "source_policy": "success",
            },
        ],
        edges=[{"from": "a", "to": "s"}],
    )
    result = await run_workflow(spec, runner=runner)

    assert "a" in runner.calls
    assert "sum" not in runner.calls, "success synthesis must not run when pred failed"
    node_status = {n.id: n.status for n in result.snapshot.nodes}
    assert node_status["s"] == "skipped"


# ---------------------------------------------------------------------------
# #1d: diamond - partial join keeps alternate completed branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_continue_diamond_partial_join_keeps_alternate_branch() -> None:
    """a (ok) -> r; b (fails) -> r. r is partial, must run on a's output.

    Guards against _mark_successors_skipped over-eagerly skipping a partial
    join that still has a viable completed predecessor (#6).
    """
    runner = _FakeRunner(fail_labels={"b"})
    spec = _v2_spec(
        nodes=[
            {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
            {"id": "b", "type": "agent", "label": "b", "prompt": "B"},
            {
                "id": "r",
                "type": "reduce",
                "label": "join",
                "from": ["a", "b"],
                "prompt_template": "join {{outputs}}",
                "source_policy": "partial",
            },
            {"id": "c", "type": "agent", "label": "c", "prompt": "C after join"},
        ],
        edges=[
            {"from": "a", "to": "r"},
            {"from": "b", "to": "r"},
            {"from": "r", "to": "c"},
        ],
    )
    result = await run_workflow(spec, runner=runner)

    assert "join" in runner.calls, "partial join must run on completed branch a"
    assert "c" in runner.calls, "successor of completed join must run"
    node_status = {n.id: n.status for n in result.snapshot.nodes}
    assert node_status["r"] == "done"
    assert node_status["c"] == "done"


# ---------------------------------------------------------------------------
# #2: fanout partial item failure records failed item keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_partial_failure_records_failed_item_keys() -> None:
    """fanout with 3 items, 1 fails (raises). The failed item key must land in
    failed_step_ids so resume can distinguish it from un-run items.
    """
    captured: dict[str, Any] = {}

    def on_checkpoint(ctx: Any, snap: Any, logs: Any) -> None:
        captured["failed_step_ids"] = list(ctx.failed_step_ids)
        captured["outputs_keys"] = list(ctx.outputs.keys())

    runner = _FakeRunner(fail_labels={"bad"})
    spec = _v2_spec(
        nodes=[
            {
                "id": "fan",
                "type": "fanout",
                "items": ["good1", "good2", "bad"],
                "agent": {
                    "label_template": "{{item}}",
                    "prompt_template": "work {{item}}",
                },
            }
        ],
        edges=[],
    )
    await run_workflow(spec, runner=runner, on_checkpoint=on_checkpoint)

    assert {"good1", "good2", "bad"} <= set(runner.calls)
    assert "fan:bad" in captured.get("failed_step_ids", []), (
        "failed fanout item key must be in failed_step_ids for resume"
    )
    assert "fan:good1" in captured.get("outputs_keys", [])
    assert "fan:good2" in captured.get("outputs_keys", [])
    assert "fan:bad" not in captured.get("outputs_keys", [])


# ---------------------------------------------------------------------------
# #2b: fanout partial failure (result is None) records failed item keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_partial_none_result_records_failed_item_keys() -> None:
    """Same as above but the failure is a None return (agent failed), not an
    exception. Both paths must record the failed item key."""
    captured: dict[str, Any] = {}

    def on_checkpoint(ctx: Any, snap: Any, logs: Any) -> None:
        captured["failed_step_ids"] = list(ctx.failed_step_ids)

    runner = _FakeRunner(none_labels={"dead"})
    spec = _v2_spec(
        nodes=[
            {
                "id": "fan",
                "type": "fanout",
                "items": ["live", "dead"],
                "agent": {
                    "label_template": "{{item}}",
                    "prompt_template": "work {{item}}",
                },
            }
        ],
        edges=[],
    )
    await run_workflow(spec, runner=runner, on_checkpoint=on_checkpoint)

    assert "fan:dead" in captured.get("failed_step_ids", []), (
        "None-returning fanout item must be in failed_step_ids"
    )
    assert "fan:live" not in captured.get("failed_step_ids", [])


# ---------------------------------------------------------------------------
# #2c: pipeline partial failure records failed item keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_partial_failure_records_failed_item_keys() -> None:
    """pipeline with 2 items, 1 fails. Failed item key must be recorded."""
    captured: dict[str, Any] = {}

    def on_checkpoint(ctx: Any, snap: Any, logs: Any) -> None:
        captured["failed_step_ids"] = list(ctx.failed_step_ids)

    runner = _FakeRunner(fail_labels={"p-bad"})
    spec = _v2_spec(
        nodes=[
            {
                "id": "pipe",
                "type": "pipeline",
                "items": ["good", "bad"],
                "stages": [
                    {
                        "label_template": "p-{{item}}",
                        "prompt_template": "stage {{item}}",
                    }
                ],
            }
        ],
        edges=[],
    )
    await run_workflow(spec, runner=runner, on_checkpoint=on_checkpoint)

    assert "pipe:bad" in captured.get("failed_step_ids", []), (
        "failed pipeline item must be in failed_step_ids"
    )
    assert "pipe:good" not in captured.get("failed_step_ids", [])
