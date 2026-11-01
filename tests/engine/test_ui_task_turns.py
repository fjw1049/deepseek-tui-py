"""A UI task ends like any other turn: the model's answer, plus the facts the harness knows."""

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import ApprovalHandler, EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.surfaces import is_task_call
from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolResult, ToolSpec
from tests.engine.test_browser_primary_loop import ScriptedClient


class FakeDesktopTool(ToolSpec):
    def __init__(self, name: str = "cua_js"):
        self._name = name

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return "Desktop REPL"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"code": {"type": "string"}}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(True, "Window: Notes")


async def desktop_engine(tmp_path, replies, *, drop=()):
    client = ScriptedClient(replies)
    engine = await Engine.create(
        handle=EngineHandle(), client=client, working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False)),
        start_mcp=False,
    )
    engine.tool_registry.register(FakeDesktopTool())
    for name in drop:
        engine.tool_registry.remove(name)
    engine._handle_approval_flow = AsyncMock(return_value=False)
    engine.reply_locale = "en"
    return engine, client


def look(call_id="look"):
    return ToolCall(id=call_id, name="cua_js", arguments={"code": "await app.getAXState()"})


def names(request):
    return {(t.get("function") or t)["name"] for t in request.tools}


async def test_ui_turn_ends_on_the_models_plain_answer(tmp_path):
    engine, client = await desktop_engine(tmp_path, [look(), "Notes shows 42."])
    try:
        result = await engine._run_conversation([Message.user("Check Notes")], "test", "sys", None)
        assert len(client.requests) == 2
        assert result.assistant_message.text_content() == "Notes shows 42."
        assert result.task_outcome == {"status": "completed_with_evidence", "remaining": []}
        assert result.completion_note is None
    finally:
        await engine.shutdown_session()


async def test_turn_with_no_tools_has_no_outcome(tmp_path):
    engine, client = await desktop_engine(tmp_path, ["Hello"])
    try:
        result = await engine._run_conversation([Message.user("Hello")], "test", "sys", None)
        assert result.task_outcome is None and result.completion_note is None
    finally:
        await engine.shutdown_session()


async def test_open_desktop_state_reminds_once_then_the_turn_ends(tmp_path):
    from types import SimpleNamespace

    engine, client = await desktop_engine(tmp_path, [
        look(), "Saved it.", "Saved it, but the desktop result is unconfirmed.",
    ])
    engine.tool_context.metadata["cua_session"] = SimpleNamespace(
        unresolved=True, outside_change=False, reset_reason="")
    try:
        result = await engine._run_conversation([Message.user("Save")], "test", "sys", None)
        assert len(client.requests) == 3
        assert "Still open at your stop" in str(client.requests[2].messages[-1].content)
        text = result.assistant_message.text_content()
        assert text == "Saved it, but the desktop result is unconfirmed."
        assert result.task_outcome["status"] == "partial"
        assert "a desktop operation" in result.task_outcome["remaining"][0]
        assert "a desktop operation" in result.completion_note
    finally:
        await engine.shutdown_session()


async def test_note_never_reaches_the_model(tmp_path):
    engine, client = await desktop_engine(tmp_path, [
        ToolCall(id="bad", name="exec_shell", arguments={"command": "false"}), "It failed.",
    ])
    try:
        result = await engine._run_conversation([Message.user("Run")], "test", "sys", None)
        assert result.completion_note and "exec_shell false" in result.completion_note
        assert result.assistant_message.text_content() == "It failed."
        sent = [m.text_content() for r in client.requests for m in r.messages]
        assert not any(result.completion_note in text for text in sent)
    finally:
        await engine.shutdown_session()


async def test_round_limit_keeps_what_the_model_wrote(tmp_path):
    engine, client = await desktop_engine(tmp_path, [look("a"), look("b"), look("c")])
    engine.max_tool_round_trips = 1
    try:
        result = await engine._run_conversation([Message.user("Loop")], "test", "sys", None)
        assert result.task_outcome["status"] == "partial"
        assert "round-trip limit" in result.completion_note
    finally:
        await engine.shutdown_session()


async def test_open_checklist_holds_a_stop_only_once(tmp_path):
    from unittest.mock import Mock

    engine, client = await desktop_engine(tmp_path, ["First stop.", "Second stop."])
    engine._open_checklist_summary = Mock(side_effect=["#1 pending", "#1 changed", "#1 again"])
    try:
        result = await engine._run_conversation([Message.user("Work")], "test", "sys", None)
        assert len(client.requests) == 2
        assert result.assistant_message.text_content() == "Second stop."
    finally:
        await engine.shutdown_session()


