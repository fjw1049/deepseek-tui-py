"""Regressions from the 2026-11-11 tool / pipeline audit."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.events import ToolResultEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import (
    ToolCapability,
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
)
from tests.engine.test_browser_primary_loop import ScriptedClient


async def _engine(tmp_path: Path, replies: list[Any]) -> tuple[Engine, ScriptedClient]:
    client = ScriptedClient(replies)
    engine = await Engine.create(
        handle=EngineHandle(), client=client, working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False)),
        start_mcp=False,
    )
    engine.reply_locale = "en"
    return engine, client


def _names(request: Any) -> set[str]:
    return {(t.get("function") or t)["name"] for t in request.tools}


# --- pipeline -------------------------------------------------------------


async def test_accepting_a_plan_mid_turn_offers_the_write_tools(tmp_path: Path) -> None:
    engine, client = await _engine(tmp_path, [
        ToolCall(id="exit", name="exit_plan_mode", arguments={}),
        ToolCall(id="write", name="write_file",
                 arguments={"path": "plan_done.txt", "content": "ok"}),
        "Implemented.",
    ])
    engine.mode = "plan"

    async def accept(tool_call_id: str) -> ToolResult:
        await engine.apply_interaction_mode("agent", reason="exit_plan_mode")
        return ToolResult(True, "Plan accepted (Agent). Implement the plan now.")

    engine._handle_exit_plan_mode = accept  # type: ignore[method-assign]
    engine._handle_approval_flow = AsyncMock(return_value=False)  # type: ignore[method-assign]
    try:
        await engine._run_conversation([Message.user("plan then do")], "test", "sys", None)
        assert "write_file" not in _names(client.requests[0])
        assert "write_file" in _names(client.requests[1])
        assert (tmp_path / "plan_done.txt").read_text(encoding="utf-8") == "ok"
    finally:
        await engine.shutdown_session()


class _NeedsApproval(ToolSpec):
    def name(self) -> str:
        return "risky"

    def description(self) -> str:
        return "needs approval"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        raise AssertionError("a denied call must not run")


async def test_denied_tool_call_closes_its_tool_item(tmp_path: Path) -> None:
    engine, _client = await _engine(tmp_path, [
        ToolCall(id="r1", name="risky", arguments={}),
        "Understood.",
    ])
    engine.tool_registry.register(_NeedsApproval())
    engine._handle_approval_flow = AsyncMock(return_value=True)  # type: ignore[method-assign]
    try:
        await engine._run_conversation([Message.user("go")], "test", "sys", None)
        results = [e for e in engine.handle.drain_events() if isinstance(e, ToolResultEvent)]
        assert [(e.tool_call_id, e.success) for e in results] == [("r1", False)]
    finally:
        await engine.shutdown_session()


def test_compacted_output_points_to_the_full_text(tmp_path: Path) -> None:
    from deepseek_tui.engine.context import compact_tool_result_for_context
    from deepseek_tui.tools import runtime

    previous = runtime.set_test_spillover_root(tmp_path / "spill")
    try:
        raw = "\n".join(f"line {i} " + "x" * 40 for i in range(400))
        result = ToolResult(False, raw)
        compacted = compact_tool_result_for_context("gpt-4", "exec_shell", result)
        assert "line 200 " not in compacted
        pointed = runtime.point_compacted_output_to_disk("call_1", "exec_shell", raw, compacted)
        path = runtime.extract_spillover_path_from_text(pointed)
        assert path is not None
        assert "line 200 " in Path(path).read_text(encoding="utf-8")

        # A pointer already inside the text is reused, not lost with the middle.
        marked = raw[:3000] + "\n[Output truncated: Full output saved to /x/shell-1.txt.]\n" + raw
        compacted = compact_tool_result_for_context(
            "gpt-4", "exec_shell", ToolResult(True, marked))
        pointed = runtime.point_compacted_output_to_disk("call_2", "exec_shell", marked, compacted)
        assert pointed.endswith(
            "Full output saved to /x/shell-1.txt. Use read_file (offset/limit) "
            "or grep_files on that path for the omitted part.")

        # Short results are left alone.
        assert runtime.point_compacted_output_to_disk("c", "exec_shell", "hi", "hi") == "hi"
    finally:
        runtime.set_test_spillover_root(previous)


def test_token_estimate_cache_matches_uncached_count(monkeypatch: pytest.MonkeyPatch) -> None:
    from deepseek_tui.engine import context

    calls: list[int] = []

    class Encoder:
        def encode(self, text: str) -> list[int]:
            calls.append(len(text))
            return [0] * (len(text) // 4)

    encoder = Encoder()
    monkeypatch.setattr(context, "_tiktoken_encoder", lambda: encoder)
    text = "a" * 4000
    assert context.estimate_tokens(text) == 1000
    assert context.estimate_tokens("a" * 4000) == 1000
    assert calls == [4000]
    assert context.estimate_tokens(text + "b" * 4) == 1001


# --- tools ----------------------------------------------------------------


async def test_file_search_skips_egg_info_dirs(tmp_path: Path) -> None:
    from deepseek_tui.tools.search import FileSearchTool

    (tmp_path / "pkg.egg-info").mkdir()
    (tmp_path / "pkg.egg-info" / "PKG-INFO").write_text("", encoding="utf-8")
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    result = await FileSearchTool().execute(
        {"pattern": "", "path": "."}, ToolContext(working_directory=tmp_path))
    assert result.content.splitlines()[0] == "app.py"
    assert result.metadata["skipped_default_dirs"] == 1
    assert "Skipped 1 default-filtered" in result.content


async def test_edit_file_on_non_utf8_file_says_so(tmp_path: Path) -> None:
    from deepseek_tui.tools.file import EditFileTool

    (tmp_path / "gbk.txt").write_bytes("中文".encode("gbk"))
    with pytest.raises(ToolError, match="not a UTF-8 text file"):
        await EditFileTool().execute(
            {"path": "gbk.txt", "old_string": "a", "new_string": "b"},
            ToolContext(working_directory=tmp_path),
        )


async def test_read_file_limit_zero_reads_the_default_page(tmp_path: Path) -> None:
    from deepseek_tui.tools.file import ReadFileTool

    (tmp_path / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    result = await ReadFileTool().execute(
        {"path": "a.txt", "limit": 0}, ToolContext(working_directory=tmp_path))
    assert result.content == "1\tone\n2\ttwo"


@pytest.mark.parametrize(
    ("content_type", "body", "binary"),
    [
        ("application/pdf", b"%PDF-1.7 ...", True),
        ("image/png", b"\x89PNG", True),
        ("image/svg+xml", b"<svg/>", False),
        ("application/octet-stream", b"plain: yaml\n", False),
        ("application/octet-stream", b"PK\x03\x04\x00\x00", True),
        ("text/plain; charset=utf-8", b"hello", False),
    ],
)
def test_fetch_url_refuses_binary_bodies(content_type: str, body: bytes, binary: bool) -> None:
    from deepseek_tui.tools.web import _reject_binary_body

    if binary:
        with pytest.raises(ToolError, match="binary content"):
            _reject_binary_body("https://example.com/f", content_type, body)
    else:
        _reject_binary_body("https://example.com/f", content_type, body)


def test_failed_shell_result_without_stderr_states_the_exit_code() -> None:
    from deepseek_tui.tools.shell import _build_shell_result

    empty = _build_shell_result(SimpleNamespace(returncode=1), b"", b"")
    assert empty.success is False and empty.content == "[exit 1]"
    with_stdout = _build_shell_result(SimpleNamespace(returncode=2), b"partial\n", b"")
    assert with_stdout.content == "[exit 2]\npartial"
    ok = _build_shell_result(SimpleNamespace(returncode=0), b"fine\n", b"")
    assert ok.content == "fine"
