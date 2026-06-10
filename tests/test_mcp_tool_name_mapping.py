"""Tests for MCP qualified tool name mapping.

``mcp_<server>_<tool>`` is ambiguous when the server name contains
underscores, so the manager persists the real ``(server, tool)`` pairs in
its tools cache and only falls back to string parsing when the cache has
no entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.mcp.client import parse_qualified_tool_name, qualify_tool_name
from deepseek_tui.mcp.manager import McpManager


def test_qualify_keeps_mcp_prefix_for_underscore_server() -> None:
    assert qualify_tool_name("my_server", "do_thing") == "mcp_my_server_do_thing"


def test_parse_fallback_is_ambiguous_for_underscore_server() -> None:
    # Documented limitation: parsing splits on the first underscore, so an
    # underscore-bearing server name is mis-split. Callers must prefer the
    # cached (server, tool) mapping.
    assert parse_qualified_tool_name("mcp_my_server_do_thing") == (
        "my",
        "server_do_thing",
    )


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {"servers": {"my_server": {"command": "echo", "enabled": True}}}
        ),
        encoding="utf-8",
    )
    return path


def test_cached_tool_map_survives_disk_roundtrip(config_path: Path) -> None:
    qualified = qualify_tool_name("my_server", "do_thing")
    mgr = McpManager(config_path=config_path)
    mgr._tool_map = {qualified: ("my_server", "do_thing")}
    mgr._cached_tool_map = dict(mgr._tool_map)
    mgr._discovered_tools_cache = [
        {
            "type": "function",
            "function": {"name": qualified, "description": "", "parameters": {}},
        }
    ]
    mgr._persist_discovered_tools_cache_to_disk()

    # A fresh manager reloads the cache + tool map from disk; the rebuilt
    # mapping must point at the real server, not the mis-parsed "my".
    fresh = McpManager(config_path=config_path)
    assert fresh._discovered_tools_cache is not None
    fresh._rebuild_tool_map_from_cache()
    assert fresh._tool_map[qualified] == ("my_server", "do_thing")


def test_rebuild_falls_back_to_parsing_without_cached_map() -> None:
    mgr = McpManager([])
    mgr._discovered_tools_cache = [
        {
            "type": "function",
            "function": {"name": "mcp_fetch_get", "description": "", "parameters": {}},
        }
    ]
    mgr._rebuild_tool_map_from_cache()
    assert mgr._tool_map["mcp_fetch_get"] == ("fetch", "get")
