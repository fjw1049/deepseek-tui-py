"""Browser module: actions, isolation, takeover, recording and tool approvals."""

import asyncio
import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import ValidationError

from deepseek_tui.browser import BrowserAction, BrowserRun, BrowserService
from deepseek_tui.tools.approval import build_approval_key
from deepseek_tui.tools.browser import BrowserUseTool
from deepseek_tui.tools.registry import ApprovalRequirement, ToolContext


def fake_session():
    output = io.BytesIO()
    Image.new("RGB", (1200, 760), "white").save(output, format="JPEG")
    result = SimpleNamespace(success=True, content="done", error=None)
    return SimpleNamespace(
        navigate=AsyncMock(return_value=result),
        click=AsyncMock(return_value=result),
        fill=AsyncMock(return_value=result),
        select=AsyncMock(return_value=result),
        press=AsyncMock(return_value=result),
        scroll=AsyncMock(return_value=result),
        dom_tree=AsyncMock(return_value=result),
        eval_js=AsyncMock(return_value=SimpleNamespace(success=True, content='"Saved"')),
        close=AsyncMock(),
        _internal=SimpleNamespace(
            client=SimpleNamespace(
                send=AsyncMock(return_value={"data": base64.b64encode(output.getvalue()).decode()})
            )
        ),
    )


@pytest.fixture
def browser(tmp_path):
    service = BrowserService(tmp_path / "artifacts")
    for name in ("one", "two"):
        directory = tmp_path / name
        directory.mkdir()
        service.runs[name] = BrowserRun(name, directory, session=fake_session())
    return service


@pytest.mark.asyncio
async def test_action_evidence_and_recording_module(browser):
    scope = browser.approval_scope("one")
    await browser.action("one", BrowserAction(action="record_start"))
    await browser.action("one", BrowserAction(action="fill", selector="#name", text="private"))
    result = await browser.action("one", BrowserAction(action="check_text", text="Saved"))
    assert result["success"]
    assert not (await browser.action("one", BrowserAction(action="check_text", text="Missing")))[
        "success"
    ]
    shot = await browser.action("one", BrowserAction(action="screenshot"))
    animation = await browser.action("one", BrowserAction(action="record_stop"))
    assert browser.artifact("one", shot["artifact"]["id"]).is_file()
    with Image.open(animation["artifact"]["path"]) as image:
        assert image.format == "GIF"
    assert "private" not in str(browser.state("one")["log"])
    assert browser.state("two")["log"] == []
    await browser.close("one")
    assert len(browser.state("one")["artifacts"]) == 3
    assert browser.approval_scope("one") != scope
    with pytest.raises(ValueError):
        browser.artifact("two", shot["artifact"]["id"])
    with pytest.raises(ValueError):
        browser.artifact("one", "../escape.jpg")


@pytest.mark.asyncio
async def test_takeover_discards_waiting_agent_action_and_stop_cleans_up(browser):
    run = browser.runs["one"]
    await run.lock.acquire()
    waiting = asyncio.create_task(
        browser.action("one", BrowserAction(action="click", selector="#save"))
    )
    await asyncio.sleep(0)
    takeover = asyncio.create_task(browser.control("one", "user"))
    await asyncio.sleep(0)
    run.lock.release()
    with pytest.raises(ValueError, match="control changed"):
        await waiting
    await takeover
    run.session.click.assert_not_called()
    await browser.action("one", BrowserAction(action="click", selector="#save"), actor="user")
    assert run.session.click.await_count == 1
    await browser.control("one", "stopped")
    run.session.close.assert_awaited_once_with(kill=True)
    assert not run.directory.exists()
    assert not browser.state("one")["active"]
    assert browser.state("two")["active"]


@pytest.mark.asyncio
async def test_failed_actions_and_recording_preserve_evidence(browser):
    run = browser.runs["one"]
    await browser.action("one", BrowserAction(action="record_start"))
    frames = list(run.frames)
    with pytest.raises(ValueError, match="already running"):
        await browser.action("one", BrowserAction(action="record_start"))
    assert run.frames == frames
    run.session.click.side_effect = RuntimeError("page disconnected")
    with pytest.raises(RuntimeError):
        await browser.action("one", BrowserAction(action="click", selector="#save"))
    assert run.log[-1] == {"action": "click", "success": False}
    await browser.close("one")
    saved = browser.state("one")
    assert saved["error"] == "page disconnected"
    assert saved["artifacts"][-1]["id"].endswith(".gif")


