"""Shared viewport input is ordered, fenced by ownership, and private."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from deepseek_tui.browser.input import BrowserInput
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
