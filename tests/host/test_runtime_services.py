from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, FeatureConfig, LspSettings
from deepseek_tui.host.assembler import AssemblyRequest, assemble_tool_runtime
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.lsp import LSP_MANAGER_KEY, LspManager
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.tools.automation_manager import AutomationManager
from deepseek_tui.tools.automation_tools import AUTOMATION_MANAGER_KEY
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.runtime import create_tool_runtime
from deepseek_tui.tools.subagent import SubAgentManager
from deepseek_tui.tools.task_manager import TaskManager


def test_tool_context_has_empty_service_registry(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)

    assert isinstance(context.services, ServiceRegistry)
    assert context.metadata == {}


@pytest.mark.asyncio
async def test_create_tool_runtime_registers_task_services(tmp_path: Path) -> None:
    cfg = Config(
        features=FeatureConfig(
            tasks=True,
            subagents=False,
            mcp=False,
            automations=False,
        )
    )
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=tmp_path,
        task_data_dir=tmp_path / "tasks",
    )
    try:
        assert runtime.task_manager is not None
        assert runtime.context.task_manager is runtime.task_manager
        assert runtime.context.metadata["task_manager"] is runtime.task_manager
        assert runtime.context.services.require(TaskManager) is runtime.task_manager
        assert runtime.context.services.require_named("task_manager") is runtime.task_manager
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_create_tool_runtime_registers_lsp_service(tmp_path: Path) -> None:
    cfg = Config(
        features=FeatureConfig(tasks=False, subagents=False, mcp=False),
        lsp=LspSettings(enabled=True),
    )
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=tmp_path,
    )
    try:
        assert runtime.lsp_manager is not None
        assert runtime.context.metadata[LSP_MANAGER_KEY] is runtime.lsp_manager
        assert runtime.context.services.require(LspManager) is runtime.lsp_manager
        assert runtime.context.services.require_named(LSP_MANAGER_KEY) is runtime.lsp_manager
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_create_tool_runtime_registers_mcp_service_without_start(
    tmp_path: Path,
) -> None:
    manager = McpManager([])
    cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=True))
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=tmp_path,
        mcp_manager=manager,
        start_mcp=False,
    )
    try:
        assert runtime.mcp_manager is manager
        assert runtime.context.services.require(McpManager) is manager
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_create_tool_runtime_registers_automation_services(tmp_path: Path) -> None:
    cfg = Config(
        features=FeatureConfig(
            tasks=True,
            subagents=False,
            mcp=False,
            automations=True,
        )
    )
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=tmp_path,
        task_data_dir=tmp_path / "tasks",
        automation_data_dir=tmp_path / "automations",
        automation_tick_interval_secs=60.0,
    )
    try:
        assert runtime.automation_manager is not None
        assert runtime.context.metadata[AUTOMATION_MANAGER_KEY] is runtime.automation_manager
        assert runtime.context.services.require(AutomationManager) is runtime.automation_manager
        assert (
            runtime.context.services.require_named(AUTOMATION_MANAGER_KEY)
            is runtime.automation_manager
        )
        assert runtime.context.services.require(TaskManager) is runtime.task_manager
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_create_tool_runtime_registers_subagent_service(tmp_path: Path) -> None:
    cfg = Config(
        features=FeatureConfig(
            tasks=False,
            subagents=True,
            mcp=False,
            automations=False,
        )
    )
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=tmp_path,
        subagent_state_path=tmp_path / "subagents.json",
    )
    try:
        assert runtime.subagent_manager is not None
        assert runtime.context.subagent_manager is runtime.subagent_manager
        assert runtime.context.services.require(SubAgentManager) is runtime.subagent_manager
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_assemble_tool_runtime_delegates_to_compatible_runtime(tmp_path: Path) -> None:
    cfg = Config(
        features=FeatureConfig(
            tasks=True,
            subagents=False,
            mcp=False,
            automations=False,
        )
    )
    runtime = await assemble_tool_runtime(
        AssemblyRequest(
            config=cfg,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "tasks",
        )
    )
    try:
        assert runtime.task_manager is not None
        assert runtime.context.services.require(TaskManager) is runtime.task_manager
        assert runtime.context.metadata["task_manager"] is runtime.task_manager
    finally:
        await runtime.shutdown()
