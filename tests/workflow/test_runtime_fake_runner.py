"""Workflow runtime tests with a fake runner."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deepseek_tui.tools.subagent.types import SubAgentStatus, SubAgentStatusKind
from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    FanoutStep,
    ItemsFrom,
    PipelineStage,
    PipelineStep,
    StepOutput,
    SynthesisStep,
    WorkflowMeta,
    WorkflowPhase,
    WorkflowPolicy,
    WorkflowSnapshot,
    WorkflowSpec,
    make_step_output,
)
from deepseek_tui.workflow.runtime import (
    DeepSeekAgentRunner,
    WorkflowFailedError,
    run_workflow,
)


class FakeRunner:
    def __init__(
        self,
        responses: dict[str, str] | None = None,
        *,
        structured_by_label: dict[str, object] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.prompts: list[str] = []
        self._responses = responses or {}
        self._structured_by_label = structured_by_label or {}
        self.timeout_seconds_seen: list[float | None] = []

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
        self.timeout_seconds_seen.append(timeout_seconds)
        if cancel_event is not None and cancel_event.is_set():
            return None
        text = self._responses.get(label, f"done:{label}")
        if label in self._structured_by_label:
            structured = self._structured_by_label[label]
        else:
            structured = {"verdict": "ok"} if output_schema else None
        return make_step_output(text, structured)


@pytest.mark.asyncio
async def test_run_workflow_agent_and_synthesis() -> None:
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(
                        id="a1",
                        type="agent",
                        label="worker",
                        prompt="work",
                    ),
                    SynthesisStep(
                        id="syn",
                        type="synthesis",
                        label="merge",
                        prompt_template="all: {{outputs.a1}}",
                        output_schema={"type": "object"},
                    ),
                ],
            )
        ],
    )
    runner = FakeRunner({"worker": "branch result", "merge": "final text"})
    result = await run_workflow(spec, runner=runner)
    assert result.result == {"verdict": "ok"}
    assert runner.calls == ["worker", "merge"]


@pytest.mark.asyncio
async def test_token_budget_warning_emitted() -> None:
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(token_budget=50000),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(
                        id="a1",
                        type="agent",
                        label="worker",
                        prompt="work",
                    ),
                ],
            )
        ],
    )
    logs: list[str] = []
    runner = FakeRunner({"worker": "done"})
    await run_workflow(spec, runner=runner, on_log=logs.append)
    assert any("not yet enforced" in msg for msg in logs)


@pytest.mark.asyncio
async def test_token_budget_absent_no_warning() -> None:
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(
                        id="a1",
                        type="agent",
                        label="worker",
                        prompt="work",
                    ),
                ],
            )
        ],
    )
    logs: list[str] = []
    runner = FakeRunner({"worker": "done"})
    await run_workflow(spec, runner=runner, on_log=logs.append)
    assert not any("token_budget" in msg for msg in logs)


@pytest.mark.asyncio
async def test_fail_fast_raises() -> None:
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(on_error="fail_fast"),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(
                        id="a1",
                        type="agent",
                        label="fail",
                        prompt="x",
                    ),
                ],
            )
        ],
    )

    class FailingRunner(FakeRunner):
        async def run(self, **kwargs: object) -> StepOutput | None:
            return None

    with pytest.raises(WorkflowFailedError):
        await run_workflow(spec, runner=FailingRunner())


@pytest.mark.asyncio
async def test_fail_fast_raises_on_partial_fanout_failure() -> None:
    class PartiallyFailingRunner(FakeRunner):
        async def run(self, **kwargs: object) -> StepOutput | None:
            if kwargs.get("label") == "bad":
                raise RuntimeError("boom")
            return make_step_output(f"done:{kwargs.get('label')}")

    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(on_error="fail_fast"),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    FanoutStep(
                        id="fan",
                        type="fanout",
                        items=["good", "bad"],
                        agent=AgentStepConfig(
                            label_template="{{item}}",
                            prompt_template="work {{item}}",
                        ),
                    ),
                ],
            )
        ],
    )

    with pytest.raises(WorkflowFailedError, match="bad"):
        await run_workflow(spec, runner=PartiallyFailingRunner())


@pytest.mark.asyncio
async def test_pipeline_respects_policy_concurrency() -> None:
    class CountingRunner(FakeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.current = 0
            self.max_seen = 0

        async def run(self, **kwargs: object) -> StepOutput | None:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)
            await asyncio.sleep(0.01)
            self.current -= 1
            return make_step_output(f"done:{kwargs.get('label')}")

    runner = CountingRunner()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(concurrency=1),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    PipelineStep(
                        id="pipe",
                        type="pipeline",
                        items=["a", "b", "c"],
                        stages=[
                            PipelineStage(
                                label_template="stage {{item}}",
                                prompt_template="work {{item}}",
                            )
                        ],
                    ),
                ],
            )
        ],
    )

    await run_workflow(spec, runner=runner)
    assert runner.max_seen == 1


@pytest.mark.asyncio
async def test_fanout_items_from_structured_targets() -> None:
    runner = FakeRunner(
        structured_by_label={
            "planner": {"targets": ["engine", "tools"]},
        }
    )
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(
                        id="plan",
                        type="agent",
                        label="planner",
                        prompt="plan {{task}}",
                        output_schema={"type": "object"},
                    ),
                    FanoutStep(
                        id="inspect",
                        type="fanout",
                        items_from=ItemsFrom(step="plan", path="$.targets"),
                        agent=AgentStepConfig(
                            label_template="inspect {{item}}",
                            prompt_template="look at {{item}} for {{task}}",
                        ),
                    ),
                ],
            )
        ],
    )

    result = await run_workflow(spec, runner=runner, task="review repo")
    assert "planner" in runner.calls
    assert runner.calls.count("inspect engine") == 1
    assert runner.calls.count("inspect tools") == 1
    assert runner.calls.index("inspect engine") < runner.calls.index("inspect tools")
    assert "review repo" in runner.prompts[0]
    assert any("engine" in p and "review repo" in p for p in runner.prompts)
    # Fanout records one aggregate step plus the plan step in snapshot.agents.
    assert result.snapshot.done_count == 2
    assert isinstance(result.result, dict)
    assert "inspect" in result.result
    assert "plan" in result.result



@pytest.mark.asyncio
async def test_task_template_in_agent_prompt() -> None:
    runner = FakeRunner()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(
                        id="a1",
                        type="agent",
                        label="worker",
                        prompt="Task is: {{task}}",
                    ),
                ],
            )
        ],
    )
    await run_workflow(spec, runner=runner, task="hello world")
    assert runner.prompts == ["Task is: hello world"]


@pytest.mark.asyncio
async def test_loop_until_stops_early() -> None:
    from deepseek_tui.workflow.models import LoopStep, LoopUntil

    class LoopRunner(FakeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.n = 0

        async def run(self, **kwargs: object) -> StepOutput | None:
            self.n += 1
            label = str(kwargs.get("label"))
            self.calls.append(label)
            self.prompts.append(str(kwargs.get("prompt")))
            done = self.n >= 2
            return make_step_output(f"r{self.n}", {"done": done})

    runner = LoopRunner()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    LoopStep(
                        id="lp",
                        type="loop",
                        max_rounds=5,
                        until=LoopUntil(path="$.done", equals=True),
                        steps=[
                            AgentStep(
                                id="chk",
                                type="agent",
                                label="check",
                                prompt="round {{round}}",
                                output_schema={"type": "object"},
                            )
                        ],
                    )
                ],
            )
        ],
    )
    await run_workflow(spec, runner=runner)
    assert runner.n == 2
    assert any("round 1" in p for p in runner.prompts)
    assert any("round 2" in p for p in runner.prompts)


@pytest.mark.asyncio
async def test_resume_skips_completed_steps(tmp_path: Path) -> None:
    from deepseek_tui.workflow.store import checkpoint_run, create_run

    runner = FakeRunner()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(id="a1", type="agent", label="one", prompt="1"),
                    AgentStep(id="a2", type="agent", label="two", prompt="2"),
                ],
            )
        ],
    )
    record = create_run(spec, task="t", workspace=tmp_path)
    checkpoint_run(
        record,
        completed_step_ids=["a1"],
        outputs={"a1": make_step_output("done:one")},
        snapshot=WorkflowSnapshot(name="t", description="d"),
        logs=[],
        status="interrupted",
        workspace=tmp_path,
    )
    result = await run_workflow(
        spec,
        runner=runner,
        task="t",
        initial_outputs={"a1": make_step_output("done:one")},
        skip_step_ids={"a1"},
    )
    assert runner.calls == ["two"]
    assert "a1" in result.result
    assert "a2" in result.result


@pytest.mark.asyncio
async def test_timeout_seconds_threaded_to_runner() -> None:
    """A step's timeout_seconds reaches runner.run as a kwarg."""
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(
                        id="a1",
                        type="agent",
                        label="worker",
                        prompt="work",
                        timeout_seconds=42,
                    ),
                ],
            )
        ],
    )
    runner = FakeRunner({"worker": "done"})
    await run_workflow(spec, runner=runner)
    assert runner.timeout_seconds_seen == [42]


