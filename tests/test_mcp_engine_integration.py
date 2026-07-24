"""Tests for MCP tool discovery and dispatch integration in the Engine."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from deepseek_tui.engine.dispatch import is_mcp_tool
from deepseek_tui.engine.tools import build_model_tool_catalog
from deepseek_tui.mcp import McpError, McpManager
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.tools.registry import ToolError, ToolResult


# --- is_mcp_tool -----------------------------------------------------------


class TestIsMcpTool:
    def test_mcp_prefixed(self):
        assert is_mcp_tool("mcp_github_create_issue") is True
        assert is_mcp_tool("mcp_fs_read_file") is True

    def test_bridge_tools(self):
        assert is_mcp_tool("list_mcp_resources") is True
        assert is_mcp_tool("list_mcp_resource_templates") is True
        assert is_mcp_tool("mcp_read_resource") is True
        assert is_mcp_tool("read_mcp_resource") is True
        assert is_mcp_tool("mcp_get_prompt") is True

    def test_non_mcp(self):
        assert is_mcp_tool("read_file") is False
        assert is_mcp_tool("exec_shell") is False
        assert is_mcp_tool("") is False


# --- build_model_tool_catalog -----------------------------------------------


class TestBuildModelToolCatalog:
    def test_merges_native_and_mcp(self):
        native = [
            {"type": "function", "function": {"name": "read_file", "description": "Read", "parameters": {}}},
        ]
        mcp = [
            {"type": "function", "function": {"name": "mcp_fs_list", "description": "List", "parameters": {}}},
        ]
        result = build_model_tool_catalog(native, mcp, "agent")
        names = [t["function"]["name"] for t in result]
        assert "read_file" in names
        assert "mcp_fs_list" in names

    def test_empty_mcp_returns_native_only(self):
        native = [
            {"type": "function", "function": {"name": "read_file", "description": "Read", "parameters": {}}},
        ]
        result = build_model_tool_catalog(native, [], "agent")
        assert len(result) == 1
        assert result[0]["function"]["name"] == "read_file"


# --- McpManager.discover_tools mock ----------------------------------------


class TestDiscoverToolsMerged:
    @pytest.fixture
    def mcp_manager(self):
        mgr = McpManager([McpServerConfig(name="test_server", command="echo")])
        discovered = [
            {
                "type": "function",
                "function": {
                    "name": "mcp_test_server_hello",
                    "description": "Say hello",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        mgr.discover_tools = AsyncMock(return_value=discovered)
        # Engine reads cached_tools() and defers cold discovery to a
        # background task — pre-populate the cache so the discovered tool
        # is visible synchronously in this test.
        mgr._discovered_tools_cache = discovered
        return mgr

    async def test_get_tools_with_mcp_includes_discovered(self, mcp_manager):
        from deepseek_tui.engine.orchestrator import Engine
        from deepseek_tui.engine.handle import EngineHandle
        from deepseek_tui.tools.registry import ToolRegistry
        from deepseek_tui.tools.registry import ToolContext
        from deepseek_tui.tools.mcp import MCP_MANAGER_KEY
        from pathlib import Path

        handle = EngineHandle()
        client = AsyncMock()
        ctx = ToolContext(
            working_directory=Path("/tmp"),
            metadata={MCP_MANAGER_KEY: mcp_manager},
        )
        engine = Engine(
            handle=handle,
            client=client,
            tool_context=ctx,
        )
        tools = await engine._get_tools_with_mcp()
        names = [t.get("function", t).get("name") for t in tools]
        assert "mcp_test_server_hello" in names

    async def test_no_mcp_manager_returns_native_only(self):
        from deepseek_tui.engine.orchestrator import Engine
        from deepseek_tui.engine.handle import EngineHandle
        from deepseek_tui.tools.registry import ToolContext
        from pathlib import Path

        handle = EngineHandle()
        client = AsyncMock()
        ctx = ToolContext(working_directory=Path("/tmp"))
        engine = Engine(handle=handle, client=client, tool_context=ctx)
        tools = await engine._get_tools_with_mcp()
        mcp_names = [
            t.get("function", t).get("name") for t in tools
            if t.get("function", t).get("name", "").startswith("mcp_")
        ]
        assert mcp_names == []


# --- McpManager.discover_tools (real path) ---------------------------------


class TestDiscoverToolsConnects:
    async def test_discover_without_prior_start_all(self):
        mgr = McpManager([McpServerConfig(name="test_server", command="echo")])
        mock_client = AsyncMock()
        mock_client.is_running = True
        mock_client.list_tools = AsyncMock(
            return_value=[
                type("D", (), {
                    "name": "hello",
                    "description": "Say hello",
                    "input_schema": {},
                })()
            ]
        )
        mgr._ensure_client = AsyncMock(return_value=mock_client)  # noqa: SLF001

        tools = await mgr.discover_tools()

        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "mcp_test_server_hello"
        mgr._ensure_client.assert_awaited_once_with("test_server")  # noqa: SLF001


# --- MCP approval gate -----------------------------------------------------


class TestMcpToolApproval:
    async def test_external_mcp_tool_requires_approval_on_request_policy(self):
        from deepseek_tui.engine.orchestrator import Engine
        from deepseek_tui.engine.handle import EngineHandle
        from deepseek_tui.policy.approval import ExecPolicyEngine
        from deepseek_tui.policy.approval import ApprovalDecision
        from deepseek_tui.protocol.responses import ToolCall
        from deepseek_tui.tools.registry import ToolContext
        from deepseek_tui.tools.mcp import MCP_MANAGER_KEY
        from pathlib import Path

        mgr = McpManager([McpServerConfig(name="srv", command="echo")])
        mgr.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
        })

        approval_handler = AsyncMock()
        approval_handler.request_approval = AsyncMock(
            return_value=ApprovalDecision.DENIED
        )

        ctx = ToolContext(
            working_directory=Path("/tmp"),
            metadata={MCP_MANAGER_KEY: mgr},
        )
        engine = Engine(
            handle=EngineHandle(),
            client=AsyncMock(),
            tool_context=ctx,
            exec_policy=ExecPolicyEngine(approval_policy="on-request"),
            approval_handler=approval_handler,
        )
        tool_call = ToolCall(
            id="tc-mcp", name="mcp_srv_write", arguments={"x": 1}
        )
        result = await engine._execute_single_tool(tool_call, [], "deepseek-chat")
        assert result is None
        mgr.call_tool.assert_not_awaited()


class TestExecuteMcpTool:
    async def test_successful_call(self):
        from deepseek_tui.mcp.execute import execute_external_mcp_tool

        mgr = McpManager([McpServerConfig(name="srv", command="echo")])
        mgr.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "hello world"}],
            "isError": False,
        })
        result = await execute_external_mcp_tool(
            mgr, "mcp_srv_greet", {"name": "test"}
        )
        assert result.success is True
        assert result.content == "hello world"
        mgr.call_tool.assert_awaited_once_with("mcp_srv_greet", {"name": "test"})

    async def test_error_result(self):
        from deepseek_tui.mcp.execute import execute_external_mcp_tool

        mgr = McpManager([McpServerConfig(name="srv", command="echo")])
        mgr.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "not found"}],
            "isError": True,
        })
        result = await execute_external_mcp_tool(mgr, "mcp_srv_find", {})
        assert result.success is False
        assert "not found" in result.content

    async def test_mcp_error_raises_tool_error(self):
        from deepseek_tui.mcp.execute import execute_external_mcp_tool

        mgr = McpManager([McpServerConfig(name="srv", command="echo")])
        mgr.call_tool = AsyncMock(side_effect=McpError("connection lost"))
        with pytest.raises(ToolError, match="connection lost"):
            await execute_external_mcp_tool(mgr, "mcp_srv_broken", {})

    async def test_multi_content_blocks_joined(self):
        from deepseek_tui.mcp.execute import execute_external_mcp_tool

        mgr = McpManager([McpServerConfig(name="srv", command="echo")])
        mgr.call_tool = AsyncMock(return_value={
            "content": [
                {"type": "text", "text": "line 1"},
                {"type": "text", "text": "line 2"},
            ],
            "isError": False,
        })
        result = await execute_external_mcp_tool(mgr, "mcp_srv_multi", {})
        assert result.success is True
        assert result.content == "line 1\nline 2"

# --- Native deferral on MCP-less branches ------------------------------------


class TestNativeDeferralWithoutMcp:
    """apply_native_tool_deferral must run on every _get_tools_with_mcp
    branch — a missing/cold/empty MCP discovery must not silently ship the
    full (undeferred) tool set to the model."""

    def _engine(self, tmp_path, mcp_manager=None, mode="agent"):
        from deepseek_tui.engine.handle import EngineHandle
        from deepseek_tui.engine.orchestrator import Engine
        from deepseek_tui.tools.mcp import MCP_MANAGER_KEY
        from deepseek_tui.tools.registry import (
            ToolContext,
            build_default_registry,
        )

        metadata = {MCP_MANAGER_KEY: mcp_manager} if mcp_manager is not None else {}
        engine = Engine(
            handle=EngineHandle(),
            client=AsyncMock(),
            tool_context=ToolContext(working_directory=tmp_path, metadata=metadata),
            tool_registry=build_default_registry(mode=mode),
        )
        engine.mode = mode
        return engine

    @staticmethod
    def _defer_map(tools):
        return {
            t.get("function", t).get("name"): bool(
                t.get("function", t).get("defer_loading", False)
            )
            for t in tools
        }

    async def test_no_mcp_manager_defers_non_core_tools(self, tmp_path):
        engine = self._engine(tmp_path)
        defer = self._defer_map(await engine._get_tools_with_mcp())
        assert defer["git_status"] is True
        assert defer["workflow"] is True
        assert defer["read_file"] is False
        assert defer["exec_shell"] is False

    async def test_empty_mcp_discovery_defers_non_core_tools(self, tmp_path):
        mgr = McpManager([McpServerConfig(name="test_server", command="echo")])
        mgr._discovered_tools_cache = []
        engine = self._engine(tmp_path, mcp_manager=mgr)
        defer = self._defer_map(await engine._get_tools_with_mcp())
        assert defer["git_status"] is True
        assert defer["read_file"] is False

    async def test_cold_mcp_discovery_defers_non_core_tools(self, tmp_path):
        mgr = McpManager([McpServerConfig(name="test_server", command="echo")])
        mgr.schedule_background_discover = lambda: None
        engine = self._engine(tmp_path, mcp_manager=mgr)
        defer = self._defer_map(await engine._get_tools_with_mcp())
        assert defer["git_status"] is True
        assert defer["read_file"] is False

    async def test_yolo_mode_defers_nothing_without_mcp(self, tmp_path):
        engine = self._engine(tmp_path, mode="yolo")
        defer = self._defer_map(await engine._get_tools_with_mcp())
        assert defer["git_status"] is False
        assert defer["workflow"] is False
