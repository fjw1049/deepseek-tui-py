"""Every UI surface ends through the delivery contract; only the browser narrows tools."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.surfaces import is_focus_call, is_task_call
from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolResult, ToolSpec
from deepseek_tui.tools.task_delivery import TaskDelivery
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


async def test_desktop_stop_without_delivery_is_partial_not_completed(tmp_path):
    # A narrated next step ("I'll dismiss the dialog") must not end the task as done.
    engine, client = await desktop_engine(tmp_path, [
        look(), "I'll dismiss the prompt next.", "Dismissing it now.", "Dismissing it now.",
    ])
    try:
        result = await engine._run_conversation([Message.user("Message Ann")], "test", "sys", None)
        assert len(client.requests) == 4
        assert "finish_task" in names(client.requests[2]) and len(names(client.requests[2])) > 1
        assert names(client.requests[-1]) == {"finish_task"}
        assert result.task_outcome["status"] == "partial"
        assert "not verified" in result.assistant_message.text_content()
    finally:
        await engine.shutdown_session()


def finish(answer, evidence=("tool:invented",)):
    return ToolCall(id=f"finish-{len(answer)}", name="finish_task", arguments={
        "status": "completed", "answer": answer, "evidence": list(evidence), "remaining": [],
    })


async def test_rejected_delivery_keeps_the_models_answer(tmp_path):
    # When finalization runs out, the user still gets the answer the model wrote,
    # marked unverified, instead of a stock sentence that hides all the work.
    # A rejected finish opens the one-round finalization; the latest attempt wins.
    engine, client = await desktop_engine(tmp_path, [
        look(),
        finish("Notes shows 42."),
        finish("Notes shows 42; the sync date was not checked."),
    ])
    try:
        result = await engine._run_conversation([Message.user("Check Notes")], "test", "sys", None)
        text = result.assistant_message.text_content()
        assert text.startswith("Notes shows 42; the sync date was not checked.")
        assert "not verified" in text
        assert result.task_outcome["status"] == "partial"
        assert result.task_outcome["answer"] == text
    finally:
        await engine.shutdown_session()


async def test_desktop_task_keeps_its_tools_and_delivers_with_evidence(tmp_path):
    (tmp_path / "notes.txt").write_text("42")
    engine, client = await desktop_engine(tmp_path, [
        look(),
        ToolCall(id="file", name="read_file", arguments={"path": "notes.txt"}),
        ToolCall(id="finish", name="finish_task", arguments={
            "status": "completed", "answer": "Notes shows 42.",
            "evidence": ["tool:look"], "remaining": [],
        }),
    ])
    try:
        result = await engine._run_conversation([Message.user("Check Notes")], "test", "sys", None)
        results = {b.tool_use_id: b for m in client.requests[-1].messages
                   for b in m.content if b.type == "tool_result"}
        assert not results["file"].is_error  # no browser-style focus for desktop work
        assert "finish_task" in names(client.requests[1])
        assert result.task_outcome["status"] == "completed"
        assert result.assistant_message.text_content() == "Notes shows 42."
    finally:
        await engine.shutdown_session()


async def test_without_finish_task_in_catalog_the_turn_ends_normally(tmp_path):
    engine, client = await desktop_engine(tmp_path, [look(), "Notes shows 42."], drop=[
        "finish_task", "request_task_tools",
    ])
    try:
        result = await engine._run_conversation([Message.user("Check Notes")], "test", "sys", None)
        assert len(client.requests) == 2
        assert result.task_outcome is None
        assert result.assistant_message.text_content() == "Notes shows 42."
    finally:
        await engine.shutdown_session()


def test_surface_registry_decides_task_and_focus():
    assert all(is_task_call(name) for name in ("browser_use", "cua_js", "cua_js_reset"))
    for action in ("run_site", "capture_start", "capture_stop"):
        assert is_task_call("browser_skill", {"action": action})
        assert is_focus_call("browser_skill", {"action": action})
    for action in ("read_site", "save", "add_site", "read_demonstration"):
        assert not is_task_call("browser_skill", {"action": action})
    assert is_focus_call("browser_use")
    assert not is_focus_call("cua_js")


@pytest.mark.parametrize("focused,allowed", [(False, True), (True, False)])
def test_focus_is_separate_from_the_delivery_contract(focused, allowed):
    state = TaskDelivery(active=True, focused=focused, catalog={"write_file"})
    assert state.allows("write_file") is allowed
    assert state.allows("cua_js")


async def test_accepted_partial_delivery_survives_open_checklist(tmp_path):
    engine, client = await desktop_engine(tmp_path, [
        look(),
        ToolCall(id="finish", name="finish_task", arguments={
            "status": "partial", "answer": "Saved draft; heading needs manual correction.",
            "evidence": ["tool:look"], "remaining": ["Correct heading"],
        }),
    ])
    from unittest.mock import Mock
    engine._next_checklist_gate_summary = Mock(return_value="#1 pending")
    try:
        result = await engine._run_conversation(
            [Message.user("Edit document")], "test", "sys", None)
        assert result.task_outcome['status'] == 'partial'
        assert result.assistant_message.text_content() == (
            'Saved draft; heading needs manual correction.')
        assert len(client.requests) == 2
    finally:
        await engine.shutdown_session()


async def test_reconnect_guide_reaches_the_model_once(tmp_path):
    from types import SimpleNamespace

    guide = "## Computer Use\n" + "Observe before acting.\n" * 300

    class GuideTool(FakeDesktopTool):
        async def execute(self, input_data, context):
            return ToolResult(True, guide + "\n" + input_data["code"])

    engine, client = await desktop_engine(tmp_path, [
        ToolCall(id="first", name="cua_js", arguments={"code": "Window: Notes"}),
        ToolCall(id="again", name="cua_js", arguments={"code": "Window: Notes 2"}),
        ToolCall(id="finish", name="finish_task", arguments={
            "status": "completed", "answer": "Done.", "evidence": ["tool:again"],
            "remaining": [],
        }),
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


@pytest.mark.parametrize("verified", [True, False])
async def test_site_replay_requires_delivery_and_verified_evidence(tmp_path, monkeypatch, verified):
    from deepseek_tui.tools.browser_skill import BrowserSkillTool

    async def replay(*args):
        return {"verified": verified, "stopped_at": None if verified else {"reason": "needs_user"}}

    monkeypatch.setattr("deepseek_tui.tools.browser_skill._run_site", replay)
    replies = [
        ToolCall(id="replay", name="browser_skill", arguments={"action": "run_site"}),
        ToolCall(id="done", name="finish_task", arguments={
            "status": "completed", "answer": "Verified.", "evidence": ["tool:replay"],
            "remaining": [],
        }),
    ]
    if not verified:
        replies.append(ToolCall(id="blocked", name="finish_task", arguments={
            "status": "blocked", "answer": "User input needed.", "evidence": [],
            "remaining": ["Enter the secret"],
        }))
    engine, client = await desktop_engine(tmp_path, replies)
    engine.tool_registry.register(BrowserSkillTool())
    engine.tool_context.metadata.update(browser_service=object(), runtime_thread_id="t")
    try:
        result = await engine._run_conversation([Message.user("Run the recorded task")], "test", "sys", None)
        assert "finish_task" in names(client.requests[1])
        assert result.task_outcome["status"] == ("completed" if verified else "blocked")
        if not verified:
            results = {b.tool_use_id: b for m in client.requests[-1].messages
                       for b in m.content if b.type == "tool_result"}
            assert results["done"].is_error
            assert "Unknown evidence" in results["done"].content
    finally:
        await engine.shutdown_session()


async def test_tool_list_stays_stable_when_a_desktop_task_starts(tmp_path):
    # Adding the delivery controls at the first UI call voided the provider prefix cache.
    engine, client = await desktop_engine(tmp_path, [
        look(),
        ToolCall(id="finish", name="finish_task", arguments={
            "status": "completed", "answer": "Notes is open.",
            "evidence": ["tool:look"], "remaining": [],
        }),
    ])
    try:
        await engine._run_conversation([Message.user("Check Notes")], "test", "sys", None)
        assert "finish_task" in names(client.requests[0])
        assert names(client.requests[0]) == names(client.requests[1])
    finally:
        await engine.shutdown_session()


async def test_finish_outside_a_ui_task_points_back_to_a_direct_answer(tmp_path):
    engine, client = await desktop_engine(tmp_path, [
        ToolCall(id="early", name="finish_task", arguments={
            "status": "completed", "answer": "Hi", "evidence": [], "remaining": [],
        }),
        "Hi",
    ])
    try:
        result = await engine._run_conversation([Message.user("Hello")], "test", "sys", None)
        errors = [b.content for m in client.requests[-1].messages for b in m.content
                  if b.type == "tool_result" and b.is_error]
        assert any("directly" in str(e) for e in errors)
        assert result.assistant_message.text_content() == "Hi"
        assert result.task_outcome is None
    finally:
        await engine.shutdown_session()


async def test_sessions_without_ui_surfaces_do_not_offer_delivery_controls(tmp_path):
    engine, client = await desktop_engine(tmp_path, ["Hello"], drop=("cua_js",))
    try:
        await engine._run_conversation([Message.user("Hello")], "test", "sys", None)
        assert not {"finish_task", "request_task_tools"} & names(client.requests[0])
    finally:
        await engine.shutdown_session()
