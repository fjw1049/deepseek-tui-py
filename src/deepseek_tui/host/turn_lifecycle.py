"""Host-owned turn lifecycle dispatch for materialized engines.

Engine keeps turn execution order; capability modules register observers on
``Engine.lifecycle_registry``. This module builds lifecycle contexts and
dispatches to the registry so ``engine.py`` does not embed feature logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepseek_tui.host.lifecycle import (
    PREPARED_USER_TURN_DECORATION,
    TURN_LIFECYCLE_RESULT_DECORATION,
    AfterToolContext,
    BeforeUserTurnContext,
    PreparedUserTurn,
    TurnCompletionContext,
    TurnFailureContext,
    TurnLifecycleResult,
    TurnStartedContext,
)

if TYPE_CHECKING:
    from deepseek_tui.engine.engine import Engine
    from deepseek_tui.protocol.responses import ToolCall
    from deepseek_tui.tools.base import ToolResult


def memory_thread_id_for(engine: Engine) -> str:
    if engine.memory_thread_id:
        return engine.memory_thread_id
    runtime_thread_id = engine.tool_context.metadata.get("runtime_thread_id")
    if isinstance(runtime_thread_id, str) and runtime_thread_id:
        return runtime_thread_id
    if engine._cycle_session_id:
        return engine._cycle_session_id
    return "default"


async def dispatch_before_user_turn(
    engine: Engine,
    *,
    turn_id: str,
    user_text: str,
) -> PreparedUserTurn:
    from deepseek_tui.protocol.messages import Message

    thread_id = memory_thread_id_for(engine)
    context = BeforeUserTurnContext(
        thread_id=thread_id,
        turn_id=turn_id,
        user_text=user_text,
        workspace=engine.tool_context.working_directory,
        metadata=engine.tool_context.metadata,
        services=engine.tool_context.services,
    )
    await engine.lifecycle_registry.before_user_turn(context)
    prepared = context.decorations.get(PREPARED_USER_TURN_DECORATION)
    if isinstance(prepared, PreparedUserTurn):
        return prepared
    return PreparedUserTurn(
        thread_id=thread_id,
        recall=None,
        user_message=Message.user(user_text),
    )


async def dispatch_turn_started(engine: Engine, *, turn_id: str) -> None:
    await engine.lifecycle_registry.on_turn_started(
        TurnStartedContext(
            thread_id=memory_thread_id_for(engine),
            turn_id=turn_id,
            metadata=engine.tool_context.metadata,
            services=engine.tool_context.services,
        )
    )


async def dispatch_turn_completed(
    engine: Engine,
    *,
    turn_id: str,
    usage: object | None,
) -> TurnLifecycleResult:
    context = TurnCompletionContext(
        thread_id=memory_thread_id_for(engine),
        turn_id=turn_id,
        success=True,
        usage=usage,
        metadata=engine.tool_context.metadata,
        services=engine.tool_context.services,
    )
    await engine.lifecycle_registry.on_turn_completed(context)
    result = context.decorations.get(TURN_LIFECYCLE_RESULT_DECORATION)
    if isinstance(result, TurnLifecycleResult):
        return result
    return TurnLifecycleResult()


async def dispatch_turn_failed(
    engine: Engine,
    *,
    turn_id: str,
    reason: str,
    usage: object | None = None,
) -> TurnLifecycleResult:
    context = TurnFailureContext(
        thread_id=memory_thread_id_for(engine),
        turn_id=turn_id,
        reason=reason,
        usage=usage,
        metadata=engine.tool_context.metadata,
        services=engine.tool_context.services,
    )
    await engine.lifecycle_registry.on_turn_failed(context)
    result = context.decorations.get(TURN_LIFECYCLE_RESULT_DECORATION)
    if isinstance(result, TurnLifecycleResult):
        return result
    return TurnLifecycleResult()


async def dispatch_after_tool(
    engine: Engine,
    tool_call: ToolCall,
    result: ToolResult,
) -> None:
    arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
    await engine.lifecycle_registry.after_tool(
        AfterToolContext(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            arguments=arguments,
            success=result.success,
            result=result,
            metadata=engine.tool_context.metadata,
            services=engine.tool_context.services,
        )
    )
