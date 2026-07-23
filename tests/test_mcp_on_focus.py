"""Contract tests for load_policy=on_focus media connectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.mcp.client import McpError, McpToolDescriptor, qualify_tool_name
from deepseek_tui.mcp.config import (
    LOAD_POLICY_ON_FOCUS,
    LOAD_POLICY_PROGRESSIVE,
    McpServerConfig,
    servers_from_document,
)
from deepseek_tui.mcp.manager import McpManager


def test_servers_from_document_parses_load_policy_and_catalog() -> None:
    configs = servers_from_document(
        {
            "mcpServers": {
                "yahoo": {"command": "uvx", "args": ["mcp-yahoo-finance"]},
                "tikhub-wechat": {
                    "command": "npx",
                    "args": ["mcp-remote", "https://example"],
                    "load_policy": "on_focus",
                    "catalog": "media",
                },
            }
        }
    )
    by_name = {c.name: c for c in configs}
    assert by_name["yahoo"].load_policy == LOAD_POLICY_PROGRESSIVE
    assert by_name["yahoo"].catalog is None
    assert by_name["tikhub-wechat"].load_policy == LOAD_POLICY_ON_FOCUS
    assert by_name["tikhub-wechat"].is_on_focus is True
    assert by_name["tikhub-wechat"].catalog == "media"


def test_servers_from_document_accepts_nested_mcp_servers() -> None:
    """TikHub documented shape: {\"mcp\": {\"servers\": {...}}}."""
    configs = servers_from_document(
        {
            "mcp": {
                "servers": {
                    "tikhub-zhihu": {
                        "command": "npx",
                        "args": [
                            "mcp-remote",
                            "https://mcp.tikhub.io/zhihu/mcp",
                            "--header",
                            "Authorization: Bearer YOUR_API_KEY",
                        ],
                        "load_policy": "on_focus",
                        "catalog": "media",
                    }
                }
            }
        }
    )
    assert len(configs) == 1
    assert configs[0].name == "tikhub-zhihu"
    assert configs[0].command == "npx"
    assert configs[0].args[1] == "https://mcp.tikhub.io/zhihu/mcp"
    assert configs[0].is_on_focus is True


@pytest.mark.asyncio
async def test_discover_tools_skips_on_focus_servers(tmp_path: Path) -> None:
    progressive = McpServerConfig(name="fetch", command="echo")
    media = McpServerConfig(
        name="tikhub-wechat",
        command="echo",
        load_policy=LOAD_POLICY_ON_FOCUS,
        catalog="media",
    )
    mgr = McpManager([progressive, media], config_path=tmp_path / "mcp.json")

    async def fake_ensure(name: str) -> Any:
        client = MagicMock()
        client.is_running = True

        async def list_tools() -> list[McpToolDescriptor]:
            return [
                McpToolDescriptor(
                    name="do_thing",
                    description=f"{name} tool",
                    input_schema={"type": "object", "properties": {}},
                )
            ]

        client.list_tools = list_tools
        return client

    mgr._ensure_client = fake_ensure  # type: ignore[method-assign]

    tools = await mgr.discover_tools()
    names = {t["function"]["name"] for t in tools}
    assert qualify_tool_name("fetch", "do_thing") in names
    assert qualify_tool_name("tikhub-wechat", "do_thing") not in names
    assert "tikhub-wechat" not in mgr.grouped_discovered_tools()


@pytest.mark.asyncio
async def test_ensure_focus_discovers_and_release_clears(tmp_path: Path) -> None:
    media = McpServerConfig(
        name="tikhub-wechat",
        command="echo",
        load_policy=LOAD_POLICY_ON_FOCUS,
        catalog="media",
    )
    mgr = McpManager([media], config_path=tmp_path / "mcp.json")

    async def fake_ensure(name: str) -> Any:
        client = MagicMock()
        client.is_running = True
        client.stop = AsyncMock()

        async def list_tools() -> list[McpToolDescriptor]:
            return [
                McpToolDescriptor(
                    name="search",
                    description="search",
                    input_schema={"type": "object", "properties": {}},
                )
            ]

        client.list_tools = list_tools
        mgr._clients[name] = client
        return client

    mgr._ensure_client = fake_ensure  # type: ignore[method-assign]

    tools = await mgr.ensure_focus_server_discovered("tikhub-wechat")
    assert len(tools) == 1
    assert mgr.focus_api_tools("tikhub-wechat")
    assert "tikhub-wechat" in mgr.grouped_discovered_tools()
    # Still excluded from progressive cache.
    assert mgr.cached_tools() in (None, [])

    await mgr.release_focus_server("tikhub-wechat")
    assert mgr.focus_api_tools("tikhub-wechat") == []
    assert "tikhub-wechat" not in mgr.grouped_discovered_tools()


@pytest.mark.asyncio
async def test_ensure_focus_disabled_raises() -> None:
    media = McpServerConfig(
        name="tikhub-wechat",
        command="echo",
        enabled=False,
        load_policy=LOAD_POLICY_ON_FOCUS,
        catalog="media",
    )
    mgr = McpManager([media])
    with pytest.raises(McpError, match="disabled"):
        await mgr.ensure_focus_server_discovered("tikhub-wechat")


@pytest.mark.asyncio
async def test_disk_cache_strips_on_focus_tools(tmp_path: Path) -> None:
    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fetch": {"command": "echo"},
                    "tikhub-wechat": {
                        "command": "echo",
                        "load_policy": "on_focus",
                        "catalog": "media",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    from deepseek_tui.mcp.store import hash_mcp_document, load_raw_document

    doc = load_raw_document(cfg_path)
    cache_path = tmp_path / "mcp-tools-cache.json"
    fetch_q = qualify_tool_name("fetch", "a")
    media_q = qualify_tool_name("tikhub-wechat", "b")
    cache_path.write_text(
        json.dumps(
            {
                "config_hash": hash_mcp_document(doc),
                "tools": [
                    {"type": "function", "function": {"name": fetch_q, "description": ""}},
                    {"type": "function", "function": {"name": media_q, "description": ""}},
                ],
                "tool_map": {
                    fetch_q: ["fetch", "a"],
                    media_q: ["tikhub-wechat", "b"],
                },
            }
        ),
        encoding="utf-8",
    )

    configs = servers_from_document(doc)
    mgr = McpManager(configs, config_path=cfg_path)
    cached = mgr.cached_tools() or []
    names = {t["function"]["name"] for t in cached}
    assert fetch_q in names
    assert media_q not in names


@pytest.mark.asyncio
async def test_start_all_skips_on_focus() -> None:
    progressive = McpServerConfig(name="fetch", command="echo")
    media = McpServerConfig(
        name="tikhub-wechat",
        command="echo",
        load_policy=LOAD_POLICY_ON_FOCUS,
    )
    mgr = McpManager([progressive, media])
    started: list[str] = []

    async def fake_ensure(name: str) -> Any:
        started.append(name)
        client = MagicMock()
        client.is_running = True
        return client

    mgr._ensure_client = fake_ensure  # type: ignore[method-assign]
    summary = await mgr.start_all()
    assert "fetch" in summary.ready
    assert "tikhub-wechat" in summary.cancelled
    assert "tikhub-wechat" not in started
