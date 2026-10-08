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
