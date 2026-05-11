"""Real executors for Task and SubAgent — replace the sleep-50ms stubs.

Each executor creates a minimal Engine instance, drives the turn loop with
the task/subagent prompt, and collects the result. Cancellation is honoured
via the passed ``cancel`` event.

Mirrors Rust ``TaskExecutor`` (task_manager.rs:1380-1472) and
``SubAgentExecutor`` (mod.rs:773-893).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.engine.events import (
    ErrorEvent,
    TextDeltaEvent,
    TurnCompleteEvent,
)
from deepseek_tui.engine.handle import EngineHandle

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent.manager import SubAgent
    from deepseek_tui.tools.task_manager import ExecutionTask, TaskExecutionResult


async def real_task_executor(
    task: ExecutionTask, cancel: asyncio.Event
) -> TaskExecutionResult:
    """Drive a full Engine turn loop for a queued task.

    Mirrors Rust ``TaskExecutor::run`` (task_manager.rs:1380).
    Creates a fresh Engine, sends the task prompt, collects streamed text
    until TurnComplete or cancellation.
    """
    from deepseek_tui.tools.task_manager import TaskExecutionResult

    engine, handle, engine_task = await _create_engine_for_execution(
        model=task.model,
        workspace=Path(task.workspace),
        allow_shell=task.allow_shell,
        auto_approve=task.auto_approve,
    )

    try:
        await handle.send_message(content=task.prompt)

        collected_text: list[str] = []
        error_msg: str | None = None

        async for event in handle.events():
            if cancel.is_set():
                await handle.cancel("task_cancelled")
                break

            if isinstance(event, TextDeltaEvent):
                collected_text.append(event.text)
            elif isinstance(event, ErrorEvent):
                error_msg = event.message
                break
            elif isinstance(event, TurnCompleteEvent):
                break

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
        engine_task.cancel()
        try:
            await engine_task
        except (asyncio.CancelledError, Exception):
            pass


async def real_subagent_executor(agent: SubAgent, cancel: asyncio.Event) -> str:
    """Drive a full Engine turn loop for a sub-agent.

    Mirrors Rust ``SubAgentExecutor::run`` (mod.rs:773).
    Creates a fresh Engine scoped to the agent's prompt and allowed tools,
    collects text output, and respects the cancel token.
    """
    engine, handle, engine_task = await _create_engine_for_execution(
        model=agent.model,
        workspace=Path("."),
        allow_shell=True,
        auto_approve=True,
        allowed_tools=agent.allowed_tools,
    )

    try:
        await handle.send_message(content=agent.prompt)

        collected_text: list[str] = []

        async for event in handle.events():
            if cancel.is_set():
                await handle.cancel("subagent_cancelled")
                raise asyncio.CancelledError

            if isinstance(event, TextDeltaEvent):
                collected_text.append(event.text)
                agent.steps_taken += 1
            elif isinstance(event, ErrorEvent):
                raise RuntimeError(event.message)
            elif isinstance(event, TurnCompleteEvent):
                break

            # Handle follow-up input from parent (assign / send_input)
            try:
                text, interrupt = agent.input_queue.get_nowait()
                if interrupt:
                    await handle.cancel("steer")
                    handle.reset_cancel()
                await handle.send_message(content=text)
            except asyncio.QueueEmpty:
                pass

        return "".join(collected_text)

    finally:
        engine_task.cancel()
        try:
            await engine_task
        except (asyncio.CancelledError, Exception):
            pass


# --- internal helpers -------------------------------------------------------


async def _create_engine_for_execution(
    model: str,
    workspace: Path,
    allow_shell: bool = True,
    auto_approve: bool = True,
    allowed_tools: list[str] | None = None,
    config: object | None = None,
) -> tuple[object, EngineHandle, asyncio.Task[None]]:
    """Create a lightweight Engine + handle for executor use.

    Returns (engine, handle, background_task). Caller must cancel the task
    when done.

    When *allowed_tools* is provided (SubAgent use-case), only tools whose
    names appear in the list are kept in the registry — mirrors Rust
    ``SubAgent::allowed_tools`` filtering (mod.rs:810-825).

    *config* may be passed from the parent Engine so provider/model/api_key
    settings are inherited. When omitted, the user's config file is loaded
    from the default path instead of using an empty default.
    """
    from deepseek_tui.client.deepseek import DeepSeekClient
    from deepseek_tui.config.loader import ConfigLoader
    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.engine import Engine

    if config is None:
        try:
            config = ConfigLoader().load()
        except Exception:  # noqa: BLE001
            config = Config()
    handle = EngineHandle()

    client = DeepSeekClient.from_config(config)

    engine = await Engine.create(
        handle=handle,
        client=client,
        config=config,
        working_directory=workspace.resolve(),  # noqa: ASYNC240
        default_model=model,
        max_tool_round_trips=10,
    )

    # Filter registry down to allowed_tools (Rust: SubAgent scope restriction)
    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        engine.tool_registry.filter_by_names(allowed_set)

    engine_task = asyncio.create_task(engine.run())
    return engine, handle, engine_task
