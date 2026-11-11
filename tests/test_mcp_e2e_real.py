"""End-to-end MCP tests against a real stdio subprocess server."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from deepseek_tui.engine.dispatch import is_mcp_tool
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.tools.approval import ExecPolicyEngine
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.mcp import MCP_MANAGER_KEY
from unittest.mock import AsyncMock

FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "minimal_mcp_server.py"


@pytest.fixture
async def mcp_manager():
    cfg = McpServerConfig(
        name="fixture",
        command=sys.executable,
        args=[str(FIXTURE_SERVER)],
        connect_timeout=15.0,
        read_timeout=30.0,
        execute_timeout=30.0,
    )
    manager = McpManager([cfg])
    try:
        yield manager
    finally:
        await manager.stop_all()


@pytest.mark.e2e
class TestMcpStdioE2E:
    @pytest.mark.parametrize("mode", ["ask", "plan"])
    async def test_explicit_readonly_trust_and_revocation(self, mcp_manager, tmp_path, mode):
        from deepseek_tui.config import Config
        from deepseek_tui.tools.registry import ToolError

        context = ToolContext(working_directory=tmp_path, metadata={MCP_MANAGER_KEY: mcp_manager})
        engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=context,
            exec_policy=ExecPolicyEngine(approval_policy="never"), approval_handler=AutoApprovalHandler())
        engine.mode = mode
        config = Config()
        engine._app_config = config
        engine._mcp_tools_cache = await mcp_manager.discover_tools()
        assert not await engine._get_tools_with_mcp()
        config.mcp_read_only_tools = ["mcp_fixture_echo"]
        catalog = await engine._get_tools_with_mcp()
        assert [entry["function"]["name"] for entry in catalog] == ["mcp_fixture_echo"]
        call = ToolCall(id="trusted", name="mcp_fixture_echo", arguments={"message": "real read"})
        result = await engine._execute_single_tool(call, catalog, "test")
        assert result.success and result.content == "echo:real read"
        config.mcp_read_only_tools = []
        with pytest.raises(ToolError, match=f"{mode} mode"):
            await engine._execute_single_tool(call, catalog, "test")

    @pytest.mark.parametrize("mode", ["agent", "ask", "plan"])
    async def test_template_discovery_and_real_file_read(self, tmp_path, mode):
        (tmp_path / "report.txt").write_text("Inventory: 17 completed items", encoding="utf-8")
        manager = McpManager([McpServerConfig(name="fixture", command=sys.executable,
            args=[str(FIXTURE_SERVER), "--resources", str(tmp_path)])])
        context = ToolContext(working_directory=tmp_path, metadata={MCP_MANAGER_KEY: manager})
        from deepseek_tui.tools.mcp import ListMcpResourceTemplatesTool, ReadMcpResourceTool
        from deepseek_tui.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(ListMcpResourceTemplatesTool())
        registry.register(ReadMcpResourceTool())
        engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=context,
                        tool_registry=registry, exec_policy=ExecPolicyEngine(approval_policy="auto"),
                        approval_handler=AutoApprovalHandler())
        engine.mode = mode
        try:
            tools = await engine._get_tools_with_mcp()
            assert "list_mcp_resource_templates" in [entry["function"]["name"] for entry in tools]
            listed = await engine._execute_single_tool(ToolCall(id="list", name="list_mcp_resource_templates",
                arguments={"server": "fixture"}), tools, "deepseek-chat")
            assert listed.success
            templates = listed.metadata["result"]["fixture"]
            assert len(templates) == 2  # both pages from the real stdio process
            uri = templates[0]["uriTemplate"].replace("{name}", "report.txt")
            read = await engine._execute_single_tool(ToolCall(id="read", name="read_mcp_resource",
                arguments={"server": "fixture", "uri": uri}), tools, "deepseek-chat")
            assert read.success and "Inventory: 17 completed items" in read.content
        finally:
            await manager.stop_all()

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

    async def test_list_resources_tools_only_server_returns_empty(
        self, mcp_manager: McpManager
    ) -> None:
        """Tools-only servers omit resources; bridge must not raise Method not found."""
        from deepseek_tui.mcp.client import McpError
        from deepseek_tui.tools.mcp import ListMcpResourcesTool, ReadMcpResourceTool

        client = await mcp_manager._ensure_client("fixture")  # noqa: SLF001
        assert client.supports_capability("resources") is False
        assert await client.list_resources() == []
        assert await client.list_resource_templates() == []
        assert await mcp_manager.list_resources() == {"fixture": []}
        assert await mcp_manager.list_resources("fixture") == {"fixture": []}

        ctx = ToolContext(
            working_directory=Path("/tmp"),
            metadata={MCP_MANAGER_KEY: mcp_manager},
        )
        listed = await ListMcpResourcesTool().execute({}, ctx)
        assert listed.success is True
        assert '"fixture"' in listed.content
        assert "[]" in listed.content

        with pytest.raises(McpError, match="does not support resources"):
            await client.read_resource("file:///nope")
        with pytest.raises(McpError, match="does not support resources"):
            await ReadMcpResourceTool().execute(
                {"server": "fixture", "uri": "file:///nope"}, ctx
            )

    async def test_engine_execute_mcp_tool_e2e(self, mcp_manager: McpManager) -> None:
        await mcp_manager.discover_tools()
        ctx = ToolContext(
            working_directory=Path("/tmp"),
            metadata={MCP_MANAGER_KEY: mcp_manager},
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
