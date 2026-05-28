"""Real executors for Task and SubAgent — replace the sleep-50ms stubs.

Sub-agents run ``run_subagent_loop`` (shared SubAgentManager, no nested Engine).
Tasks run a single Engine turn with the **shared** process TaskManager injected.

Mirrors Rust ``run_subagent`` + ``EngineTaskExecutor``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.engine.events import (
    ErrorEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.tools.task_manager import CRON_PROMPT_MARKER

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent.manager import SubAgent
    from deepseek_tui.tools.task_manager import ExecutionTask, TaskExecutionResult

logger = logging.getLogger(__name__)

# Background automations need headroom for web_search etc., but not unbounded loops.
TASK_MAX_TOOL_ROUND_TRIPS = 30
CRON_MAX_TOOL_ROUND_TRIPS = 12
CRON_TASK_WALL_CLOCK_SECONDS = 300


def _is_cron_task(prompt: str) -> bool:
    return prompt.lstrip().startswith(CRON_PROMPT_MARKER)


async def _collect_turn_events(
    handle: EngineHandle,
    cancel: asyncio.Event,
) -> tuple[str, str | None]:
    """Drain events until turn end. Returns (final_assistant_text, error_message)."""
    from deepseek_tui.automation.delivery_format import assistant_message_text

    final_text = ""
    error_msg: str | None = None

    async for event in handle.events():
        if cancel.is_set():
            await handle.cancel("executor_cancelled")
            break

        if isinstance(event, ErrorEvent):
            error_msg = event.message
        elif isinstance(event, UserInputRequiredEvent):
            future = handle.pending_user_inputs.get(event.tool_call_id)
            if future and not future.done():
                future.set_result(
                    {"error": "Background executors cannot request user input"}
                )
        elif isinstance(event, TurnCompleteEvent):
            final_text = assistant_message_text(event.assistant_message)
            break
        elif isinstance(event, TurnCancelledEvent):
            break

    return final_text, error_msg


async def _run_task_engine_turn(
    task: ExecutionTask, cancel: asyncio.Event
) -> "TaskExecutionResult":
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
        mcp=True,
        automations=False,
    )
    cfg.hooks = HooksConfig(enabled=False, hooks=[])
    handle = EngineHandle()
    client = DeepSeekClient.from_config(cfg)
    workspace = Path(task.workspace).resolve()  # noqa: ASYNC240

    shared_mcp = getattr(task.task_manager, "_shared_mcp_manager", None)
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=workspace,
        shared_task_manager=task.task_manager,
        mcp_manager=shared_mcp,
        start_mcp=False,
    )

    approval_handler = AutoApprovalHandler() if task.auto_approve else None
    max_rounds = (
        CRON_MAX_TOOL_ROUND_TRIPS
        if _is_cron_task(task.prompt)
        else TASK_MAX_TOOL_ROUND_TRIPS
    )

    engine = await Engine.create(
        handle=handle,
        client=client,
        config=cfg,
        working_directory=workspace,
        default_model=task.model,
        max_tool_round_trips=max_rounds,
        approval_handler=approval_handler,
        tool_runtime=runtime,
    )
    engine.tool_context.trust_mode = task.trust_mode
    engine.tool_context.active_task_id = task.id
    engine.tool_context.metadata["task_id"] = task.id

    try:
        await engine.run_single_turn(task.prompt, model=task.model)
        result_text, error_msg = await _collect_turn_events(handle, cancel)
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


async def real_task_executor(
    task: ExecutionTask, cancel: asyncio.Event
) -> "TaskExecutionResult":
    """Run one Engine turn for a queued task (shared TaskManager)."""
    from deepseek_tui.tools.task_manager import TaskExecutionResult

    if _is_cron_task(task.prompt):
        try:
            return await asyncio.wait_for(
                _run_task_engine_turn(task, cancel),
                timeout=CRON_TASK_WALL_CLOCK_SECONDS,
            )
        except asyncio.TimeoutError:
            cancel.set()
            logger.warning(
                "[task_executor] cron wall-clock timeout task_id=%s after=%ds",
                task.id,
                CRON_TASK_WALL_CLOCK_SECONDS,
            )
            return TaskExecutionResult(
                summary="",
                error=f"Task timed out after {CRON_TASK_WALL_CLOCK_SECONDS}s",
            )
    return await _run_task_engine_turn(task, cancel)


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
