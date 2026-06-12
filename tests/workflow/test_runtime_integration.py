"""WorkflowTool integration with mock SubAgentManager."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.subagent import (
    SubAgentManager,
    SubAgentRuntime,
)
from deepseek_tui.tools.subagent import AgentRunOutput
from deepseek_tui.tools.workflow import WorkflowTool
from deepseek_tui.workflow.runtime import DeepSeekAgentRunner
from deepseek_tui.workflow.models import StepOutput, WorkflowAbortedError, WorkflowPolicy
from deepseek_tui.workflow.models import make_step_output


async def _workflow_stub_executor(agent, cancel: asyncio.Event) -> AgentRunOutput:
    del cancel
    return AgentRunOutput(text=f"ok:{agent.nickname}", structured=None)


@pytest.mark.asyncio
async def test_workflow_tool_runs_two_agent_steps(tmp_path: Path) -> None:
    manager = SubAgentManager(workspace=tmp_path, executor=_workflow_stub_executor)
    client = MagicMock()
    runtime = SubAgentRuntime(
        manager=manager,
        client=client,
        model="deepseek-chat",
        config=MagicMock(),
        workspace=tmp_path,
        allow_shell=False,
        auto_approve=True,
    )
    manager.attach_loop_runtime(runtime)

    spec = {
        "version": 1,
        "meta": {"name": "two_step", "description": "test"},
        "phases": [
            {
                "id": "p1",
                "title": "P",
                "steps": [
                    {
                        "id": "a1",
                        "type": "agent",
                        "label": "first",
                        "prompt": "one",
                    },
                    {
                        "id": "a2",
                        "type": "agent",
                        "label": "second",
                        "prompt": "two",
                    },
                ],
            }
        ],
    }

    tool = WorkflowTool()
    ctx = ToolContext(working_directory=tmp_path, subagent_manager=manager)
    ctx.metadata["engine_cancel_event"] = asyncio.Event()
    ctx.metadata["workflow_tool_call_id"] = "tc_workflow_1"

    result = await tool.execute({"spec": spec}, ctx)
    assert result.success is True
    assert "workflow" in result.metadata
    wf = result.metadata["workflow"]
    assert wf["name"] == "two_step"
    assert wf["result"] is not None


@pytest.mark.asyncio
async def test_agent_runner_cancel_interrupts_spawned_subagent_task(
    tmp_path: Path,
) -> None:
    cancelled = asyncio.Event()

    async def _slow_executor(agent, cancel: asyncio.Event) -> AgentRunOutput:
        del agent, cancel
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()
        return AgentRunOutput(text="late", structured=None)

    manager = SubAgentManager(workspace=tmp_path, executor=_slow_executor)
    runtime = SubAgentRuntime(
        manager=manager,
        client=MagicMock(),
        model="deepseek-chat",
        config=MagicMock(),
        workspace=tmp_path,
        allow_shell=False,
        auto_approve=True,
    )
    manager.attach_loop_runtime(runtime)
    runner = DeepSeekAgentRunner(manager, runtime)
    cancel_event = asyncio.Event()

    task = asyncio.create_task(
        runner.run(
            prompt="slow",
            label="slow",
            agent_type="general",
            model=None,
            allowed_tools=None,
            output_schema=None,
            policy=WorkflowPolicy(),
            cancel_event=cancel_event,
            on_agent_id=None,
        )
    )
    for _ in range(20):
        if manager.running_count() == 1:
            break
        await asyncio.sleep(0.01)

    cancel_event.set()
    with pytest.raises(WorkflowAbortedError):
        await asyncio.wait_for(task, timeout=1)

    await asyncio.wait_for(cancelled.wait(), timeout=1)
    assert manager.running_count() == 0


class _FakeRunner:
    async def run(self, **kwargs: object) -> StepOutput | None:
        label = kwargs.get("label", "agent")
        return make_step_output(f"out:{label}")


@pytest.mark.asyncio
async def test_fanout_preserves_item_order_in_preview() -> None:
    from deepseek_tui.workflow.models import (
        AgentStepConfig,
        FanoutStep,
        WorkflowMeta,
        WorkflowPhase,
        WorkflowPolicy,
        WorkflowSpec,
    )
    from deepseek_tui.workflow.runtime import run_workflow

    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="f", description="d"),
        policy=WorkflowPolicy(concurrency=4),
        phases=[
            WorkflowPhase(
                id="p",
                title="P",
                steps=[
                    FanoutStep(
                        id="fan",
                        type="fanout",
                        items=["alpha", "beta", "gamma"],
                        agent=AgentStepConfig(
                            label_template="x {{item}}",
                            prompt_template="go {{item}}",
                        ),
                    )
                ],
            )
        ],
    )
    result = await run_workflow(spec, runner=_FakeRunner())
    blob = (
        json.dumps(result.result, default=str)
        if not isinstance(result.result, str)
        else result.result
    )
    assert blob.index("alpha") < blob.index("beta") < blob.index("gamma")