async def test_tool_list_never_changes_within_a_turn(tmp_path):
    engine, client = await desktop_engine(tmp_path, [look(), "Notes is open."])
    try:
        await engine._run_conversation([Message.user("Check Notes")], "test", "sys", None)
        assert names(client.requests[0]) == names(client.requests[1])
        assert "finish_task" not in names(client.requests[0])
    finally:
        await engine.shutdown_session()


def test_surface_registry_decides_task_calls():
    assert all(is_task_call(name) for name in ("browser_use", "cua_js", "cua_js_reset"))
    for action in ("run_site", "capture_start", "capture_stop"):
        assert is_task_call("browser_skill", {"action": action})
    for action in ("read_site", "save", "add_site", "read_demonstration"):
        assert not is_task_call("browser_skill", {"action": action})


async def test_reconnect_guide_reaches_the_model_once(tmp_path):
    from types import SimpleNamespace

    guide = "## Computer Use\n" + "Observe before acting.\n" * 300

    class GuideTool(FakeDesktopTool):
        async def execute(self, input_data, context):
            return ToolResult(True, guide + "\n" + input_data["code"])

    engine, client = await desktop_engine(tmp_path, [
        ToolCall(id="first", name="cua_js", arguments={"code": "Window: Notes"}),
        ToolCall(id="again", name="cua_js", arguments={"code": "Window: Notes 2"}),
        "Done.",
    ])
    engine.tool_registry.register(GuideTool())
    engine._cua_session = SimpleNamespace(
        large_texts=[guide], instructions="", human_reserved=False,
        close=AsyncMock(), end_turn=AsyncMock())
    try:
        await engine._run_conversation([Message.user("Check Notes")], "test", "sys", None)
        results = {b.tool_use_id: str(b.content) for m in client.requests[-1].messages
                   for b in m.content if b.type == "tool_result"}
        assert guide in results["first"]
        assert guide not in results["again"]
        assert "tool call first above" in results["again"]
        assert "Window: Notes 2" in results["again"]
    finally:
        await engine.shutdown_session()


async def _session_started_later(engine):
    # Everything on disk now is the user's, as if the session had just begun.
    engine.tool_context.metadata["session_started_at"] = time.time() + 5


async def test_deleting_an_older_file_asks_and_a_refusal_names_the_way_out(tmp_path):
    (tmp_path / "keep.txt").write_text("the user's")
    engine, client = await desktop_engine(tmp_path, [
        ToolCall(id="rm", name="exec_shell", arguments={"command": "rm keep.txt"}),
        "I left it in place.",
    ])
    await _session_started_later(engine)
    engine._handle_approval_flow = AsyncMock(return_value=True)  # denied
    try:
        result = await engine._run_conversation([Message.user("Clean up")], "test", "sys", None)
        assert (tmp_path / "keep.txt").exists()
        refusal = next(str(b.content) for m in client.requests[-1].messages for b in m.content
                       if b.type == "tool_result" and b.tool_use_id == "rm")
        assert "_to_delete/" in refusal and "keep.txt" in refusal
        assert engine._handle_approval_flow.await_args.args[1].force_prompt
        assert "exec_shell rm keep.txt" in result.completion_note
    finally:
        await engine.shutdown_session()


async def test_approved_deletion_runs(tmp_path):
    (tmp_path / "keep.txt").write_text("the user's")
    engine, client = await desktop_engine(tmp_path, [
        ToolCall(id="rm", name="exec_shell", arguments={"command": "rm keep.txt"}), "Removed.",
    ])
    await _session_started_later(engine)
    engine._handle_approval_flow = AsyncMock(return_value=False)
    engine.tool_context.trust_mode = True
    try:
        await engine._run_conversation([Message.user("Delete keep.txt")], "test", "sys", None)
        assert not (tmp_path / "keep.txt").exists()
    finally:
        await engine.shutdown_session()


async def test_nobody_watching_means_deletion_is_refused(tmp_path):
    from deepseek_tui.engine.handle import AutoApprovalHandler
    from deepseek_tui.tools.approval import ApprovalDecision, build_approval_request

    request = build_approval_request("exec_shell", [])
    request.force_prompt = True
    assert await AutoApprovalHandler().request_approval("id", request) is ApprovalDecision.DENIED


