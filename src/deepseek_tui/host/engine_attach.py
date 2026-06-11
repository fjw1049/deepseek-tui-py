"""Host-owned wiring for engine-scoped capability runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.config.models import Config
from deepseek_tui.host.assembler import AssembledContributions, merge_lifecycle_registries

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.tools.runtime import ToolRuntime


@dataclass(frozen=True, slots=True)
class EngineAttachRequest:
    engine: object
    config: Config
    client: LLMClient
    workspace: Path
    mode: str
    default_model: str
    handle: EngineHandle
    tool_runtime: ToolRuntime
    assembled: AssembledContributions


async def attach_engine_capabilities(request: EngineAttachRequest) -> None:
    """Attach engine-scoped capability runtimes after the Engine shell exists."""
    from deepseek_tui.capabilities.cycle import attach_engine_cycle
    from deepseek_tui.capabilities.evolution import attach_engine_evolution
    from deepseek_tui.capabilities.goal import attach_engine_goal, rebind_goal_thread_if_local
    from deepseek_tui.capabilities.hooks import attach_engine_hooks
    from deepseek_tui.capabilities.memory import attach_engine_memory
    from deepseek_tui.capabilities.post_turn import attach_engine_post_turn
    from deepseek_tui.capabilities.subagents import attach_engine_subagents
    from deepseek_tui.execpolicy.sandbox import sync_execution_sandbox_policy
    from deepseek_tui.host.engine_lifecycle import register_engine_lifecycle_observers
    from deepseek_tui.tools.builder import wire_registry_client

    engine = request.engine
    attach_engine_goal(engine)
    attach_engine_hooks(engine)
    await attach_engine_memory(engine, request.config, request.client)
    cycle_runtime = attach_engine_cycle(
        engine,
        request.config,
        client=request.client,
    )
    rebind_goal_thread_if_local(
        engine.goal_controller,  # type: ignore[attr-defined]
        metadata=engine.tool_context.metadata,  # type: ignore[attr-defined]
        thread_id=cycle_runtime.session_id,
    )
    engine.mode = request.mode  # type: ignore[attr-defined]
    sync_execution_sandbox_policy(
        engine.tool_context,  # type: ignore[attr-defined]
        request.mode,
        engine.tool_context.working_directory,  # type: ignore[attr-defined]
    )
    wire_registry_client(
        engine.tool_registry,  # type: ignore[attr-defined]
        request.client,
        root_model=engine.default_model,  # type: ignore[attr-defined]
    )
    await attach_engine_subagents(
        engine,
        config=request.config,
        client=request.client,
        workspace=request.workspace,
        default_model=request.default_model,
        cancel_token=request.handle.cancel_event,
        tool_runtime=request.tool_runtime,
    )
    evolution_runtime = attach_engine_evolution(
        engine,
        request.config,
        request.client,
        workspace=request.workspace,
        emit_event=engine.handle.emit,  # type: ignore[attr-defined]
    )
    await attach_engine_post_turn(
        engine,
        request.config,
        evolution_pipeline=evolution_runtime.pipeline,
    )
    merge_lifecycle_registries(
        engine.lifecycle_registry,  # type: ignore[attr-defined]
        request.assembled.lifecycle,
    )
    register_engine_lifecycle_observers(engine)
