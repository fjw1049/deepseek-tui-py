"""Host-owned wiring for engine-scoped capability runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.config.models import Config
from deepseek_tui.host.assembler import (
    AssembledContributions,
    collect_builtin_contributions,
    merge_lifecycle_registries,
)
from deepseek_tui.host.engine_shell import EngineShell

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.engine.engine import Engine
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.tools.runtime import ToolRuntime


@dataclass(frozen=True, slots=True)
class EngineAttachRequest:
    shell: EngineShell
    config: Config
    client: LLMClient
    workspace: Path
    mode: str
    default_model: str
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
    from deepseek_tui.tools.builder import wire_registry_client

    shell = request.shell
    attach_engine_goal(shell)
    attach_engine_hooks(shell)
    await attach_engine_memory(shell, request.config, request.client)
    cycle_runtime = attach_engine_cycle(
        shell,
        request.config,
        client=request.client,
    )
    rebind_goal_thread_if_local(
        shell.goal_controller,
        metadata=shell.tool_context.metadata,
        thread_id=cycle_runtime.session_id,
    )
    shell.mode = request.mode
    sync_execution_sandbox_policy(
        shell.tool_context,
        request.mode,
        shell.tool_context.working_directory,
    )
    wire_registry_client(
        shell.tool_registry,
        request.client,
        root_model=shell.default_model,
    )
    await attach_engine_subagents(
        shell,
        config=request.config,
        client=request.client,
        workspace=request.workspace,
        default_model=request.default_model,
        tool_runtime=request.tool_runtime,
    )
    evolution_runtime = attach_engine_evolution(
        shell,
        request.config,
        request.client,
        workspace=request.workspace,
        emit_event=shell.handle.emit,
    )
    await attach_engine_post_turn(
        shell,
        request.config,
        evolution_pipeline=evolution_runtime.pipeline,
    )
    merge_lifecycle_registries(
        shell.lifecycle_registry,
        request.assembled.lifecycle,
    )


async def attach_engine_shell(
    engine: Engine,
    *,
    config: Config,
    client: LLMClient,
    workspace: Path,
    mode: str,
    default_model: str,
    handle: EngineHandle,
    tool_runtime: ToolRuntime,
    contributions: AssembledContributions | None = None,
) -> None:
    """Attach capability runtimes to an already-constructed Engine shell."""
    from deepseek_tui.engine.capacity import CapacityController, CapacityControllerConfig
    from deepseek_tui.skills import discover_in_workspace

    shell = EngineShell.wrap(engine)
    assembled = contributions or collect_builtin_contributions(config)
    shell.skill_registry = discover_in_workspace(workspace=workspace)
    shell.capacity_controller = CapacityController(
        config=CapacityControllerConfig.from_app_config(config.capacity)
    )
    await attach_engine_capabilities(
        EngineAttachRequest(
            shell=shell,
            config=config,
            client=client,
            workspace=workspace,
            mode=mode,
            default_model=default_model,
            tool_runtime=tool_runtime,
            assembled=assembled,
        )
    )
    shell.apply_to(engine)
    from deepseek_tui.host.engine_lifecycle import register_engine_lifecycle_observers

    engine._assembled_contributions = assembled
    register_engine_lifecycle_observers(engine)
