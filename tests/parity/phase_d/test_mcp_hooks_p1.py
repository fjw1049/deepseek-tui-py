"""P1 MCP store + lazy reload + slash command parity tests."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.config.models import Config, HooksConfig, LifecycleHookEntry
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.mcp.store import (
    McpWriteStatus,
    add_server_config,
    format_manager_snapshot,
    init_config,
    manager_snapshot_from_config,
    remove_server_config,
    set_server_enabled,
)
from deepseek_tui.tui.commands import CommandResult, dispatch


class TestMcpStoreCrud:
    def test_init_and_add_stdio(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        assert init_config(path) == McpWriteStatus.CREATED
        assert init_config(path) == McpWriteStatus.SKIPPED_EXISTS
        add_server_config(path, "local", command="node", args=["server.js"])
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["servers"]["local"]["command"] == "node"
        assert data["servers"]["local"]["args"] == ["server.js"]

    def test_enable_disable_remove(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        add_server_config(path, "svc", command="echo", args=["hi"])
        set_server_enabled(path, "svc", False)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["servers"]["svc"]["enabled"] is False
        set_server_enabled(path, "svc", True)
        remove_server_config(path, "svc")
        assert "svc" not in json.loads(path.read_text(encoding="utf-8"))["servers"]

    def test_snapshot_format(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        add_server_config(path, "demo", command="echo", args=["x"])
        snapshot = manager_snapshot_from_config(path)
        text = format_manager_snapshot(snapshot)
        assert "demo" in text
        assert "stdio" in text


class TestMcpLazyReload:
    async def test_reload_if_config_changed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "mcp.json"
        add_server_config(path, "a", command="echo", args=["1"])
        mgr = McpManager([McpServerConfig(name="a", command="echo", args=["1"])], config_path=path)
        assert await mgr.reload_if_config_changed() is False

        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["servers"]["b"] = {"command": "echo", "args": ["2"], "enabled": True}
        path.write_text(json.dumps(doc), encoding="utf-8")
        path.touch()
        time.sleep(0.01)

        stop_mock = AsyncMock()
        monkeypatch.setattr(mgr, "stop_all", stop_mock)
        changed = await mgr.reload_if_config_changed()
        assert changed is True
        stop_mock.assert_awaited_once()
        assert "b" in mgr.server_names


class TestSlashMcpCommand:
    def test_mcp_list_from_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from deepseek_tui.tui.app import DeepSeekTUI

        path = tmp_path / "mcp.json"
        add_server_config(path, "demo", command="echo", args=["x"])
        app = DeepSeekTUI(config=Config(mcp_config_path=path))
        result = dispatch("/mcp", app)
        assert isinstance(result, CommandResult)
        assert result.output is not None
        assert "demo" in result.output

    def test_mcp_add_enable_remove(self, tmp_path: Path) -> None:
        from deepseek_tui.tui.app import DeepSeekTUI

        path = tmp_path / "mcp.json"
        init_config(path, force=True)
        app = DeepSeekTUI(config=Config(mcp_config_path=path))
        add_result = dispatch("/mcp add stdio local node server.js", app)
        assert not add_result.error
        assert "Added MCP stdio server 'local'" in (add_result.output or "")
        disable_result = dispatch("/mcp disable local", app)
        assert "Disabled MCP server 'local'" in (disable_result.output or "")
        remove_result = dispatch("/mcp remove local", app)
        assert "Removed MCP server 'local'" in (remove_result.output or "")


class TestMcpToolNaming:
    def test_qualify_uses_single_underscore_format(self) -> None:
        from deepseek_tui.mcp.client import parse_qualified_tool_name, qualify_tool_name

        assert qualify_tool_name("My Server", "Echo-Tool") == "mcp_my_server_echo_tool"
        assert parse_qualified_tool_name("mcp_fixture_echo") == ("fixture", "echo")

    def test_parse_legacy_double_underscore(self) -> None:
        from deepseek_tui.mcp.client import parse_qualified_tool_name

        assert parse_qualified_tool_name("mcp__legacy__tool") == ("legacy", "tool")

    def test_validate_mcp_config_path_rejects_parent_segments(self) -> None:
        from deepseek_tui.mcp.store import validate_mcp_config_path

        with pytest.raises(ValueError, match="\\.\\."):
            validate_mcp_config_path(Path("/tmp/../etc/mcp.json"))


class TestEngineMcpCache:
    async def test_invalidate_mcp_tools_cache_forces_rediscover(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from deepseek_tui.engine.engine import Engine

        engine = Engine.__new__(Engine)
        engine._mcp_tools_cache = [{"function": {"name": "stale"}}]
        engine.tool_registry = MagicMock()
        engine.tool_registry.to_api_tools.return_value = []
        engine.tool_runtime = None

        engine.invalidate_mcp_tools_cache()
        assert engine._mcp_tools_cache is None


class TestAppServerLifecycleHooks:
    def test_stream_engine_events_wires_hook_executor(self) -> None:
        import inspect

        from deepseek_tui.app_server.runtime import AppRuntime

        source = inspect.getsource(AppRuntime._stream_engine_events)
        assert "build_lifecycle_hook_executor" in source
        assert "hook_executor=hook_executor" in source


class TestSlashHooksCommand:
    def test_hooks_events(self) -> None:
        from deepseek_tui.tui.app import DeepSeekTUI

        app = DeepSeekTUI()
        result = dispatch("/hooks events", app)
        assert result.output is not None
        assert "session_start" in result.output

    def test_hooks_list_grouped(self) -> None:
        from deepseek_tui.engine.engine import Engine
        from deepseek_tui.hooks.executor import HookExecutor
        from deepseek_tui.tui.app import DeepSeekTUI

        cfg = HooksConfig(
            enabled=True,
            hooks=[
                LifecycleHookEntry(event="session_start", command="true", name="boot"),
                LifecycleHookEntry(event="tool_call_before", command="true"),
            ],
        )
        app = DeepSeekTUI()
        engine = Engine.__new__(Engine)
        engine.hook_executor = HookExecutor(cfg, Path.cwd())
        app._engine = engine
        result = dispatch("/hooks list", app)
        assert result.output is not None
        assert "### session_start" in result.output
        assert "boot" in result.output