async def test_unattended_run_says_so_and_fails_questions_fast(tmp_path):
    question = ToolCall(id="ask", name="request_user_input", arguments={
        "questions": [{"id": "which", "header": "Which", "question": "Which report?"}]})
    engine, client = await desktop_engine(tmp_path, [question, "Assumed the latest report."])
    engine.tool_context.metadata["unattended"] = True
    try:
        result = await asyncio.wait_for(
            engine._run_conversation([Message.user("Summarize")], "test", "sys", None), 5)
        assert "Unattended run" in client.requests[0].system_prompt
        refusal = next(b for m in client.requests[-1].messages for b in m.content
                       if b.type == "tool_result" and b.tool_use_id == "ask")
        assert refusal.is_error and "Nobody is watching" in str(refusal.content)
        assert result.assistant_message.text_content() == "Assumed the latest report."
    finally:
        await engine.shutdown_session()


async def test_unattended_deletion_is_refused_without_waiting_for_a_person(tmp_path):
    (tmp_path / "keep.txt").write_text("the user's")
    engine, client = await desktop_engine(tmp_path, [
        ToolCall(id="rm", name="exec_shell", arguments={"command": "rm keep.txt"}),
        "I left it in place.",
    ])
    await _session_started_later(engine)
    engine.tool_context.metadata["unattended"] = True
    del engine._handle_approval_flow  # the real gate, with a handler that would wait forever
    engine.approval_handler = _NeverAnswers()
    try:
        await asyncio.wait_for(
            engine._run_conversation([Message.user("Clean")], "test", "sys", None), 5)
        assert (tmp_path / "keep.txt").exists()
    finally:
        await engine.shutdown_session()


class _NeverAnswers(ApprovalHandler):
    async def request_approval(self, tool_call_id, request):
        await asyncio.Event().wait()


def _keep(tmp_path, name="keep.txt"):
    (tmp_path / name).write_text("the user's")


async def _run_commands(tmp_path, *commands):
    calls = [ToolCall(id=f"c{i}", name="exec_shell", arguments={"command": c})
             for i, c in enumerate(commands)]
    engine, client = await desktop_engine(tmp_path, [*calls, "Done."])
    await _session_started_later(engine)
    engine.tool_context.metadata["session_started_at"] = time.time() + 5
    engine.tool_context.trust_mode = True
    try:
        result = await engine._run_conversation([Message.user("Work")], "test", "sys", None)
        seen = [str(b.content) for m in client.requests[-1].messages for b in m.content
                if b.type == "tool_result"]
        return result, seen
    finally:
        await engine.shutdown_session()


REMOVES_WITHOUT_RM = "python3 -c \"import os; os.remove('keep.txt')\""


async def test_removal_no_parser_can_see_is_still_reported(tmp_path):
    _keep(tmp_path)
    result, seen = await _run_commands(tmp_path, REMOVES_WITHOUT_RM)
    assert not (tmp_path / "keep.txt").exists()
    assert "no longer at their path: keep.txt" in seen[0]
    assert "keep.txt" in result.completion_note


async def test_a_moved_file_is_not_reported_as_gone(tmp_path):
    _keep(tmp_path)
    result, seen = await _run_commands(tmp_path, "mkdir _to_delete && mv keep.txt _to_delete/")
    assert (tmp_path / "_to_delete" / "keep.txt").exists()
    assert "no longer at their path" not in seen[0]
    assert result.completion_note is None


async def test_a_file_the_session_made_may_vanish_quietly(tmp_path):
    engine, client = await desktop_engine(tmp_path, [
        ToolCall(id="make", name="exec_shell", arguments={"command": "touch mine.txt"}),
        ToolCall(id="drop", name="exec_shell", arguments={"command": REMOVES_WITHOUT_RM.replace(
            "keep.txt", "mine.txt")}),
        "Done.",
    ])
    engine.tool_context.metadata["session_started_at"] = time.time() - 60
    engine.tool_context.trust_mode = True
    try:
        result = await engine._run_conversation([Message.user("Work")], "test", "sys", None)
        assert result.completion_note is None
    finally:
        await engine.shutdown_session()


async def test_an_approved_deletion_is_not_reported_again(tmp_path):
    _keep(tmp_path)
    result, seen = await _run_commands(tmp_path, "rm keep.txt")
    assert not (tmp_path / "keep.txt").exists()
    assert "no longer at their path" not in seen[0]
