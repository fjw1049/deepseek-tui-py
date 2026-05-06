from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.mcp.client import McpClient
from deepseek_tui.mcp.config import McpServerConfig, ToolFilter
from deepseek_tui.mcp.encoding import parse_qualified_tool_name, qualify_tool_name
from deepseek_tui.mcp.loader import load_mcp_config
from deepseek_tui.mcp.manager import McpManager


def test_qualify_tool_name_basic() -> None:
    assert qualify_tool_name("my-server", "read_file") == "mcp__my_server__read_file"


def test_qualify_tool_name_truncates_long_names() -> None:
    long_server = "a" * 40
    long_tool = "b" * 40
    result = qualify_tool_name(long_server, long_tool)
    assert len(result) <= 64
    assert result.startswith("mcp__")


def test_parse_qualified_tool_name() -> None:
    assert parse_qualified_tool_name("mcp__server__tool") == ("server", "tool")
    assert parse_qualified_tool_name("not_mcp") is None
    assert parse_qualified_tool_name("mcp__nodelim") is None


def test_tool_filter_allow_deny() -> None:
    f = ToolFilter(allow=["read_file", "write_file"])
    assert f.accepts("read_file") is True
    assert f.accepts("exec_shell") is False

    f2 = ToolFilter(deny=["exec_shell"])
    assert f2.accepts("read_file") is True
    assert f2.accepts("exec_shell") is False

    f3 = ToolFilter()
    assert f3.accepts("anything") is True


@pytest.mark.asyncio
async def test_mcp_client_lifecycle(tmp_path: Path) -> None:
    """Test MCP client against a simple echo server script."""
    server_script = tmp_path / "echo_server.py"
    server_script.write_text(
        """\
import json, sys

def respond(req_id, result):
    resp = {"jsonrpc": "2.0", "id": req_id, "result": result}
    sys.stdout.write(json.dumps(resp) + "\\n")
    sys.stdout.flush()

for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method", "")
    req_id = msg.get("id")
    if req_id is None:
        continue
    if method == "initialize":
        respond(req_id, {"protocolVersion": "2024-11-05"})
    elif method == "tools/list":
        respond(req_id, {"tools": [
            {"name": "echo", "description": "Echo tool", "inputSchema": {}}
        ]})
    elif method == "tools/call":
        args = msg["params"]["arguments"]
        respond(req_id, {"content": [{"type": "text", "text": args.get("msg", "")}]})
    else:
        respond(req_id, {})
""",
        encoding="utf-8",
    )

    config = McpServerConfig(
        name="echo",
        command="python3",
        args=[str(server_script)],
    )
    client = McpClient(config)
    await client.start()
    assert client.is_running

    tools = await client.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "echo"

    result = await client.call_tool("echo", {"msg": "hello"})
    assert result["content"][0]["text"] == "hello"

    await client.stop()
    assert not client.is_running


@pytest.mark.asyncio
async def test_mcp_manager_discover_and_call(tmp_path: Path) -> None:
    server_script = tmp_path / "mgr_server.py"
    server_script.write_text(
        """\
import json, sys

def respond(req_id, result):
    resp = {"jsonrpc": "2.0", "id": req_id, "result": result}
    sys.stdout.write(json.dumps(resp) + "\\n")
    sys.stdout.flush()

for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method", "")
    req_id = msg.get("id")
    if req_id is None:
        continue
    if method == "initialize":
        respond(req_id, {"protocolVersion": "2024-11-05"})
    elif method == "tools/list":
        respond(req_id, {"tools": [
            {"name": "greet", "description": "Greet", "inputSchema": {}}
        ]})
    elif method == "tools/call":
        respond(req_id, {"greeting": "hi"})
    else:
        respond(req_id, {})
""",
        encoding="utf-8",
    )

    config = McpServerConfig(
        name="greeter",
        command="python3",
        args=[str(server_script)],
    )
    manager = McpManager([config])
    await manager.start_all()

    tools = await manager.discover_tools()
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "mcp__greeter__greet"
    assert tools[0]["function"]["parameters"] == {}

    result = await manager.call_tool("mcp__greeter__greet", {})
    assert result["greeting"] == "hi"

    await manager.stop_all()


def test_load_mcp_config_supports_servers_and_filters(tmp_path: Path) -> None:
    config_file = tmp_path / "mcp.json"
    config_file.write_text(
        """{
          "timeouts": {"connect_timeout": 3},
          "servers": {
            "demo": {
              "command": "python3",
              "args": ["server.py"],
              "env": {"A": "B"},
              "enabled_tools": ["echo"],
              "disabled_tools": ["danger"]
            }
          }
        }""",
        encoding="utf-8",
    )

    configs = load_mcp_config(config_file)

    assert len(configs) == 1
    assert configs[0].name == "demo"
    assert configs[0].command == "python3"
    assert configs[0].args == ["server.py"]
    assert configs[0].env == {"A": "B"}
    assert configs[0].connect_timeout == 3
    assert configs[0].tool_filter is not None
    assert configs[0].tool_filter.accepts("echo") is True
    assert configs[0].tool_filter.accepts("danger") is False
