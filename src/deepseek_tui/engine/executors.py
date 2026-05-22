"""Real executors for Task and SubAgent — replace the sleep-50ms stubs.

Sub-agents run ``run_subagent_loop`` (shared SubAgentManager, no nested Engine).
Tasks run a single Engine turn with the **shared** process TaskManager injected.

Mirrors Rust ``run_subagent`` + ``EngineTaskExecutor``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.engine.events import (
    ErrorEvent,
    TextDeltaEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.engine.handle import EngineHandle

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent.manager import SubAgent
    from deepseek_tui.tools.task_manager import ExecutionTask, TaskExecutionResult


async def _collect_turn_events(
    handle: EngineHandle,
    cancel: asyncio.Event,
) -> tuple[list[str], str | None]:
    """Drain events until turn end. Returns (text_chunks, error_message)."""
    collected_text: list[str] = []
    error_msg: str | None = None

    async for event in handle.events():
        if cancel.is_set():
            await handle.cancel("executor_cancelled")
            break

        if isinstance(event, TextDeltaEvent):
            collected_text.append(event.text)
        elif isinstance(event, ErrorEvent):
            error_msg = event.message
            collected_text.append(f"\n[tool error] {event.message}\n")
        elif isinstance(event, UserInputRequiredEvent):
            future = handle.pending_user_inputs.get(event.tool_call_id)
            if future and not future.done():
                future.set_result(
                    {"error": "Background executors cannot request user input"}
                )
        elif isinstance(event, (TurnCompleteEvent, TurnCancelledEvent)):
            break

    return collected_text, error_msg


async def real_task_executor(
    task: ExecutionTask, cancel: asyncio.Event
) -> TaskExecutionResult:
    """Run one Engine turn for a queued task (shared TaskManager)."""
    from deepseek_tui.client.deepseek import DeepSeekClient
    from deepseek_tui.config.loader import ConfigLoader
    from deepseek_tui.config.models import FeatureConfig, HooksConfig
    from deepseek_tui.engine.engine import Engine
    from deepseek_tui.engine.handle import AutoApprovalHandler
    from deepseek_tui.tools.runtime import create_tool_runtime
    from deepseek_tui.tools.task_manager import TaskExecutionResult

    cfg = ConfigLoader().load()
    cfg = cfg.model_copy(deep=True)
    cfg.features = FeatureConfig(
        tasks=True,
        subagents=True,
        mcp=False,
        automations=False,
    )
    cfg.hooks = HooksConfig(enabled=False, hooks=[])
    handle = EngineHandle()
    client = DeepSeekClient.from_config(cfg)
    workspace = Path(task.workspace).resolve()  # noqa: ASYNC240

    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=workspace,
        shared_task_manager=task.task_manager,
        start_mcp=False,
    )

    approval_handler = AutoApprovalHandler() if task.auto_approve else None

    engine = await Engine.create(
        handle=handle,
        client=client,
        config=cfg,
        working_directory=workspace,
        default_model=task.model,
        max_tool_round_trips=10,
        approval_handler=approval_handler,
        tool_runtime=runtime,
    )
    engine.tool_context.trust_mode = task.trust_mode
    engine.tool_context.active_task_id = task.id
    engine.tool_context.metadata["task_id"] = task.id

    try:
        await engine.run_single_turn(task.prompt, model=task.model)
        collected_text, error_msg = await _collect_turn_events(handle, cancel)
        result_text = "".join(collected_text)
        if error_msg:
            return TaskExecutionResult(
                summary=result_text or "Task failed",
                detail=None,
                error=error_msg,
            )
        if cancel.is_set():
            return TaskExecutionResult(summary=result_text, error="canceled")
        return TaskExecutionResult(summary=result_text, detail=None, error=None)
    finally:
        await engine.shutdown_session()
        handle.drain_events()


async def real_subagent_executor(agent: SubAgent, cancel: asyncio.Event) -> str:
    """Drive ``run_subagent_loop`` — no nested Engine / managers."""
    from deepseek_tui.tools.subagent.manager import run_subagent_loop

    runtime = agent.loop_runtime
    if runtime is None:
        raise RuntimeError(
            "Sub-agent loop runtime is missing; Engine.create must call "
            "SubAgentManager.attach_loop_runtime"
        )
    return await run_subagent_loop(agent, runtime, cancel)
