"""Workflow runtime tests with a fake runner."""

from __future__ import annotations

import asyncio

import pytest

from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    FanoutStep,
    PipelineStage,
    PipelineStep,
    StepOutput,
    SynthesisStep,
    WorkflowMeta,
    WorkflowPhase,
    WorkflowPolicy,
    WorkflowSpec,
)
from deepseek_tui.workflow.runtime import WorkflowFailedError, run_workflow
from deepseek_tui.workflow.models import make_step_output


class FakeRunner:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.calls: list[str] = []
        self._responses = responses or {}

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
    ) -> StepOutput | None:
        self.calls.append(label)
        if cancel_event is not None and cancel_event.is_set():
            return None
        text = self._responses.get(label, f"done:{label}")
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
