"""Compatibility assembler for capability-module migration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from deepseek_tui.config.models import Config
from deepseek_tui.host.catalog import BuiltinModuleCatalog, default_builtin_catalog
from deepseek_tui.host.contributions import Contributions, PostTurnPipelineContribution
from deepseek_tui.host.lifecycle import LifecycleRegistry
from deepseek_tui.host.prompts import PromptContributor
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.host.surfaces import RuntimeSurfaceRegistry

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.engine.engine import ApprovalHandler, Engine
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.execpolicy.engine import ExecPolicyEngine
    from deepseek_tui.execpolicy.policy import Policy
    from deepseek_tui.host.module import CapabilityModule
    from deepseek_tui.host.toolpacks import ToolPack
    from deepseek_tui.mcp.manager import McpManager
    from deepseek_tui.tools.registry import ToolRegistry
    from deepseek_tui.tools.runtime import ToolRuntime
    from deepseek_tui.tools.task_manager import TaskManager


@dataclass(frozen=True, slots=True)
class AssemblyRequest:
    config: Config | None = None
    working_directory: Path | None = None
    mode: str = "agent"
    policy: Policy | None = None
    task_data_dir: Path | None = None
    subagent_state_path: Path | None = None
    mcp_manager: McpManager | None = None
    start_mcp: bool = False
    automation_data_dir: Path | None = None
    automation_tick_interval_secs: float = 15.0
    shared_task_manager: TaskManager | None = None
    contributions: AssembledContributions | None = None


@dataclass(frozen=True, slots=True)
class EngineAssemblyRequest:
    engine_cls: type[Engine]
    handle: EngineHandle
    client: LLMClient
    config: object | None = None
    working_directory: Path | None = None
    mode: str = "agent"
    default_model: str = "deepseek-chat"
    exec_policy: ExecPolicyEngine | None = None
    approval_handler: ApprovalHandler | None = None
    max_tool_round_trips: int = 100
    task_data_dir: Path | None = None
    tool_runtime: object | None = None
    start_mcp: bool | None = None
    mcp_manager: object | None = None
    contributions: AssembledContributions | None = None


@dataclass(frozen=True, slots=True)
class AssembledContributions:
    modules: tuple[CapabilityModule, ...]
    services: ServiceRegistry
    lifecycle: LifecycleRegistry
    surfaces: RuntimeSurfaceRegistry
    tool_packs: tuple[ToolPack, ...]
    prompt_contributors: tuple[PromptContributor, ...]
    post_turn_pipelines: tuple[PostTurnPipelineContribution, ...]


def collect_builtin_contributions(
    config: Config,
    *,
    catalog: BuiltinModuleCatalog | None = None,
) -> AssembledContributions:
    """Collect enabled first-party module contributions without materializing runtime."""
    resolved_catalog = catalog or default_builtin_catalog()
    modules = resolved_catalog.enabled_for(config)
    contributions = Contributions()
    for module in modules:
        module.contribute(contributions)
    return AssembledContributions(
        modules=modules,
        services=contributions.services,
        lifecycle=contributions.lifecycle,
        surfaces=contributions.surfaces,
        tool_packs=contributions.tool_packs(),
        prompt_contributors=contributions.prompt_contributors(),
        post_turn_pipelines=contributions.post_turn_pipelines(),
    )


def resolve_assembly_tool_packs(
    contributions: AssembledContributions,
) -> tuple[ToolPack, ...]:
    if contributions.tool_packs:
        return contributions.tool_packs
    from deepseek_tui.capabilities.toolpacks import default_tool_packs

    return default_tool_packs()


def resolve_assembly_prompt_contributors(
    contributions: AssembledContributions | None = None,
    *,
    config: Config | None = None,
) -> tuple[PromptContributor, ...]:
    """Return prompt contributors from assembled or default builtin catalog."""
    cfg = config or Config()
    assembled = contributions or collect_builtin_contributions(cfg)
    if assembled.prompt_contributors:
        return assembled.prompt_contributors
    return collect_builtin_contributions(cfg, catalog=default_builtin_catalog()).prompt_contributors


def build_tool_registry_from_contributions(
    contributions: AssembledContributions,
    config: Config,
    *,
    mode: str = "agent",
) -> ToolRegistry:
    from deepseek_tui.tools.registry import ToolRegistry

    registry = ToolRegistry()
    for pack in resolve_assembly_tool_packs(contributions):
        for tool in pack.tools(config, mode=mode):
            registry.register(tool)
    return registry


def merge_lifecycle_registries(
    target: LifecycleRegistry,
    source: LifecycleRegistry,
) -> None:
    existing_ids = {registration.id for registration in target.registrations()}
    for registration in source.registrations():
        if registration.id in existing_ids:
            continue
        target.add(
            id=registration.id,
            owner=registration.owner,
            observer=registration.observer,
            order=registration.order,
        )


async def assemble_engine(request: EngineAssemblyRequest) -> Engine:
    """Build Engine from collected capability contributions."""
    engine_cls = cast(Any, request.engine_cls)
    cfg = request.config if isinstance(request.config, Config) else Config()
    contributions = request.contributions or collect_builtin_contributions(cfg)
    return await engine_cls._materialize(
        request.handle,
        request.client,
        config=request.config,
        working_directory=request.working_directory,
        mode=request.mode,
        default_model=request.default_model,
        exec_policy=request.exec_policy,
        approval_handler=request.approval_handler,
        max_tool_round_trips=request.max_tool_round_trips,
        task_data_dir=request.task_data_dir,
        tool_runtime=request.tool_runtime,
        start_mcp=request.start_mcp,
        mcp_manager=request.mcp_manager,
        contributions=contributions,
    )


async def assemble_tool_runtime(request: AssemblyRequest) -> ToolRuntime:
    """Build ToolRuntime from collected capability contributions."""
    from deepseek_tui.tools.runtime import materialize_tool_runtime

    cfg = request.config or Config()
    contributions = request.contributions or collect_builtin_contributions(cfg)
    return await materialize_tool_runtime(
        config=request.config,
        working_directory=request.working_directory,
        mode=request.mode,
        policy=request.policy,
        task_data_dir=request.task_data_dir,
        subagent_state_path=request.subagent_state_path,
        mcp_manager=request.mcp_manager,
        start_mcp=request.start_mcp,
        automation_data_dir=request.automation_data_dir,
        automation_tick_interval_secs=request.automation_tick_interval_secs,
        shared_task_manager=request.shared_task_manager,
        contributions=contributions,
    )


def assemble_registry_only(
    config: Config,
    *,
    mode: str = "agent",
    contributions: AssembledContributions | None = None,
) -> ToolRegistry:
    """Build ToolRegistry from collected capability contributions."""
    cfg = config or Config()
    assembled = contributions or collect_builtin_contributions(cfg)
    return build_tool_registry_from_contributions(assembled, cfg, mode=mode)
