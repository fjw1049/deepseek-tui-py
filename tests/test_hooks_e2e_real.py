"""End-to-end hooks tests with real JSONL + shell sinks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, HooksConfig, ShellHookConfig
from deepseek_tui.engine.events import (
    SessionStartedEvent,
    TextDeltaEvent,
    ToolCallEvent,
    TurnStartedEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.hooks.build import build_hook_dispatcher
from deepseek_tui.protocol.responses import ToolCall


@pytest.mark.e2e
class TestHooksJsonlE2E:
    async def test_engine_handle_writes_jsonl(self, tmp_path: Path) -> None:
        log_path = tmp_path / "events.jsonl"
        cfg = Config(hooks=HooksConfig(jsonl_path=log_path))
        dispatcher = build_hook_dispatcher(cfg)
        handle = EngineHandle(hooks=dispatcher)
        handle.set_response_id("resp-e2e-1")

        await handle.emit(TurnStartedEvent(user_text="hi"))
        await handle.emit(TextDeltaEvent(text="world"))
        await handle.emit(SessionStartedEvent(session_id="sess-e2e"))

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

        types = [json.loads(line)["event"]["type"] for line in lines]
        assert types == ["response_start", "response_delta", "session_lifecycle"]

        delta = json.loads(lines[1])["event"]
        assert delta["delta"] == "world"
        assert delta["response_id"] == "resp-e2e-1"


@pytest.mark.e2e
class TestHooksShellE2E:
    async def test_shell_hook_receives_event_json(self, tmp_path: Path) -> None:
        marker = tmp_path / "shell_hook_out.json"
        helper = tmp_path / "capture_stdin.py"
        helper.write_text(
            "import sys\nfrom pathlib import Path\n"
            f"Path({str(marker)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n",
            encoding="utf-8",
        )
        cfg = Config(
            hooks=HooksConfig(
                shell_hooks=[
                    ShellHookConfig(
                        event="tool_lifecycle",
                        command=f"{sys.executable} {helper}",
                    )
                ]
            )
        )
        dispatcher = build_hook_dispatcher(cfg)
        handle = EngineHandle(hooks=dispatcher)

        tc = ToolCall(id="tc-shell", name="read_file", arguments={"path": "x"})
        await handle.emit(ToolCallEvent(tool_call=tc))

        assert marker.is_file()
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["type"] == "tool_lifecycle"
        assert payload["tool_name"] == "read_file"
        assert payload["phase"] == "start"