@pytest.mark.asyncio
async def test_text_check_waits_for_dynamic_content_and_captures_failure(browser):
    run = browser.runs["one"]
    run.session.eval_js.side_effect = [
        SimpleNamespace(success=True, content='"Loading"'),
        SimpleNamespace(success=True, content='"Saved"'),
        SimpleNamespace(success=False, content="", error="page unavailable"),
    ]
    result = await browser.action(
        "one", BrowserAction(action="check_text", text="Saved", timeout_ms=1000)
    )
    assert result["success"]
    failed = await browser.action("one", BrowserAction(action="check_text", text="Saved"))
    assert not failed["success"]
    assert failed["artifact"]["label"] == "失败现场"
    assert browser.state("one")["error"] == "FAIL: Saved"


@pytest.mark.asyncio
async def test_stop_at_frame_limit_returns_the_saved_animation(browser):
    run = browser.runs["one"]
    await browser.action("one", BrowserAction(action="record_start"))
    run.frames *= 39
    result = await browser.action("one", BrowserAction(action="record_stop"))
    assert result["artifact"]["id"].endswith(".gif")
    assert len(run.artifacts) == 1
    assert not run.recording


@pytest.mark.asyncio
async def test_skill_form_actions_are_idempotent_and_use_the_owned_session(browser):
    session = browser.runs["one"].session
    session.eval_js.return_value = SimpleNamespace(success=True, content="true")
    await browser.action(
        "one", BrowserAction(action="set_checked", selector="#notify", checked=True)
    )
    session.click.assert_not_called()
    await browser.action(
        "one", BrowserAction(action="set_checked", selector="#notify", checked=False)
    )
    session.click.assert_awaited_once_with(selector="#notify")
    await browser.action("one", BrowserAction(action="select", selector="#plan", text="pro"))
    session.select.assert_awaited_once_with(value="pro", selector="#plan", ref=None)


@pytest.mark.asyncio
async def test_workflow_preflight_and_takeover(browser, monkeypatch):
    from deepseek_tui import browser_workflows as flows

    models = pytest.importorskip("octop_browser.record.models")
    doc = models.StepsDocument(
        recordingId="rec_test",
        steps=[models.SemanticStep(id="1", kind="new_tab", url="https://example.com")],
    )
    monkeypatch.setattr(flows, "read_workflow", lambda *args: doc)
    await browser.control("one", "user")
    with pytest.raises(ValueError, match="Unsupported"):
        await flows.start_replay(browser, "one", "rec_test", {})
    browser.runs["one"].session.navigate.assert_not_called()
    doc.steps = [models.SemanticStep(id="1", kind="fill", value="{{password}}")]
    with pytest.raises(ValueError, match="Missing"):
        await flows.start_replay(browser, "one", "rec_test", {})
    doc.steps = [models.SemanticStep(id=str(i), kind="press", key="Enter") for i in range(4)]
    await flows.start_replay(browser, "one", "rec_test", {})
    await asyncio.sleep(0.05)
    await browser.control("one", "user")
    assert browser.state("one")["demo_status"] == "stopped"
    assert browser.runs["one"].session.press.await_count < 4
    assert browser.state("two")["log"] == []


def test_profile_preferences_require_closed_session_and_survive_restart(browser):
    with pytest.raises(ValueError, match="End"):
        browser.configure("one", True)
    with pytest.raises(ValueError, match="End"):
        browser.clear_profile("one")
    browser.configure("saved", True)
    restarted = BrowserService(browser.artifact_root)
    assert restarted.preferences("saved") == {"persistent": True}
    assert restarted.preferences("other") == {"persistent": False}


@pytest.mark.asyncio
async def test_recover_restarts_after_disconnect(browser, monkeypatch):
    run = browser.runs["one"]
    run.session.close.side_effect = ConnectionError("disconnected")
    replacement = BrowserRun("one", run.directory, session=fake_session())

    async def ensure(thread_id):
        browser.runs[thread_id] = replacement
        return replacement

    monkeypatch.setattr(browser, "ensure", ensure)
    state = await browser.recover("one")
    assert state["active"] and state["owner"] == "user"
    assert browser.runs["two"].owner == "agent"


