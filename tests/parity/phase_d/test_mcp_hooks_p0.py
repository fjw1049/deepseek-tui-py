"""P0 MCP + lifecycle hooks parity tests (Stage 4 hooks/mcp).

Fast unit/integration tests only — no real MCP subprocess (see test_mcp_e2e_real).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.config.models import Config, HooksConfig, LifecycleHookEntry
from deepseek_tui.hooks.executor import HookContext, HookExecutor, parse_env_lines
from deepseek_tui.mcp.client import McpError
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.mcp.startup import raise_if_required_mcp_failed
from deepseek_tui.protocol.mcp_lifecycle import (
    McpStartupCompleteEvent,
    McpStartupFailure,
    McpStartupStatus,
    McpStartupUpdateEvent,
)


class TestMcpRequiredStartup:
    async def test_raise_if_required_server_failed(self) -> None:
        mgr = McpManager(
            [McpServerConfig(name="must-work", command="echo", required=True)]
        )
        summary = McpStartupCompleteEvent(
            ready=[],
            failed=[McpStartupFailure(server_name="must-work", error="boom")],
        )
        with pytest.raises(McpError, match="Required MCP server"):
            raise_if_required_mcp_failed(mgr._configs, summary)  # noqa: SLF001

    async def test_start_all_fail_on_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mgr = McpManager(
            [
                McpServerConfig(
                    name="must-work",
                    command="echo",
                    required=True,
                )
            ]
        )

        async def _fail(_name: str):  # noqa: ANN001
            raise McpError("connect failed")

        monkeypatch.setattr(mgr, "_ensure_client", _fail)
        with pytest.raises(McpError, match="Required MCP server"):
            await mgr.start_all(fail_on_required=True)

    async def test_optional_failure_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mgr = McpManager(
            [McpServerConfig(name="optional", command="echo", required=False)]
        )

        async def _fail(_name: str):  # noqa: ANN001
            raise McpError("connect failed")

        monkeypatch.setattr(mgr, "_ensure_client", _fail)
        summary = await mgr.start_all(fail_on_required=True)
        assert summary.failed
        assert summary.ready == []


class TestParseEnvLines:
    def test_parses_export_and_comments(self) -> None:
        stdout = "# comment\nexport FOO=bar\nBAZ=\"qux\"\n"
        assert parse_env_lines(stdout) == {"FOO": "bar", "BAZ": "qux"}


class TestHookExecutor:
    async def test_tool_call_before_runs_command(self, tmp_path: Path) -> None:
        marker = tmp_path / "hook.ran"
        cfg = HooksConfig(
            enabled=True,
            hooks=[
                LifecycleHookEntry(
                    event="tool_call_before",
                    command=f"touch {marker}",
                )
            ],
        )
        executor = HookExecutor(cfg, tmp_path)
        await executor.execute(
            "tool_call_before",
            HookContext(tool_name="read_file", session_id="sess_test"),
        )
        assert marker.exists()

    async def test_shell_env_merges_stdout(self, tmp_path: Path) -> None:
        script = tmp_path / "env.sh"
        script.write_text('echo "INJECTED=1"', encoding="utf-8")
        cfg = HooksConfig(
            enabled=True,
            hooks=[
                LifecycleHookEntry(
                    event="shell_env",
                    command=f"sh {script}",
                )
            ],
        )
        executor = HookExecutor(cfg, tmp_path)
        merged = await executor.collect_shell_env_async(
            HookContext(tool_name="exec_shell", workspace=tmp_path)
        )
        assert merged.get("INJECTED") == "1"


class TestAppServerMcpToolRoute:
    async def test_handle_tool_routes_external_mcp(self) -> None:
        from deepseek_tui.app_server.runtime import AppRuntime

        cfg = Config()
        runtime = await AppRuntime.create(config=cfg)
        assert runtime._tool_runtime is not None

        mgr = MagicMock(spec=McpManager)
        mgr.server_names = ["mock"]
        mgr._configs = {"mock": McpServerConfig(name="mock", command="echo")}
        mgr.discover_tools = AsyncMock(
            return_value=[
                {
                    "type": "function",
                    "function": {
                        "name": "mcp_mock_echo",
                        "description": "echo",
                        "parameters": {},
                    },
                }
            ]
        )

        async def _fake_call(name: str, arguments: dict) -> dict:
            assert name == "mcp_mock_echo"
            return {
                "isError": False,
                "content": [{"type": "text", "text": f"echo:{arguments['message']}"}],
            }

        mgr.call_tool = AsyncMock(side_effect=_fake_call)
        runtime._tool_runtime.mcp_manager = mgr

        result = await runtime.handle_tool(
            {
                "call": {
                    "name": "mcp_mock_echo",
                    "arguments": {"message": "appserver-path"},
                }
            }
        )
        assert result["ok"] is True
        assert "appserver-path" in result.get("content", "")
        mgr.call_tool.assert_awaited_once()


class TestEngineLifecycleHooks:
    async def test_run_lifecycle_hook_delegates_to_executor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from deepseek_tui.engine.engine import Engine
        from deepseek_tui.engine.handle import EngineHandle
        from deepseek_tui.hooks.executor import HookExecutor

        cfg = HooksConfig(
            enabled=True,
            hooks=[
                LifecycleHookEntry(
                    event="message_submit",
                    command="true",
                )
            ],
        )
        executor = HookExecutor(cfg, tmp_path)
        execute_mock = AsyncMock()
        monkeypatch.setattr(executor, "execute", execute_mock)
        monkeypatch.setattr(executor, "has_hooks_for_event", lambda _e: True)

        engine = Engine.__new__(Engine)
        engine.hook_executor = executor
        engine.mode = "agent"
        engine.default_model = "deepseek-chat"
        engine.tool_context = MagicMock()
        engine.tool_context.working_directory = tmp_path

        await engine.run_lifecycle_hook("message_submit", message="hello")
        execute_mock.assert_awaited_once()
        assert execute_mock.await_args[0][0] == "message_submit"
        assert execute_mock.await_args[0][1].message == "hello"
    async def test_mcp_startup_emits_generic_event_frames(self, tmp_path: Path) -> None:
        from deepseek_tui.app_server.runtime import AppRuntime

        cfg = Config()
        cfg.hooks.jsonl_path = tmp_path / "hooks.jsonl"
        runtime = await AppRuntime.create(config=cfg)
        assert runtime._tool_runtime is not None

        summary = McpStartupCompleteEvent(
            ready=["mock"],
            failed=[],
            cancelled=[],
        )

        async def _fake_start_all(on_update=None, **kwargs):  # noqa: ANN001
            if on_update is not None:
                await on_update(
                    McpStartupUpdateEvent(
                        server_name="mock",
                        status=McpStartupStatus.starting(),
                    )
                )
                await on_update(
                    McpStartupUpdateEvent(
                        server_name="mock",
                        status=McpStartupStatus.ready(),
                    )
                )
            return summary

        mgr = MagicMock(spec=McpManager)
        mgr.server_names = ["mock"]
        mgr._configs = {"mock": McpServerConfig(name="mock", command="echo", enabled=True)}
        mgr.start_all = AsyncMock(side_effect=_fake_start_all)
        runtime._tool_runtime.mcp_manager = mgr

        out = await runtime.mcp_startup()
        assert out["ok"] is True
        lines = cfg.hooks.jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 2
        types = [json.loads(line)["event"]["frame"]["event"] for line in lines]
        assert "mcp_startup_update" in types
        assert "mcp_startup_complete" in types
