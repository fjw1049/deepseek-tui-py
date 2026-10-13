"""Browser help pauses the existing turn and resumes only on explicit decisions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.client.base import LLMClient
from deepseek_tui.server.threads.manager import RuntimeThreadManager


class NoSecondaryRequests(LLMClient):
    async def stream_chat_completion(self, request):
        raise AssertionError("Only the primary model should be called")
        yield


@pytest.fixture
def help_task(tmp_path):
    manager = RuntimeThreadManager.__new__(RuntimeThreadManager)
    manager.browser_service = BrowserService(tmp_path)
    handle = EngineHandle()
    handle._mark_turn_active()
    manager._active = {
        "one": SimpleNamespace(handle=handle, active_turn=SimpleNamespace(turn_id="turn"))
    }
    session = SimpleNamespace(
        dom_tree=AsyncMock(
            return_value=SimpleNamespace(success=True, content="Login still required", error=None)
        ),
        _internal=SimpleNamespace(client=SimpleNamespace(send=AsyncMock(return_value={}))),
    )
    run = BrowserRun("one", tmp_path / "profile", session=session, url="https://example.test")
    async def cdp(method, params=None):
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 1}
        if method == "Runtime.evaluate":
            return {"result": {"value": {"url": run.url, "title": "Login",
                    "text": "Login still required", "elements": [], "warnings": [],
                    "viewport": {"width": 1200, "height": 760}, "truncated": False}}}
        return {"frameTree": {"frame": {"id": "tab", "loaderId": "doc", "url": run.url}}}
    session._internal.client.send.side_effect = cdp
    manager.browser_service.runs["one"] = run
    return manager, run, handle


@pytest.mark.asyncio
async def test_takeover_continue_preserves_turn_and_requires_verification(help_task):
    manager, run, handle = help_task
    await manager.request_browser_assistance("one", "Please log in")
    request = run.assistance.copy()
    assert handle.pause.paused
    assert manager.pending_browser_assistance()[0]["id"] == request["id"]
    with pytest.raises(ValueError, match="Waiting"):
        await manager.browser_service.action("one", BrowserAction(action="reload"))
    with pytest.raises(ValueError, match="Take control"):
        await manager.respond_browser_assistance("one", request["id"], "continue")
    await manager.respond_browser_assistance("one", request["id"], "takeover")
    assert run.owner == "user" and run.assistance["status"] == "human"
    assert handle.pause.paused
    await manager.respond_browser_assistance("one", request["id"], "continue")
    assert not handle.pause.paused and run.owner == "agent" and run.assistance is None
    assert "NOT guaranteed" in handle.resume_context
    assert "within its authorization" in handle.resume_context
    assert "Login still required" in handle.resume_context
    assert handle._op_queue.empty()
    with pytest.raises(ValueError, match="ended"):
        await manager.respond_browser_assistance("one", request["id"], "takeover")


@pytest.mark.asyncio
async def test_ignore_returns_decision_to_model_without_classifying_next_request(help_task):
    manager, run, handle = help_task
    await manager.request_browser_assistance("one", "Optional login")
    await manager.respond_browser_assistance("one", run.assistance["id"], "ignore")
    assert "Do not skip" in handle.resume_context
    assert "without new evidence" in handle.resume_context
    assert "original authorization" in handle.resume_context
    assert not handle.pause.paused
    # The model, not reason-string matching, decides whether new evidence warrants help.
    assert (await manager.request_browser_assistance("one", "Optional login"))["success"]


@pytest.mark.asyncio
async def test_failed_observation_resumes_with_explicit_recovery_requirement(help_task):
    manager, run, handle = help_task
    await manager.request_browser_assistance("one", "Verify")
    request_id = run.assistance["id"]
    await manager.respond_browser_assistance("one", request_id, "takeover")
    run.session._internal.client.send.side_effect = ConnectionError("Disconnected")
    await manager.respond_browser_assistance("one", request_id, "continue")
    assert not handle.pause.paused and run.owner == "agent" and run.assistance is None
    assert run.latest_observation is None
    assert '"status": "unavailable"' in handle.resume_context
    assert "recover and observe" in handle.resume_context


@pytest.mark.asyncio
async def test_information_and_stale_cancelled_requests(help_task):
    manager, run, handle = help_task
    await manager.request_browser_assistance("one", "Which account?")
    request_id = run.assistance["id"]
    with pytest.raises(ValueError, match="additional"):
        await manager.respond_browser_assistance("one", request_id, "information", " ")
    run.session._internal.client.send.side_effect = ConnectionError("Disconnected")
    await manager.respond_browser_assistance(
        "one", request_id, "information", "Use the public link"
    )
    assert not handle.pause.paused
    assert handle.drain_steers() == ["Use the public link"]
    assert "No manual handoff" in handle.resume_context
    await manager.request_browser_assistance("one", "New obstacle")
    handle.cancel_event.set()
    with pytest.raises(ValueError, match="ended"):
        await manager.respond_browser_assistance("one", run.assistance["id"], "ignore")
    manager._active["one"].active_turn = None
    assert manager.pending_browser_assistance() == []
    assert run.assistance is None


@pytest.mark.asyncio
async def test_tool_routes_assistance_to_task_pause(help_task):
    import json

    from deepseek_tui.tools.browser import BrowserUseTool

    manager, run, handle = help_task
    context = SimpleNamespace(
        metadata={
            "browser_service": manager.browser_service,
            "runtime_thread_id": "one",
            "request_browser_assistance": manager.request_browser_assistance,
        }
    )
    result = await BrowserUseTool().execute(
        {"action": "request_assistance", "reason": "Please verify"}, context
    )
    assert result.success and handle.pause.paused
    assert json.loads(result.content)["success"]
    assert run.assistance["reason"] == "Please verify"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://www.google.com/sorry/index",
    "https://example.test/login",
    "https://example.test/unfamiliar-device-confirmation",
])
async def test_page_evidence_alone_does_not_trigger_assistance(help_task, url):
    manager, run, handle = help_task
    run.url = url
    run.session._internal.client.send.return_value = {"frameTree": {"frame": {"url": url}}}
    await manager.browser_service.action("one", BrowserAction(action="status"))
    await manager.browser_service.action("one", BrowserAction(action="observe", level="full"))
    assert run.assistance is None and not handle.pause.paused
    await manager.request_browser_assistance("one", "This step requires your confirmation")
    assert handle.pause.paused and run.assistance is not None


@pytest.mark.asyncio
async def test_engine_fences_bing_until_explicit_user_decision(help_task, tmp_path):
    """Actual engine + tool + service + pause; only model and CDP transport are fake."""
    import asyncio

    from deepseek_tui.config.models import Config, FeatureConfig
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.engine.turn import TurnResult
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import ToolCall

    manager, run, handle = help_task
    run.url = "about:blank"

    async def navigate(url):
        run.url = "https://www.google.com/sorry/index" if "google" in url else url
        return SimpleNamespace(success=True, content="Page opened", error=None)

    run.session.navigate = AsyncMock(side_effect=navigate)
    engine = await Engine.create(
        handle=handle,
        client=NoSecondaryRequests(),
        working_directory=tmp_path,
        config=Config(
            features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False)
        ),
        start_mcp=False,
    )
    engine.tool_context.metadata.update(
        browser_service=manager.browser_service, runtime_thread_id="one",
        request_browser_assistance=manager.request_browser_assistance,
    )
    engine._handle_approval_flow = AsyncMock(return_value=False)
    requests = []

    async def model(request, *args, **kwargs):
        requests.append(request)
        if len(requests) == 1:
            return TurnResult(
                assistant_message=None,
                tool_calls=[
                    ToolCall(
                        id="help",
                        name="browser_use",
                        arguments={
                            "action": "request_assistance",
                            "reason": "Please complete human verification on the page",
                        },
                    ),
                    ToolCall(
                        id="bing-stale",
                        name="browser_use",
                        arguments={
                            "action": "open",
                            "url": "https://www.bing.com/search?q=trending",
                        },
                    ),
                ],
            )
        return TurnResult(assistant_message=Message.assistant("Continuing after the user's choice"))

    engine.turn_loop.run = model
    task = asyncio.create_task(
        engine._run_conversation(
            [Message.user("Find trending searches")],
            "deepseek-chat",
            "sys",
            None,
        )
    )
    try:
        await asyncio.wait_for(handle.pause.requested.wait(), 3)
        await asyncio.sleep(0.03)
        assert not task.done() and len(requests) == 1
        assert run.session.navigate.await_count == 0
        assert manager.pending_browser_assistance()[0]["id"] == run.assistance["id"]
        await manager.respond_browser_assistance("one", run.assistance["id"], "ignore")
        await asyncio.wait_for(task, 3)
        assert run.session.navigate.await_count == 0  # queued Bing action was discarded
        assert len(requests) == 3
        assert any("Do not skip" in m.text_content() for m in requests[1].messages)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.shutdown_session()


async def test_information_reaches_primary_model_in_active_engine(help_task, tmp_path):
    import json

    from deepseek_tui.config.models import Config, FeatureConfig
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.engine.turn import TurnResult
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import ToolCall

    manager, run, handle = help_task
    requests = []

    engine = await Engine.create(handle=handle, client=NoSecondaryRequests(), working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False)), start_mcp=False)
    engine.tool_context.metadata.update(browser_service=manager.browser_service,
                                        runtime_thread_id="one")
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)
    engine._handle_shell_process_turn_handoff = AsyncMock(return_value=False)
    calls = iter([
        TurnResult(assistant_message=None, tool_calls=[ToolCall(
            id="help", name="browser_use", arguments={"action": "request_assistance"})]),
        TurnResult(assistant_message=None, tool_calls=[ToolCall(
            id="read", name="browser_use", arguments={"action": "observe"})]),
        TurnResult(assistant_message=Message.assistant("川沙测试店评分4.8。")),
    ])

    async def primary(request, *args, **kwargs):
        requests.append(request)
        return next(calls)

    async def execute(tool_calls, model):
        if tool_calls[0].id == "help":
            await manager.request_browser_assistance("one", "请提供地区")
            await manager.respond_browser_assistance(
                "one", run.assistance["id"], "information", "我在川沙")
            return [Message.tool_result("help", '{"success":true}')]
        return [Message.tool_result("read", json.dumps({
            "receipt": {"action_id": "read1", "execution": "executed"},
            "observation": {"observation_id": "o1", "text": "川沙测试店评分4.8"}}))]

    engine.turn_loop.run = primary
    engine._execute_tool_calls = execute
    try:
        result = await engine._run_conversation(
            [Message.user("用浏览器推荐附近店")], "test", "sys", None)
        assert result.assistant_message.text_content() == "川沙测试店评分4.8。"
        assert any("我在川沙" in m.text_content() for m in requests[-1].messages)
    finally:
        await engine.shutdown_session()


async def test_handoff_reports_sampled_changes_without_claiming_user_actions(help_task):
    import json
    manager, run, handle = help_task
    await manager.browser_service.action("one", BrowserAction(action="observe"))
    await manager.request_browser_assistance("one", "Please log in")
    request_id = run.assistance["id"]
    await manager.respond_browser_assistance("one", request_id, "takeover")
    run.url = "https://example.test/orders"
    run.unresolved["old-submit"] = {"effect": "unknown"}
    await manager.respond_browser_assistance("one", request_id, "continue")
    report = json.loads(handle.resume_context.split("Resume reconciliation:\n")[1].split("\nFresh browser observation:")[0])
    assert report["status"] == "compared"
    assert report["changes"]["url"]["after"].endswith("/orders")
    assert report["unresolved_action_ids"] == ["old-submit"]
    assert "outcomes remain unknown" in report["limits"]
    assert run.handoff_baseline is None


def test_handoff_detects_checkbox_change_without_retaining_input_values():
    import json
    from deepseek_tui.browser.handoff import baseline, resume_context
    before = {"observation_id": "old", "tab_id": "t", "document_id": "d", "text": "Notify",
              "elements": [{"selector": "#notify", "checked": False, "value": "SECRET"}]}
    after = {**before, "observation_id": "new", "elements": [{"selector": "#notify", "checked": True}]}
    saved = baseline(before)
    assert "SECRET" not in json.dumps(saved)
    run = SimpleNamespace(handoff_baseline=saved, assistance=None, unresolved={})
    result = resume_context(run, {"success": True, "observation": after}, "Returned")
    report = json.loads(result.split("Resume reconciliation:\n")[1].split("\nFresh browser observation:")[0])
    assert report["sampled_controls_changed"] is True
    assert report["visible_text_changed"] is False