@pytest.mark.parametrize(
    "value",
    [
        {"action": "open", "url": "file:///etc/passwd"},
        {"action": "open", "url": "javascript:alert(1)"},
        {"action": "open", "url": "https://user:password@example.com"},
        {"action": "check_text", "text": ""},
        {"action": "click", "x": 1300, "y": 1},
        {"action": "fill", "text": "no target"},
        {"action": "eval_js", "text": "alert(1)"},
    ],
)
def test_invalid_actions(value):
    with pytest.raises(ValidationError):
        BrowserAction.model_validate(value)


@pytest.mark.asyncio
async def test_tool_uses_thread_session_and_scoped_approval(browser, tmp_path):
    tool = BrowserUseTool()
    context = ToolContext(
        working_directory=tmp_path,
        metadata={"browser_service": browser, "runtime_thread_id": "one"},
    )
    result = await tool.execute({"action": "check_text", "text": "Saved"}, context)
    assert result.success
    assert tool.approval_requirement_for_input({"action": "click"}) == ApprovalRequirement.REQUIRED
    assert not tool.supports_parallel()
    a = build_approval_key("browser_use", {"action": "click", "selector": "#save"})
    b = build_approval_key("browser_use", {"action": "click", "selector": "#delete"})
    assert a != b
    await browser.control("one", "user")
    assert not (await tool.execute({"action": "click", "selector": "#save"}, context)).success


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_real_octop_demo(tmp_path):
    """Explicit opt-in; runs real local Chromium, never a model or external website."""
    import os

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    service = BrowserService(tmp_path / "artifacts")
    try:
        await service.start_demo("demo")
        await asyncio.wait_for(service.runs["demo"].demo_task, timeout=60)
        state = service.state("demo")
        assert state["demo_status"] == "passed", state
        assert state["demo_step"] == state["demo_total"] == 9
        assert len(state["artifacts"]) == 2
        assert (await service.frame("demo")).startswith("data:image/jpeg;base64,")
        await service.control("demo", "user")
        result = await service.action(
            "demo", BrowserAction(action="fill", selector="#name", text="人工接管"), actor="user"
        )
        assert result["success"]
    finally:
        await service.close_all()


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_real_record_replay_and_persistent_profile(tmp_path):
    import json
    import os
    from pathlib import Path

    from deepseek_tui import browser as browser_module
    from deepseek_tui.browser_workflows import (
        finish_recording,
        read_workflow,
        start_recording,
        start_replay,
    )

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    service = BrowserService(tmp_path / "artifacts")
    url = (Path(browser_module.__file__).parent / "browser_demo.html").as_uri()
    service.configure("flow", True)
    assert service.environment()["ready"]
    try:
        run = await service.ensure("flow")
        await run.session.navigate(url)
        await service.control("flow", "user")
        await start_recording(service, "flow")
        await run.session.navigate(url)
        await service.action(
            "flow", BrowserAction(action="fill", selector="#name", text="first"), actor="user"
        )
        await service.action(
            "flow", BrowserAction(action="click", selector="#notifications"), actor="user"
        )
        await service.action("flow", BrowserAction(action="click", selector="#save"), actor="user")
        await asyncio.sleep(0.5)
        result = await finish_recording(run)
        doc = read_workflow(service, "flow", result["recordingId"])
        assert any(step.kind == "fill" for step in doc.steps)
        assert all("example" not in item for item in doc.inputs)
        await start_replay(
            service,
            "flow",
            result["recordingId"],
            {item["name"]: "replayed" for item in doc.inputs},
        )
        await asyncio.wait_for(run.demo_task, timeout=60)
        assert service.state("flow")["demo_status"] == "passed", service.state("flow")
        check = await service.action(
            "flow", BrowserAction(action="check_text", text="已保存：replayed")
        )
        assert check["success"]
        await run.session.eval_js("localStorage.setItem('workbench-profile-test','retained')")
        await service.close("flow")
        service = BrowserService(tmp_path / "artifacts")
        run = await service.ensure("flow")
        await run.session.navigate(url)
        stored = await run.session.eval_js("localStorage.getItem('workbench-profile-test')")
        assert json.loads(stored.content) == "retained"
        await service.close("flow")
        service.clear_profile("flow")
        run = await service.ensure("flow")
        await run.session.navigate(url)
        cleared = await run.session.eval_js("localStorage.getItem('workbench-profile-test')")
        assert json.loads(cleared.content) is None
    finally:
        await service.close_all()
