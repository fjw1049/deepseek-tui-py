"""End-to-end MCP tests against a real stdio subprocess server."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from deepseek_tui.engine.dispatch import is_mcp_tool
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.execpolicy.engine import ExecPolicyEngine
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.mcp_tools import MCP_MANAGER_KEY
from unittest.mock import AsyncMock

FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "minimal_mcp_server.py"


@pytest.fixture
def mcp_manager() -> McpManager:
    cfg = McpServerConfig(
        name="fixture",
        command=sys.executable,
        args=[str(FIXTURE_SERVER)],
        connect_timeout=15.0,
        read_timeout=30.0,
        execute_timeout=30.0,
    )
    return McpManager([cfg])


@pytest.mark.e2e
class TestMcpStdioE2E:
    async def test_client_list_and_call_echo(self, mcp_manager: McpManager) -> None:
        client = await mcp_manager._ensure_client("fixture")  # noqa: SLF001
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert "echo" in names

        result = await client.call_tool("echo", {"message": "hello-real"})
        assert result.get("isError") is False
        blocks = result.get("content", [])
        assert blocks[0]["text"] == "echo:hello-real"

    async def test_discover_tools_exposes_qualified_name(
        self, mcp_manager: McpManager
    ) -> None:
        tools = await mcp_manager.discover_tools()
        names = [t["function"]["name"] for t in tools]
        assert "mcp_fixture_echo" in names
        assert is_mcp_tool("mcp_fixture_echo")

    async def test_manager_call_tool_qualified(self, mcp_manager: McpManager) -> None:
        await mcp_manager.discover_tools()
        result = await mcp_manager.call_tool(
            "mcp_fixture_echo", {"message": "via-manager"}
        )
        assert result["content"][0]["text"] == "echo:via-manager"

    async def test_engine_execute_mcp_tool_e2e(self, mcp_manager: McpManager) -> None:
        await mcp_manager.discover_tools()
        from deepseek_tui.host.services import ServiceScope

        ctx = ToolContext(working_directory=Path("/tmp"))
        ctx.services.add_named(
            MCP_MANAGER_KEY,
            mcp_manager,
            owner="test",
            scope=ServiceScope.PROCESS,
        )
        engine = Engine(
            handle=EngineHandle(),
            client=AsyncMock(),
            tool_context=ctx,
            exec_policy=ExecPolicyEngine(approval_policy="auto"),
            approval_handler=AutoApprovalHandler(),
        )
        engine._mcp_tools_cache = await mcp_manager.discover_tools()
        api_tools = await engine._get_tools_with_mcp()
        tool_names = [t["function"]["name"] for t in api_tools]
        assert "mcp_fixture_echo" in tool_names

        tc = ToolCall(
            id="tc-e2e",
            name="mcp_fixture_echo",
            arguments={"message": "engine-path"},
        )
        result = await engine._execute_single_tool(tc, api_tools, "deepseek-chat")
        assert result is not None
        assert result.success is True
        assert result.content == "echo:engine-path"
