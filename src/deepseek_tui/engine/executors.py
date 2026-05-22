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
from typing import TYPE_CHECKING, Any

from deepseek_tui.engine.events import (
    ErrorEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.messages import Message

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent.manager import SubAgent
    from deepseek_tui.tools.task_manager import ExecutionTask, TaskExecutionResult


async def real_task_executor(
    task: ExecutionTask, cancel: asyncio.Event
) -> TaskExecutionResult:
    """Drive a full Engine turn loop for a queued task."""
    from deepseek_tui.tools.task_manager import TaskExecutionResult

    engine, handle, engine_task = await _create_engine_for_execution(
        model=task.model,
        workspace=Path(task.workspace),
        allow_shell=task.allow_shell,
        auto_approve=task.auto_approve,
        trust_mode=task.trust_mode,
        task_id=task.id,
        task_manager=task.task_manager,
    )

    try:
        await handle.send_message(content=task.prompt)

        collected_text: list[str] = []
        error_msg: str | None = None

        async for event in handle.events():
            if cancel.is_set():
                await handle.cancel("task_cancelled")
                break

            if engine_task.done():
                exc = engine_task.exception()
                if exc:
                    error_msg = f"engine crashed: {exc}"
                break

            if isinstance(event, TextDeltaEvent):
                collected_text.append(event.text)
            elif isinstance(event, ErrorEvent):
                error_msg = event.message
                collected_text.append(f"\n[tool error] {event.message}\n")
            elif isinstance(event, UserInputRequiredEvent):
                future = handle.pending_user_inputs.get(event.tool_call_id)
                if future and not future.done():
                    future.set_result({"error": "Tasks cannot request user input"})
            elif isinstance(event, TurnCompleteEvent):
                break
            elif isinstance(event, TurnCancelledEvent):
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
        await _shutdown_engine(engine, engine_task)


async def real_subagent_executor(agent: SubAgent, cancel: asyncio.Event) -> str:
    """Drive a full Engine turn loop for a sub-agent."""
    from deepseek_tui.tools.subagent.manager import build_subagent_system_prompt
    from deepseek_tui.tools.subagent.mailbox import MailboxMessage

    parent_cancel = agent.parent_cancel
    engine, handle, engine_task = await _create_engine_for_execution(
        model=agent.model,
        workspace=agent.workspace,
        allow_shell=True,
        auto_approve=True,
        allowed_tools=agent.allowed_tools,
    )

    engine.tool_context.metadata["subagent_depth"] = agent.spawn_depth  # type: ignore[attr-defined]
    system_prompt = build_subagent_system_prompt(agent.agent_type, agent.assignment)
    mailbox = agent.mailbox

    if agent.fork_messages:
        engine.session_messages = _messages_from_fork(agent.fork_messages)  # type: ignore[attr-defined]

    try:
        await handle.send_message(content=agent.prompt, system_prompt=system_prompt)

        collected_text: list[str] = []

        async for event in handle.events():
            if _should_cancel(cancel, parent_cancel):
                await handle.cancel("subagent_cancelled")
                raise asyncio.CancelledError

            if engine_task.done():
                exc = engine_task.exception()
                if exc:
                    raise RuntimeError(f"engine crashed: {exc}") from exc
                break

            if isinstance(event, TextDeltaEvent):
                collected_text.append(event.text)
                agent.steps_taken += 1
            elif isinstance(event, ToolCallEvent):
                if mailbox is not None:
                    mailbox.send(
                        MailboxMessage.tool_call_started(
                            agent.id, event.tool_call.name, agent.steps_taken
                        )
                    )
            elif isinstance(event, ToolResultEvent):
                if mailbox is not None:
                    mailbox.send(
                        MailboxMessage.tool_call_completed(
                            agent.id,
                            event.tool_name,
                            agent.steps_taken,
                            event.success,
                        )
                    )
            elif isinstance(event, ErrorEvent):
                collected_text.append(f"\n[tool error] {event.message}\n")
            elif isinstance(event, UserInputRequiredEvent):
                future = handle.pending_user_inputs.get(event.tool_call_id)
                if future and not future.done():
                    future.set_result({"error": "Sub-agents cannot request user input"})
            elif isinstance(event, TurnCompleteEvent):
                if mailbox is not None and event.usage is not None:
                    mailbox.send(
                        MailboxMessage.token_usage(
                            agent.id,
                            agent.model,
                            {
                                "input_tokens": event.usage.input_tokens,
                                "output_tokens": event.usage.output_tokens,
                                "cache_read_input_tokens": (
                                    event.usage.cache_read_input_tokens
                                ),
                                "cache_creation_input_tokens": (
                                    event.usage.cache_creation_input_tokens
                                ),
                            },
                        )
                    )
                break
            elif isinstance(event, TurnCancelledEvent):
                break

            try:
                text, interrupt = agent.input_queue.get_nowait()
                if interrupt:
                    await handle.cancel("steer")
                    handle.reset_cancel()
                await handle.send_message(content=text, system_prompt=system_prompt)
            except asyncio.QueueEmpty:
                pass

        return "".join(collected_text)

    finally:
        await _shutdown_engine(engine, engine_task)


def _should_cancel(cancel: asyncio.Event, parent_cancel: asyncio.Event | None) -> bool:
    if cancel.is_set():
        return True
    return parent_cancel is not None and parent_cancel.is_set()


def _messages_from_fork(raw_messages: list[dict[str, Any]]) -> list[Message]:
    out: list[Message] = []
    for item in raw_messages:
        try:
            out.append(Message.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    return out


async def _shutdown_engine(engine: object, engine_task: asyncio.Task[None]) -> None:
    """Gracefully shutdown an executor-spawned engine and its resources."""
    try:
        if hasattr(engine, "shutdown"):
            await engine.shutdown()
    except Exception:  # noqa: BLE001
        pass
    engine_task.cancel()
    try:
        await engine_task
    except (asyncio.CancelledError, Exception):
        pass


async def _create_engine_for_execution(
    model: str,
    workspace: Path,
    allow_shell: bool = True,
    auto_approve: bool = True,
    allowed_tools: list[str] | None = None,
    config: object | None = None,
    task_id: str | None = None,
    task_manager: object | None = None,
    trust_mode: bool = False,
) -> tuple[object, EngineHandle, asyncio.Task[None]]:
    from deepseek_tui.client.deepseek import DeepSeekClient
    from deepseek_tui.config.loader import ConfigLoader
    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import AutoApprovalHandler
    from deepseek_tui.engine.engine import Engine

    if config is None:
        try:
            config = ConfigLoader().load()
        except Exception:  # noqa: BLE001
            config = Config()
    handle = EngineHandle()

    client = DeepSeekClient.from_config(config)

    approval_handler = AutoApprovalHandler() if auto_approve else None

    engine = await Engine.create(
        handle=handle,
        client=client,
        config=config,
        working_directory=workspace.resolve(),  # noqa: ASYNC240
        default_model=model,
        max_tool_round_trips=10,
        approval_handler=approval_handler,
    )

    engine.tool_context.trust_mode = trust_mode

    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        engine.tool_registry.filter_by_names(allowed_set)

    if task_id is not None:
        engine.tool_context.metadata["task_id"] = task_id
        engine.tool_context.active_task_id = task_id
    if task_manager is not None:
        engine.tool_context.metadata["task_manager"] = task_manager

    engine_task = asyncio.create_task(engine.run())
    return engine, handle, engine_task
