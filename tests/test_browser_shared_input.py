"""Shared viewport input is ordered, fenced by ownership, and private."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from deepseek_tui.browser.input import BrowserInput, key_event
from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService


@pytest.fixture
def shared(tmp_path):
    browser = BrowserService(tmp_path)
    client = SimpleNamespace(send=AsyncMock(return_value={}))
    run = BrowserRun(
        "one",
        tmp_path / "profile",
        session=SimpleNamespace(_internal=SimpleNamespace(client=client)),
        owner="user",
    )
    browser.runs["one"] = run
    return browser, run, client


async def test_same_generation_navigation_rejects_old_scene_and_releases_keys(shared):
    browser, run, client = shared
    frame = {"id": "tab", "loaderId": "before", "url": "https://example.test/one"}

    async def send(method, params=None):
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": frame}}
        return {}

    client.send.side_effect = send
    scene = await browser._scene(run)
    await browser.input("one", BrowserInput(kind="key", event="keyDown", key="Shift",
        code="ShiftLeft", generation=0, scene_id=scene["scene_id"]))
    frame.update(loaderId="after", url="https://example.test/two")
    with pytest.raises(ValueError, match="page changed"):
        await browser.input("one", BrowserInput(kind="text", text="STALE_TEXT",
            generation=0, scene_id=scene["scene_id"]))
    assert not run.pressed_keys
    assert any(call.args[0] == "Input.dispatchKeyEvent" and call.args[1]["type"] == "keyUp"
               for call in client.send.await_args_list)
    assert not any(call.args[0] == "Input.insertText" for call in client.send.await_args_list)


@pytest.mark.asyncio
async def test_input_ownership_generation_and_private_text(shared):
    browser, run, client = shared
    body = BrowserInput(kind="text", text="中文 private", generation=0)
    await browser.input("one", body)
    client.send.assert_awaited_once_with("Input.insertText", {"text": "中文 private"})
    assert "private" not in json.dumps(browser.state("one"))
    await browser.control("one", "agent")
    with pytest.raises(ValueError, match="control changed"):
        await browser.input("one", body)
    await browser.control("one", "user")
    with pytest.raises(ValueError, match="control changed"):
        await browser.input("one", body)
    assert client.send.await_count == 1


@pytest.mark.asyncio
async def test_manual_key_and_text_events_do_not_duplicate_printable_input(shared):
    browser, run, client = shared
    for body in [
        BrowserInput(kind="key", event="keyDown", key="a", code="KeyA", generation=0),
        BrowserInput(kind="text", text="a", generation=0),
        BrowserInput(kind="key", event="keyUp", key="a", code="KeyA", generation=0),
    ]:
        await browser.input("one", body)
    calls = client.send.await_args_list
    assert [call.args[0] for call in calls] == [
        "Input.dispatchKeyEvent",
        "Input.insertText",
        "Input.dispatchKeyEvent",
    ]
    assert calls[0].args[1]["type"] == "rawKeyDown" and "text" not in calls[0].args[1]
    assert calls[2].args[1]["type"] == "keyUp" and "text" not in calls[2].args[1]


@pytest.mark.parametrize("chord", ["Ctrl+a", "Meta+A", "Ctrl++", "Alt+Shift+1"])
def test_shortcuts_never_emit_printable_text(chord):
    event = key_event(chord)
    assert event.text == "" and event.modifiers & 7


@pytest.mark.asyncio
async def test_transfer_waits_for_atomic_action_and_discards_queued_input(shared):
    browser, run, client = shared
    await run.lock.acquire()
    transfer = asyncio.create_task(browser.control("one", "agent"))
    await asyncio.sleep(0)
    assert browser.state("one")["transferring"]
    queued = asyncio.create_task(
        browser.input("one", BrowserInput(kind="text", text="stale", generation=0))
    )
    run.lock.release()
    await transfer
    with pytest.raises(ValueError):
        await queued
    assert not browser.state("one")["transferring"]
    client.send.assert_not_called()


@pytest.mark.asyncio
async def test_resize_pointer_and_key_dispatch(shared):
    browser, run, client = shared
    await browser.input("one", BrowserInput(kind="resize", width=600, height=400, generation=0))
    assert (run.width, run.height) == (600, 400)
    with pytest.raises(ValueError, match="outside"):
        await browser.input(
            "one", BrowserInput(kind="mouse", event="mousePressed", x=601, generation=0)
        )
    await browser.input("one", BrowserInput(kind="wheel", x=50, y=80, delta_y=300, generation=0))
    assert client.send.call_args.args[1]["type"] == "mouseWheel"
    await browser.input(
        "one", BrowserInput(kind="key", event="keyDown", key="Tab", key_code=9, generation=0)
    )
    assert client.send.call_args.args[1]["windowsVirtualKeyCode"] == 9
    with pytest.raises(ValidationError):
        BrowserInput(kind="mouse", event="keyDown", generation=0)


@pytest.mark.asyncio
async def test_cut_requires_the_selection_already_copied_and_video_keeps_dimensions(shared):
    browser, run, client = shared
    client.send.return_value = {"result": {"value": "selected"}}
    with pytest.raises(ValueError, match="Selection changed"):
        await browser.input("one", BrowserInput(kind="cut", text="old selection", generation=0))
    assert client.send.await_count == 1
    run.video = object()
    with pytest.raises(ValueError, match="Finish video"):
        await browser.input("one", BrowserInput(kind="resize", width=600, height=400, generation=0))
    assert (run.width, run.height) == (1200, 760)


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_real_shared_browser_handoff_and_direct_input(tmp_path):
    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    browser = BrowserService(tmp_path / "artifacts")
    page = tmp_path / "input.html"
    page.write_text(
        '<input id="name"><textarea id="note"></textarea><div style="height:2000px">Reading</div>'
    )
    try:
        run = await browser.ensure("one")
        await run.session.navigate(page.as_uri())
        await browser.control("one", "user")
        generation = run.generation
        await browser.input(
            "one", BrowserInput(kind="resize", width=800, height=600, generation=generation)
        )
        await browser.action("one", BrowserAction(action="click", selector="#name"), actor="user")
        await browser.input(
            "one", BrowserInput(kind="text", text="中文粘贴 ✓", generation=generation)
        )
        result = await run.session.eval_js('document.querySelector("#name").value')
        assert json.loads(result.content) == "中文粘贴 ✓"
        await browser.input(
            "one",
            BrowserInput(
                kind="key",
                event="keyDown",
                key="Tab",
                code="Tab",
                key_code=9,
                generation=generation,
            ),
        )
        await browser.input(
            "one",
            BrowserInput(
                kind="key", event="keyUp", key="Tab", code="Tab", key_code=9, generation=generation
            ),
        )
        await browser.input(
            "one", BrowserInput(kind="text", text="保留我的草稿", generation=generation)
        )
        assert (
            json.loads((await run.session.eval_js('document.querySelector("#note").value')).content)
            == "保留我的草稿"
        )
        await browser.input(
            "one",
            BrowserInput(
                kind="key",
                event="keyDown",
                key="Enter",
                code="Enter",
                key_code=13,
                generation=generation,
            ),
        )
        await browser.input(
            "one",
            BrowserInput(
                kind="key",
                event="keyUp",
                key="Enter",
                code="Enter",
                key_code=13,
                generation=generation,
            ),
        )
        assert json.loads(
            (await run.session.eval_js('document.querySelector("#note").value')).content
        ).endswith("\n")
        await browser.action(
            "one", BrowserAction(action="fill", selector="#note", text="保留我的草稿"), actor="user"
        )
        view = await browser.view("one")
        assert view["image"].startswith("data:image/jpeg;base64,")
        assert view["tabs"] and view["viewport"] == {"width": 800, "height": 600}
        first = next(tab["tab_id"] for tab in view["tabs"] if tab["active"])
        assert (await browser.action("one", BrowserAction(action="new_tab"), actor="user"))[
            "success"
        ]
        view = await browser.view("one")
        import base64
        import io

        from PIL import Image

        with Image.open(io.BytesIO(base64.b64decode(view["image"].split(",", 1)[1]))) as frame:
            assert frame.size == (800, 600)
        second = next(tab["tab_id"] for tab in view["tabs"] if tab["active"])
        assert second != first
        assert (
            await browser.action(
                "one", BrowserAction(action="close_tab", tab_id=second), actor="user"
            )
        )["success"]
        assert (
            json.loads((await run.session.eval_js('document.querySelector("#note").value')).content)
            == "保留我的草稿"
        )
        await browser.control("one", "agent")
        with pytest.raises(ValueError):
            await browser.input(
                "one", BrowserInput(kind="text", text="stale", generation=generation)
            )
        assert (await browser.action("one", BrowserAction(action="observe")))["success"]
        assert not any("草稿" in str(entry) for entry in run.log)
    finally:
        await browser.close_all()


@pytest.mark.asyncio
async def test_element_pick_is_fenced_and_does_not_click_or_log_content(shared):
    browser, run, client = shared
    client.send.return_value = {
        "result": {
            "value": {
                "url": "http://localhost/test.html",
                "pick": {"selector": "#save", "textPreview": "private"},
            }
        }
    }
    result = await browser.input("one", BrowserInput(kind="pick", x=10, y=20, generation=0))
    assert result["pick"]["selector"] == "#save"
    assert client.send.call_args.args[0] == "Runtime.evaluate"
    assert "private" not in json.dumps(browser.state("one"))
    with pytest.raises(ValueError, match="outside"):
        await browser.input("one", BrowserInput(kind="pick", x=1300, generation=0))
    await browser.control("one", "agent")
    with pytest.raises(ValueError, match="control changed"):
        await browser.input("one", BrowserInput(kind="pick", generation=0))


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_real_picker_and_devtools_share_current_tab(tmp_path):
    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    browser = BrowserService(tmp_path / "artifacts")
    page = tmp_path / "preview.html"
    page.write_text('<button id="save" onclick="this.textContent=\'clicked\'">Save draft</button>')
    try:
        run = await browser.ensure("one")
        await run.session.navigate(page.as_uri())
        await browser.control("one", "user")
        result = await browser.input(
            "one", BrowserInput(kind="pick", x=30, y=15, generation=run.generation)
        )
        assert result["pick"]["selector"] == "button#save"
        assert result["pick"]["textPreview"] == "Save draft"
        assert result["url"] == page.as_uri()
        check = await run.session.eval_js('document.querySelector("#save").textContent')
        assert json.loads(check.content) == "Save draft"
        devtools = await browser.input(
            "one", BrowserInput(kind="devtools", generation=run.generation)
        )
        target = await run.session._internal.client.send("Target.getTargetInfo", {})
        assert devtools["url"].endswith("/devtools/page/" + target["targetInfo"]["targetId"])
    finally:
        await browser.close("one")


async def test_manual_input_capture_failure_does_not_report_input_failure(shared, monkeypatch):
    browser, run, client = shared
    run.recording = True
    monkeypatch.setattr(browser, "_capture", AsyncMock(side_effect=RuntimeError("capture unavailable")))
    result = await browser.input("one", BrowserInput(kind="text", text="draft", generation=0))
    assert result["success"] and result["evidence_warning"]
    client.send.assert_awaited_once_with("Input.insertText", {"text": "draft"})
    assert not run.recording


async def test_view_distinguishes_busy_from_changed_frame(shared, monkeypatch):
    browser, run, _ = shared
    async with run.lock:
        view = await browser.view("one")
    assert view["frame_status"] == "busy" and view["image"] is None
    scene = {"scene_id": "before", "url": "https://example.test"}
    monkeypatch.setattr(browser, "_scene", AsyncMock(side_effect=[scene, scene]))
    monkeypatch.setattr(browser, "_capture", AsyncMock(return_value=b"jpeg"))
    monkeypatch.setattr(browser, "page_state", AsyncMock())
    view = await browser.view("one")
    assert view["frame_status"] == "ready" and view["image"]
    assert run.url == scene["url"]
    browser.page_state.assert_not_called()
    browser._scene.side_effect = [scene, {**scene, "scene_id": "after"}]
    view = await browser.view("one")
    assert view["frame_status"] == "changed" and view["image"] is None


async def test_view_saves_cookies_only_for_manual_browsing(shared, monkeypatch):
    browser, run, _ = shared
    scene = {"scene_id": "same", "url": "https://example.test"}
    monkeypatch.setattr(browser, "_scene", AsyncMock(return_value=scene))
    monkeypatch.setattr(browser, "_capture", AsyncMock(return_value=b"jpeg"))
    monkeypatch.setattr(browser, "save_cookies", AsyncMock())
    run.owner = "agent"
    await browser.view("one")
    browser.save_cookies.assert_not_called()
    run.owner = "user"
    await browser.view("one")
    browser.save_cookies.assert_awaited_once()


class StreamClient:
    """CDP page client that repaints only when the test says so."""

    def __init__(self, frame):
        self.frame, self.listeners, self.sent = frame, {}, []

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def off(self, event, callback):
        self.listeners[event].remove(callback)

    async def send(self, method, params=None):
        self.sent.append(method)
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": self.frame}}
        if method == "Page.captureScreenshot":
            return {"data": "Y2FwdHVyZQ=="}
        return {}

    async def paint(self, data):
        for callback in list(self.listeners.get("Page.screencastFrame", [])):
            await callback({"data": data, "sessionId": 1})


async def test_view_serves_streamed_frames_only_between_equal_scenes(tmp_path):
    browser = BrowserService(tmp_path)
    frame = {"id": "tab", "loaderId": "doc", "url": "https://example.test"}
    client = StreamClient(frame)
    run = BrowserRun("one", tmp_path / "profile", owner="user",
                     session=SimpleNamespace(_internal=SimpleNamespace(client=client)))
    browser.runs["one"] = run
    captured = "data:image/jpeg;base64,Y2FwdHVyZQ=="
    assert (await browser.view("one"))["image"] == captured
    assert client.sent.count("Page.startScreencast") == 1
    # Nothing repainted: the bound image is served again without a capture.
    assert (await browser.view("one"))["image"] == captured
    assert client.sent.count("Page.captureScreenshot") == 1
    await client.paint("c3RyZWFt")
    assert (await browser.view("one"))["image"].endswith(",c3RyZWFt")
    assert "Page.screencastFrameAck" in client.sent
    # A frame painted before a new document is never served for it.
    await client.paint("b2xk")
    frame["loaderId"] = "next"
    assert (await browser.view("one"))["image"] == captured
    assert client.sent.count("Page.captureScreenshot") == 2
    # Once the viewer leaves, the next repaint stops the stream.
    run.last_view_at -= 10
    await client.paint("bGF0ZQ==")
    assert client.sent[-1] == "Page.stopScreencast" and run.screencast_client is None
    assert not client.listeners["Page.screencastFrame"]


async def test_manual_text_persists_receipt_once(shared, monkeypatch):
    from unittest.mock import Mock
    browser, _, _ = shared
    persist = Mock()
    monkeypatch.setattr(browser, "_persist", persist)
    result = await browser.input("one", BrowserInput(kind="text", text="test", generation=0))
    persist.assert_called_once()
    assert result["receipt"]["execution"] == "executed"
    persist.side_effect = OSError("disk full")
    result = await browser.input("one", BrowserInput(kind="text", text="test", generation=0))
    assert result["success"] and result["receipt"]["evidence"] == "unavailable"

async def test_unresolved_result_allows_scroll_but_blocks_click_and_typing(shared):
    browser, run, client = shared
    run.unresolved['pending'] = {'action_id': 'pending', 'execution': 'unknown'}
    await browser.input('one', BrowserInput(kind='wheel', x=50, y=80, delta_y=300, generation=0))
    assert client.send.call_args.args[1]['type'] == 'mouseWheel'
    for body in [BrowserInput(kind='mouse', event='mousePressed', x=50, y=80, generation=0),
                 BrowserInput(kind='text', text='do not send', generation=0)]:
        with pytest.raises(ValueError, match='outcome is unknown'):
            await browser.input('one', body)
    assert 'pending' in run.unresolved


@pytest.mark.parametrize("disconnected", [True, False])
async def test_view_probes_transport_after_scene_failure(shared, monkeypatch, disconnected):
    browser, run, client = shared
    monkeypatch.setattr(browser, "_stream", AsyncMock())
    monkeypatch.setattr(browser, "_scene", AsyncMock(side_effect=ValueError("Document changed")))
    if disconnected:
        client.send.side_effect = RuntimeError("Connection closed")
        view = await browser.view("one")
        assert not view["active"] and not view["healthy"]
        assert view["image"] is None and "recover" in view["error"]
        assert run.view_sequence == 1
    else:
        with pytest.raises(RuntimeError, match="Browser view unavailable"):
            await browser.view("one")
        assert run.healthy
    client.send.assert_awaited_once_with(
        "Runtime.evaluate", {"expression": "1", "returnByValue": True})
