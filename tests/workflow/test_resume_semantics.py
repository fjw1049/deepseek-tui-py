"""Industry-style workflow resume: keep successes, retry failures."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.workflow.models import (
    StepOutput,
    WorkflowSnapshot,
    make_step_output,
    parse_workflow_spec,
)
from deepseek_tui.workflow.runtime import run_workflow
from deepseek_tui.workflow.store import (
    checkpoint_run,
    create_run,
    prepare_workflow_resume,
)


class _FakeRunner:
    def __init__(
        self,
        *,
        fail_labels: set[str] | None = None,
        fail_once: set[str] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._fail = fail_labels or set()
        self._fail_once = set(fail_once or set())
        self._failed_once: set[str] = set()

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
        resume_agent_id: str | None = None,
        force_retry: bool = False,
        on_start_mode: object = None,
        **_kwargs: Any,
    ) -> StepOutput | None:
        self.calls.append(label)
        mode = "spawn"
        if resume_agent_id and not force_retry:
            mode = "resume"
            aid = resume_agent_id
        else:
            if resume_agent_id or force_retry:
                mode = "retry"
            aid = f"aid-{label}"
        if callable(on_start_mode):
            on_start_mode(mode)
        if label in self._fail:
            raise RuntimeError(f"boom:{label}")
        if label in self._fail_once and label not in self._failed_once:
            self._failed_once.add(label)
            raise RuntimeError(f"transient:{label}")
        if callable(on_agent_id):
            on_agent_id(aid)
        return make_step_output(f"done:{label}")


def _v2_spec(nodes: list[dict], edges: list[dict], **policy: Any):
    return parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "resume", "description": "d"},
            "policy": {"on_error": "continue", **policy},
            "graph": {"nodes": nodes, "edges": edges},
        }
    )


def test_prepare_workflow_resume_keeps_success_retries_failure(tmp_path: Path) -> None:
    spec = _v2_spec(
        nodes=[
            {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
            {"id": "b", "type": "agent", "label": "b", "prompt": "B"},
        ],
        edges=[{"from": "a", "to": "b"}],
    )
    record = create_run(spec, task="t", workspace=tmp_path)
    checkpoint_run(
        record,
        completed_step_ids=["a"],
        outputs={"a": make_step_output("done:a")},
        snapshot=WorkflowSnapshot(name="resume", description="d"),
        logs=[],
        status="failed",
        workspace=tmp_path,
        runtime_graph={"nodes": {}, "edges": [], "phase_of": {}, "phase_titles": {}},
        dynamic_states={"dyn": {"round": 2}},
        budgets_used={"dyn": 1},
        generated_node_ids=["g1"],
        skipped_step_ids=["b"],
        failed_step_ids=["b", "fan:bad"],
        estimated_tokens_used=42,
        agent_bindings={
            "b": {
                "agent_id": "agent_b1",
                "status": "cancelled",
                "mode": "spawn",
            }
        },
    )

    plan = prepare_workflow_resume(record)
    assert plan.skip_step_ids == {"a"}
    assert "a" in plan.initial_outputs
    assert plan.resume_ctx["failed_step_ids"] == []
    assert plan.resume_ctx["skipped_step_ids"] == []
    assert plan.resume_ctx["dynamic_states"] == {"dyn": {"round": 2}}
    assert plan.resume_ctx["budgets_used"] == {"dyn": 1}
    assert plan.resume_ctx["generated_node_ids"] == ["g1"]
    assert plan.resume_ctx["estimated_tokens_used"] == 42
    assert plan.resume_ctx["agent_bindings"]["b"]["agent_id"] == "agent_b1"
    assert plan.initial_graph is not None
    assert record.failed_step_ids == []
    assert record.skipped_step_ids == []
    assert record.agent_bindings["b"]["agent_id"] == "agent_b1"


@pytest.mark.asyncio
async def test_resume_retries_failed_node_keeps_completed(tmp_path: Path) -> None:
    """Failed node is retried; completed predecessor is not re-run."""
    spec = _v2_spec(
        nodes=[
            {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
            {"id": "b", "type": "agent", "label": "b", "prompt": "B"},
        ],
        edges=[{"from": "a", "to": "b"}],
    )
    record = create_run(spec, task="t", workspace=tmp_path)
    checkpoint_run(
        record,
        completed_step_ids=["a"],
        outputs={"a": make_step_output("done:a")},
        snapshot=WorkflowSnapshot(name="resume", description="d"),
        logs=[],
        status="failed",
        workspace=tmp_path,
        failed_step_ids=["b"],
        skipped_step_ids=[],
    )

    plan = prepare_workflow_resume(record)
    runner = _FakeRunner()
    result = await run_workflow(
        spec,
        runner=runner,
        initial_outputs=plan.initial_outputs,
        skip_step_ids=plan.skip_step_ids,
        resume_ctx=plan.resume_ctx,
    )
    assert runner.calls == ["b"], "resume must retry failed b, not re-run a"
    assert result.snapshot.done_count >= 1 or "b" in (result.result or {})


@pytest.mark.asyncio
async def test_resume_fanout_retries_failed_item_keeps_success(tmp_path: Path) -> None:
    runner = _FakeRunner(fail_labels={"bad"})
    spec = _v2_spec(
        nodes=[
            {
                "id": "fan",
                "type": "fanout",
                "items": ["good", "bad"],
                "agent": {
                    "label_template": "{{item}}",
                    "prompt_template": "work {{item}}",
                },
            }
        ],
        edges=[],
    )
    await run_workflow(spec, runner=runner)

    record = create_run(spec, task="t", workspace=tmp_path)
    checkpoint_run(
        record,
        completed_step_ids=[],
        outputs={"fan:good": make_step_output("done:good")},
        snapshot=WorkflowSnapshot(name="resume", description="d"),
        logs=[],
        status="interrupted",
        workspace=tmp_path,
        failed_step_ids=["fan:bad"],
    )

    plan = prepare_workflow_resume(record)
    runner2 = _FakeRunner()
    await run_workflow(
        spec,
        runner=runner2,
        initial_outputs=plan.initial_outputs,
        skip_step_ids=plan.skip_step_ids,
        resume_ctx=plan.resume_ctx,
    )
    assert "good" not in runner2.calls, "successful fanout item must not re-run"
    assert "bad" in runner2.calls, "failed fanout item must retry on resume"


@pytest.mark.asyncio
async def test_resume_pipeline_skips_completed_items(tmp_path: Path) -> None:
    spec = _v2_spec(
        nodes=[
            {
                "id": "pipe",
                "type": "pipeline",
                "items": ["one", "two"],
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
    record = create_run(spec, task="t", workspace=tmp_path)
    checkpoint_run(
        record,
        completed_step_ids=[],
        outputs={"pipe:one": make_step_output("done:one")},
        snapshot=WorkflowSnapshot(name="resume", description="d"),
        logs=[],
        status="interrupted",
        workspace=tmp_path,
    )
    plan = prepare_workflow_resume(record)
    runner = _FakeRunner()
    await run_workflow(
        spec,
        runner=runner,
        initial_outputs=plan.initial_outputs,
        skip_step_ids=plan.skip_step_ids,
        resume_ctx=plan.resume_ctx,
    )
    assert "p-one" not in runner.calls
    assert "p-two" in runner.calls


@pytest.mark.asyncio
async def test_resume_prefers_bound_agent_id(tmp_path: Path) -> None:
    """Unfinished unit with agent_binding must true-resume that id, not spawn."""
    class _TrackingRunner(_FakeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.resume_ids: list[str | None] = []
            self.modes: list[str] = []

        async def run(self, **kwargs: Any) -> StepOutput | None:  # type: ignore[override]
            self.resume_ids.append(kwargs.get("resume_agent_id"))
            mode_cb = kwargs.get("on_start_mode")
            orig = mode_cb

            def _capture(mode: str) -> None:
                self.modes.append(mode)
                if callable(orig):
                    orig(mode)

            kwargs["on_start_mode"] = _capture
            return await super().run(**kwargs)

    spec = _v2_spec(
        nodes=[{"id": "b", "type": "agent", "label": "b", "prompt": "B"}],
        edges=[],
    )
    record = create_run(spec, task="t", workspace=tmp_path)
    checkpoint_run(
        record,
        completed_step_ids=[],
        outputs={},
        snapshot=WorkflowSnapshot(name="resume", description="d"),
        logs=[],
        status="interrupted",
        workspace=tmp_path,
        agent_bindings={
            "b": {"agent_id": "agent_keep", "status": "cancelled", "mode": "spawn"}
        },
    )
    plan = prepare_workflow_resume(record)
    runner = _TrackingRunner()
    await run_workflow(
        spec,
        runner=runner,
        initial_outputs=plan.initial_outputs,
        skip_step_ids=plan.skip_step_ids,
        resume_ctx=plan.resume_ctx,
    )
    assert runner.resume_ids == ["agent_keep"]
    assert runner.modes == ["resume"]
    assert runner.calls == ["b"]


@pytest.mark.asyncio
async def test_deepseek_runner_resumes_same_agent(tmp_path: Path) -> None:
    from deepseek_tui.tools.subagent import (
        SpawnRequest,
        SubAgentAssignment,
        SubAgentManager,
        SubAgentStatusKind,
        SubAgentType,
    )
    from deepseek_tui.tools.subagent.manager import SubAgentRuntime
    from deepseek_tui.workflow.models import WorkflowPolicy
    from deepseek_tui.workflow.runtime import DeepSeekAgentRunner

    async def _hang(agent, cancel):
        await cancel.wait()
        raise asyncio.CancelledError

    from deepseek_tui.config.models import Config

    mgr = SubAgentManager(workspace=tmp_path, executor=_hang, state_path=tmp_path / "sa.json")
    runtime = SubAgentRuntime(
        manager=mgr,
        client=object(),  # type: ignore[arg-type]
        model="deepseek-chat",
        config=Config(),
        workspace=tmp_path,
    )
    mgr.attach_loop_runtime(runtime)
    snap = await mgr.spawn(
        SpawnRequest(
            prompt="work",
            agent_type=SubAgentType.GENERAL,
            assignment=SubAgentAssignment(objective="work"),
        )
    )
    await asyncio.sleep(0.05)
    await mgr.cancel(snap.agent_id)
    assert (await mgr.get_result(snap.agent_id)).status.kind is SubAgentStatusKind.CANCELLED

    # Swap executor so resume completes quickly.
    async def _done(agent, cancel):
        return "finished"

    mgr._executor = _done
    runner = DeepSeekAgentRunner(mgr, runtime, workspace=tmp_path)
    out = await runner.run(
        prompt="work",
        label="step",
        agent_type="general",
        model=None,
        allowed_tools=None,
        output_schema=None,
        policy=WorkflowPolicy(),
        cancel_event=None,
        resume_agent_id=snap.agent_id,
    )
    assert out is not None
    assert out.text == "finished"
    final = await mgr.get_result(snap.agent_id)
    assert final.status.kind is SubAgentStatusKind.COMPLETED
