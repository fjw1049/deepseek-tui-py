"""Browser help pauses the existing turn and resumes only on explicit decisions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.server.threads.manager import RuntimeThreadManager


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
    assert not handle.pause.paused
    # The model, not reason-string matching, decides whether new evidence warrants help.
    assert (await manager.request_browser_assistance("one", "Optional login"))["success"]


@pytest.mark.asyncio
async def test_failed_observation_keeps_request_and_pause(help_task):
    manager, run, handle = help_task
    await manager.request_browser_assistance("one", "Verify")
    request_id = run.assistance["id"]
    await manager.respond_browser_assistance("one", request_id, "takeover")
    run.session.dom_tree.side_effect = ConnectionError("Disconnected")
    with pytest.raises(ConnectionError):
        await manager.respond_browser_assistance("one", request_id, "continue")
    assert handle.pause.paused and run.owner == "user" and run.assistance["id"] == request_id


@pytest.mark.asyncio
async def test_information_and_stale_cancelled_requests(help_task):
    manager, run, handle = help_task
    await manager.request_browser_assistance("one", "Which account?")
    request_id = run.assistance["id"]
    with pytest.raises(ValueError, match="additional"):
        await manager.respond_browser_assistance("one", request_id, "information", " ")
    await manager.respond_browser_assistance(
        "one", request_id, "information", "Use the public link"
    )
    assert "Use the public link" in handle.resume_context and not handle.pause.paused
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
    run.session._internal.client.send.side_effect = lambda *args, **kwargs: {
        "frameTree": {"frame": {"url": run.url}}
    }
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
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
        assert len(requests) == 2
        assert any("Do not skip" in m.text_content() for m in requests[1].messages)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.shutdown_session()
