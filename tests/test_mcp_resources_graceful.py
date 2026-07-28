"""Unit tests for optional MCP resources capability handling."""

from __future__ import annotations

from deepseek_tui.mcp.client import McpError, is_method_not_found


def test_is_method_not_found_by_code() -> None:
    assert is_method_not_found(McpError("MCP error: Method not found", code=-32601))
    assert not is_method_not_found(McpError("MCP error: boom", code=-32603))


def test_is_method_not_found_by_message() -> None:
    assert is_method_not_found(McpError("MCP error: method not found: resources/list"))
    assert is_method_not_found(RuntimeError("Method not found"))
    assert not is_method_not_found(McpError("timeout"))
