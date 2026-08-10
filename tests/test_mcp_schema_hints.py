"""Tests for MCP argument-error schema reinjection."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.mcp.client import McpError
from deepseek_tui.mcp.execute import execute_external_mcp_tool, mcp_response_to_tool_result
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.mcp.schema_hints import (
    enrich_mcp_argument_error,
    format_schema_hint,
    looks_like_argument_error,
)
from deepseek_tui.tools.registry import ToolError


def test_looks_like_argument_error() -> None:
    assert looks_like_argument_error("Missing required field 'query'") is True
    assert looks_like_argument_error("invalid arguments: expected string") is True
    assert looks_like_argument_error("connection reset by peer") is False


def test_format_schema_hint_includes_required_and_search_guidance() -> None:
    hint = format_schema_hint(
        {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "search text"},
                "limit": {"type": "integer"},
            },
        }
    )
    assert "query" in hint
    assert "required" in hint
    assert "tool_search_tool_bm25" in hint


def test_enrich_attaches_schema_only_for_arg_errors() -> None:
    schema = {"type": "object", "required": ["q"], "properties": {"q": {"type": "string"}}}
    enriched = enrich_mcp_argument_error(
        "mcp_demo_search", "Missing required parameter 'q'", schema
    )
    assert "mcp_demo_search" in enriched
    assert '"q"' in enriched or "'q'" in enriched or "q" in enriched
    assert "tool_search_tool_bm25" in enriched

    plain = enrich_mcp_argument_error(
        "mcp_demo_search", "connection reset by peer", schema
    )
    assert "tool_search_tool_bm25" not in plain
    assert "connection reset" in plain


def test_mcp_response_is_error_gets_schema_hint() -> None:
    result = mcp_response_to_tool_result(
        "mcp_demo_search",
        {
            "isError": True,
            "content": [{"type": "text", "text": "Invalid arguments: missing query"}],
        },
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
    )
    assert result.success is False
    assert "query" in result.content
    assert "tool_search_tool_bm25" in result.content


@pytest.mark.asyncio
async def test_execute_external_mcp_tool_enriches_mcp_error() -> None:
    manager = McpManager(configs=[])
    manager._discovered_tools_cache = [  # noqa: SLF001 — test seed
        {
            "type": "function",
            "function": {
                "name": "mcp_demo_search",
                "description": "search",
                "parameters": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
            },
        }
    ]
    manager.call_tool = AsyncMock(  # type: ignore[method-assign]
        side_effect=McpError("Missing required field 'query'")
    )

    with pytest.raises(ToolError, match="Missing required field") as excinfo:
        await execute_external_mcp_tool(manager, "mcp_demo_search", {})
    msg = str(excinfo.value)
    assert "tool_search_tool_bm25" in msg
    assert "query" in msg


def test_lookup_tool_parameters_from_cache() -> None:
    manager = McpManager(configs=[])
    manager._discovered_tools_cache = [  # noqa: SLF001
        {
            "type": "function",
            "function": {
                "name": "mcp_demo_search",
                "parameters": {"type": "object", "required": ["query"]},
            },
        }
    ]
    params = manager.lookup_tool_parameters("mcp_demo_search")
    assert params is not None
    assert params.get("required") == ["query"]
    assert manager.lookup_tool_parameters("mcp_demo_other") is None