@pytest.mark.asyncio
async def test_timeout_seconds_default_none_threaded() -> None:
    """Steps without timeout_seconds pass None through (no behavior change)."""
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(
                        id="a1",
                        type="agent",
                        label="worker",
                        prompt="work",
                    ),
                ],
            )
        ],
    )
    runner = FakeRunner({"worker": "done"})
    await run_workflow(spec, runner=runner)
    assert runner.timeout_seconds_seen == [None]


@pytest.mark.asyncio
async def test_max_agents_not_double_counted_under_concurrent_fanout() -> None:
    """A fanout with concurrency == max_agents must let every item spawn.

    Regression test: reserved_agents used to stay incremented until
    runner.run() fully returned, while spawned_agent_ids already counted the
    same in-flight agent as soon as on_agent_id fired — double counting each
    live agent and tripping "max_agents reached" at roughly half the
    configured limit.
    """

    class SlotTrackingRunner(FakeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.in_flight = 0
            self.max_in_flight = 0

        async def run(
            self, *, label: str, on_agent_id: Any = None, **kwargs: object
        ) -> StepOutput | None:
            self.calls.append(label)
            if on_agent_id is not None:
                on_agent_id(label)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            await asyncio.sleep(0.02)
            self.in_flight -= 1
            return make_step_output(f"done:{label}")

    runner = SlotTrackingRunner()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(concurrency=4, max_agents=4),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    FanoutStep(
                        id="fan",
                        type="fanout",
                        items=["a", "b", "c", "d"],
                        agent=AgentStepConfig(
                            label_template="{{item}}",
                            prompt_template="work {{item}}",
                        ),
                    ),
                ],
            )
        ],
    )

    result = await run_workflow(spec, runner=runner)
    assert runner.max_in_flight == 4
    assert set(runner.calls) == {"a", "b", "c", "d"}
    assert isinstance(result.result, dict)


