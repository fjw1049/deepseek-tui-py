"""Tests for MCP startup preload."""

from __future__ import annotations

import asyncio

import pytest

from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.mcp.manager import McpPreloadSnapshot


def test_preload_snapshot_ready_flags() -> None:
    warming = McpPreloadSnapshot(phase="warming", tools_count=0)
    assert warming.to_payload()["warming"] is True
    assert warming.to_payload()["ready"] is False

    ready = McpPreloadSnapshot(phase="ready", tools_count=12)
    payload = ready.to_payload()
    assert payload["ready"] is True
    assert payload["warming"] is False

    partial = McpPreloadSnapshot(phase="partial", tools_count=5, enabled_servers=7)
    assert partial.to_payload()["ready"] is True


def test_preload_status_disabled_without_servers() -> None:
    mgr = McpManager([])
    status = mgr.preload_status()
    assert status["phase"] == "disabled"
    assert status["ready"] is True


def test_schedule_preload_skips_when_disk_cache_warm() -> None:
    mgr = McpManager([
        McpServerConfig(name="fetch", command="uvx", args=["mcp-server-fetch"]),
    ])
    mgr._discovered_tools_cache = [{"type": "function", "function": {"name": "mcp_fetch_x"}}]
    mgr.schedule_startup_preload()
    assert mgr.preload_status()["phase"] == "ready"
    assert mgr.preload_status()["from_disk_cache"] is True
    assert mgr._preload._task is None


@pytest.mark.asyncio
async def test_schedule_preload_runs_discover(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = McpManager([
        McpServerConfig(name="fetch", command="uvx", args=["mcp-server-fetch"]),
    ])
    called = asyncio.Event()

    async def fake_discover() -> list[dict]:
        called.set()
        mgr._discovered_tools_cache = [
            {"type": "function", "function": {"name": "mcp_fetch_tool"}},
        ]
        return mgr._discovered_tools_cache

    monkeypatch.setattr(mgr, "discover_tools", fake_discover)
    # The fake discover never starts real clients, so pretend the one
    # enabled server connected — otherwise the phase is "partial".
    monkeypatch.setattr(mgr, "_connected_server_count", lambda: 1)
    mgr.schedule_startup_preload(timeout_s=5.0)
    await asyncio.wait_for(called.wait(), timeout=2.0)
    await asyncio.sleep(0.05)
    status = mgr.preload_status()
    assert status["phase"] == "ready"
    assert status["tools_count"] == 1
