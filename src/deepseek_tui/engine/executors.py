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
    TurnCancelledEvent,
    TurnCompleteEvent,
    UserInputRequiredEvent,
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

    Threads ``task.id`` + ``task.task_manager`` into the spawned
    Engine's ``ToolContext.metadata`` so checklist tools can route their
    snapshots back to :meth:`TaskManager.record_tool_metadata` — the
    Python analog of Rust's ``TaskExecutionEvent::ToolCompleted`` event
    channel (``task_manager.rs:1183-1238``).
    """
    from deepseek_tui.tools.task_manager import TaskExecutionResult

    engine, handle, engine_task = await _create_engine_for_execution(
        model=task.model,
        workspace=Path(task.workspace),
        allow_shell=task.allow_shell,
        auto_approve=task.auto_approve,
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
    """Drive a full Engine turn loop for a sub-agent.

    Mirrors Rust ``SubAgentExecutor::run`` (mod.rs:773).
    Creates a fresh Engine scoped to the agent's prompt and allowed tools,
    collects text output, and respects the cancel token.
    """
    engine, handle, engine_task = await _create_engine_for_execution(
        model=agent.model,
        workspace=agent.workspace,
        allow_shell=True,
        auto_approve=True,
        allowed_tools=agent.allowed_tools,
    )

    # Stamp this agent's depth on the child Engine's tool context so any
    # ``agent_spawn`` tool calls from inside the agent inherit it as
    # ``parent_depth`` and ``SubAgentManager.spawn`` can refuse spawns
    # past ``DEFAULT_MAX_SPAWN_DEPTH``.
    engine.tool_context.metadata["subagent_depth"] = agent.spawn_depth  # type: ignore[attr-defined]

    try:
        await handle.send_message(content=agent.prompt)

        collected_text: list[str] = []

        async for event in handle.events():
            if cancel.is_set():
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
            elif isinstance(event, ErrorEvent):
                collected_text.append(f"\n[tool error] {event.message}\n")
            elif isinstance(event, UserInputRequiredEvent):
                future = handle.pending_user_inputs.get(event.tool_call_id)
                if future and not future.done():
                    future.set_result({"error": "Sub-agents cannot request user input"})
            elif isinstance(event, TurnCompleteEvent):
                break
            elif isinstance(event, TurnCancelledEvent):
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
        await _shutdown_engine(engine, engine_task)


# --- internal helpers -------------------------------------------------------


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
    trust_mode: bool = False,  # Subagents use sandboxed paths by default
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

    *task_id* / *task_manager* are stashed on the new Engine's
    ``ToolContext.metadata`` so tools running inside a durable task can
    forward their ``task_updates`` payloads to the owning
    :class:`~deepseek_tui.tools.task_manager.TaskManager`.

    *trust_mode* controls whether paths outside workspace are allowed.
    Subagents default to False (sandboxed to workspace), while tasks
    default to their configured value.
    """
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

    # Use AutoApprovalHandler for subagents/tasks when auto_approve=True
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

    # Override trust_mode for subagents (mirrors Rust context inheritance)
    engine.tool_context.trust_mode = trust_mode

    # Filter registry down to allowed_tools (Rust: SubAgent scope restriction)
    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        engine.tool_registry.filter_by_names(allowed_set)

    # Side-channel for Task ↔ checklist persistence. See
    # ``tools/todo_tools.py::_forward_to_task_manager``.
    if task_id is not None:
        engine.tool_context.metadata["task_id"] = task_id
    if task_manager is not None:
        engine.tool_context.metadata["task_manager"] = task_manager

    engine_task = asyncio.create_task(engine.run())
    return engine, handle, engine_task