class _NeverCompletesManager:
    """Fake SubAgentManager whose get_result always reports RUNNING."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self._n = 0

    async def spawn(self, request: Any) -> Any:
        self._n += 1
        return SimpleNamespace(agent_id=f"a{self._n}")

    async def get_result(self, agent_id: str) -> Any:
        return SimpleNamespace(
            status=SubAgentStatus.running(),
            result=None,
            structured=None,
        )

    async def cancel(self, agent_id: str) -> None:
        self.cancelled.append(agent_id)


@pytest.mark.asyncio
async def test_runner_deadline_uses_step_timeout() -> None:
    """Per-step timeout_seconds overrides the default 1h deadline and cancels."""
    manager = _NeverCompletesManager()
    runner = DeepSeekAgentRunner(manager, base_runtime=None, workspace=None)  # type: ignore[arg-type]
    started = time.monotonic()
    out = await runner.run(
        prompt="x",
        label="slow",
        agent_type="general",
        model=None,
        allowed_tools=None,
        output_schema=None,
        policy=WorkflowPolicy(),
        cancel_event=None,
        on_agent_id=None,
        timeout_seconds=1,
    )
    elapsed = time.monotonic() - started
    assert out is None
    assert elapsed < 5  # deadline honored (~1s), not the 1h default
    assert manager.cancelled  # agent was cancelled on timeout
