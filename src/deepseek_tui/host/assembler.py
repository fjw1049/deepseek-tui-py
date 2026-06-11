"""Compatibility assembler for capability-module migration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from deepseek_tui.config.models import Config

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.engine.engine import ApprovalHandler, Engine
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.execpolicy.engine import ExecPolicyEngine
    from deepseek_tui.execpolicy.policy import Policy
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


async def assemble_engine(request: EngineAssemblyRequest) -> Engine:
    """Build the existing Engine through the host composition entry point."""
    engine_cls = cast(Any, request.engine_cls)
    return await engine_cls._create_legacy(
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
    )


async def assemble_tool_runtime(request: AssemblyRequest) -> ToolRuntime:
    """Build the existing ToolRuntime through the host composition entry point.

    This is deliberately a compatibility adapter: no capability ownership moves
    here yet. The next phases can replace the legacy delegate one service at a
    time while keeping the public ``create_tool_runtime`` API stable.
    """
    from deepseek_tui.tools.runtime import _create_tool_runtime_legacy

    return await _create_tool_runtime_legacy(
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
    )


def assemble_registry_only(config: Config, *, mode: str = "agent") -> ToolRegistry:
    """Build the existing ToolRegistry through the host composition entry point."""
    from deepseek_tui.tools.builder import _build_default_registry_legacy

    return _build_default_registry_legacy(config, mode=mode)
