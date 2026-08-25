"""Composer-facing MCP connection status: connecting / connected / failed."""

from __future__ import annotations

from unittest.mock import MagicMock

from deepseek_tui.mcp.config import LOAD_POLICY_ON_FOCUS, McpServerConfig
from deepseek_tui.mcp.manager import McpManager


def test_status_idle_is_connecting_not_failed() -> None:
    mgr = McpManager(
        [
            McpServerConfig(name="bing-search", command="echo"),
            McpServerConfig(
                name="yahoo-finance",
                command="echo",
                load_policy=LOAD_POLICY_ON_FOCUS,
            ),
        ]
    )
    assert mgr.server_runtime_status("bing-search")["status"] == "connecting"
    assert mgr.server_runtime_status("yahoo-finance")["status"] == "connecting"
    assert mgr.server_runtime_status("missing")["status"] == "disabled"


def test_status_warming_is_connecting() -> None:
    mgr = McpManager([McpServerConfig(name="bing-search", command="echo")])
    mgr._warming_servers.add("bing-search")
    assert mgr.server_runtime_status("bing-search")["status"] == "connecting"


def test_status_error_without_warmup_is_failed() -> None:
    mgr = McpManager([McpServerConfig(name="bing-search", command="echo")])
    mgr._preload.phase = "ready"
    mgr._discover_errors["bing-search"] = "timed out after 10s"
    payload = mgr.server_runtime_status("bing-search")
    assert payload["status"] == "failed"
    assert payload["connected"] is False
    assert "timed out" in (payload["error"] or "")


def test_status_running_progressive_is_connected() -> None:
    mgr = McpManager([McpServerConfig(name="bing-search", command="echo")])
    client = MagicMock()
    client.is_running = True
    mgr._clients["bing-search"] = client
    assert mgr.server_runtime_status("bing-search") == {
        "status": "connected",
        "connected": True,
        "error": None,
    }


def test_on_focus_needs_tools_before_green() -> None:
    mgr = McpManager(
        [
            McpServerConfig(
                name="yahoo-finance",
                command="echo",
                load_policy=LOAD_POLICY_ON_FOCUS,
            )
        ]
    )
    client = MagicMock()
    client.is_running = True
    mgr._clients["yahoo-finance"] = client
    mgr._preload.phase = "warming"
    # Process up, tools not listed yet — still connecting.
    assert mgr.server_runtime_status("yahoo-finance")["status"] == "connecting"
    mgr._focus_api_tools["yahoo-finance"] = [{"type": "function", "function": {"name": "x"}}]
    mgr._preload.phase = "ready"
    assert mgr.server_runtime_status("yahoo-finance")["status"] == "connected"


def test_disabled_config_is_disabled() -> None:
    mgr = McpManager(
        [McpServerConfig(name="yahoo-finance", command="echo", enabled=False)]
    )
    assert mgr.server_runtime_status("yahoo-finance")["status"] == "disabled"
