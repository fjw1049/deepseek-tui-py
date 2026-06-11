"""Characterization tests for MCP host integration glue."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deepseek_tui.capabilities.mcp import (
    MCP_PRELOAD_DISABLED_STATUS,
    mcp_preload_status_for_tool_runtime,
    normalize_mcp_tool_name,
    schedule_mcp_preload_for_tool_runtime,
    try_execute_external_mcp_tool,
)
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.tools.base import ToolError


class _PreloadManager(McpManager):
    def __init__(self) -> None:
        super().__init__([])
        self.preload_scheduled = 0

    def schedule_startup_preload(self) -> None:
        self.preload_scheduled += 1

    def preload_status(self) -> dict[str, object]:
        return {"phase": "ready", "warming": False, "ready": True}


class _Runtime:
    def __init__(self, manager: McpManager | None) -> None:
        self.mcp_manager = manager


def test_schedule_mcp_preload_skips_when_disabled() -> None:
    runtime = _Runtime(_PreloadManager())
    schedule_mcp_preload_for_tool_runtime(mcp_enabled=False, tool_runtime=runtime)
    assert runtime.mcp_manager.preload_scheduled == 0


def test_schedule_mcp_preload_invokes_manager() -> None:
    manager = _PreloadManager()
    schedule_mcp_preload_for_tool_runtime(
        mcp_enabled=True,
        tool_runtime=_Runtime(manager),
    )
    assert manager.preload_scheduled == 1


def test_mcp_preload_status_disabled_matches_constant() -> None:
    status = mcp_preload_status_for_tool_runtime(mcp_enabled=False, tool_runtime=None)
    assert status == MCP_PRELOAD_DISABLED_STATUS


def test_mcp_preload_status_reads_manager() -> None:
    manager = _PreloadManager()
    status = mcp_preload_status_for_tool_runtime(
        mcp_enabled=True,
        tool_runtime=_Runtime(manager),
    )
    assert status["phase"] == "ready"


def test_normalize_mcp_tool_name_preserves_external_names() -> None:
    assert normalize_mcp_tool_name("mcp__server__tool") == "mcp__server__tool"


@pytest.mark.asyncio
async def test_try_execute_external_mcp_tool_returns_none_for_native_tool() -> None:
    result = await try_execute_external_mcp_tool(
        manager=McpManager([]),
        tool_name="read_file",
        arguments={},
        registry_contains=True,
    )
    assert result is None


@pytest.mark.asyncio
async def test_try_execute_external_mcp_tool_raises_without_manager() -> None:
    with pytest.raises(ToolError, match="no MCP manager configured"):
        await try_execute_external_mcp_tool(
            manager=None,
            tool_name="mcp__server__tool",
            arguments={},
            registry_contains=False,
        )


class _ExecuteManager(McpManager):
    def __init__(self) -> None:
        super().__init__([])
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        self.calls.append((tool_name, arguments))
        return {"content": [{"type": "text", "text": "ok"}]}


@pytest.mark.asyncio
async def test_try_execute_external_mcp_tool_dispatches_external_tool() -> None:
    manager = _ExecuteManager()
    result = await try_execute_external_mcp_tool(
        manager=manager,
        tool_name="mcp__server__tool",
        arguments={"x": 1},
        registry_contains=False,
    )
    assert result is not None
    assert result.success is True
    assert manager.calls == [("mcp__server__tool", {"x": 1})]


def test_engine_mcp_manager_property_uses_capability_resolver(tmp_path) -> None:
    from deepseek_tui.capabilities.mcp import mcp_manager_from_runtime_or_context
    from deepseek_tui.tools.context import ToolContext

    manager = McpManager([])
    context = ToolContext(working_directory=tmp_path)
    context.services.add(McpManager, manager, owner="test", scope="process")
    resolved = mcp_manager_from_runtime_or_context(
        tool_runtime=SimpleNamespace(mcp_manager=None),
        context=context,
    )
    assert resolved is manager
