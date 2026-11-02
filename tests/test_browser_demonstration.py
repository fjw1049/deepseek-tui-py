"""A demonstration in real Chrome, driven by trusted input, must replay what the user did."""

import asyncio
import json
import os

import pytest

from deepseek_tui.browser import workflows
from deepseek_tui.browser.observation import evaluate
from deepseek_tui.browser.service import BrowserAction, BrowserService

PAGES = {
    "/": """<title>start</title><form action=/result>
<input id=q name=q placeholder=search style="width:300px"><button id=go>Go</button></form>
<a id=detail href=/detail>detail</a>""",
    "/result": "<title>result</title><h1>result</h1>",
    "/detail": """<title>detail</title>
<button id=act onclick="this.textContent='done'">act</button>""",
    "/rows": """<title>rows</title><div id=root><div>
<div class=row onclick="this.dataset.hit=1" style="height:60px;cursor:pointer">
<span>first row</span></div>
<div class=row onclick="this.dataset.hit=1" style="height:60px;cursor:pointer">second row</div>
</div></div>""",
    "/controls": """<title>controls</title>
<input id=file type=file style="display:none" onchange="document.title='picked'">
<button id=pick onclick="document.getElementById('file').click()">choose</button>
<label style="display:block;margin-top:20px"><input id=box type=checkbox
 style="position:absolute;opacity:0"><span id=agree>agree</span></label>""",
    "/menu": """<title>menu</title>
<button id=open onclick="document.getElementById('list').style.display='block'">open</button>
<div id=list style="display:none"><div id=option role=option style="height:40px"
 onmousedown="document.title='picked';document.getElementById('list').remove()">pick me</div>
</div>""",
    "/card": """<title>card</title><div id=card style="position:relative;width:400px;height:120px;
cursor:pointer" onclick="document.title='opened'"><span id=close style="position:absolute;top:4px;
right:4px" onclick="event.stopPropagation();document.title='closed'">x</span>card body</div>""",
    "/article": "<title>article</title><div style='height:3000px'>article</div>",
    "/lazy": """<title>lazy</title><div id=list style='height:300px;overflow:auto'>
<div style='height:600px'>rows</div></div><script>
const list=document.getElementById('list');
list.addEventListener('scroll',()=>{
  if(list.scrollTop+list.clientHeight<list.scrollHeight-20||document.getElementById('more'))return;
  const more=document.createElement('button');
  more.id='more';more.textContent='loaded';more.onclick=()=>{document.title='loaded'};
  list.append(more);
})</script>""",
    "/search-scroll": """<title>search</title><input id=q>
<div id=list style='height:300px;overflow:auto'><div style='height:1000px'>results</div></div>
<script>window.searched=[];document.getElementById('list').addEventListener('scroll',()=>{
searched.push(document.getElementById('q').value)})</script>""",
    "/carousel": """<title>carousel</title><div id=track style='height:100px;overflow:auto'>
<div style='height:600px'>slides</div></div><button id=go>go</button>
<script>setInterval(()=>{document.getElementById('track').scrollTop+=40},100)</script>""",
    "/live": """<title>live</title><input id=q><script>
document.getElementById('q').addEventListener('input',
  e=>history.replaceState(null,'','/live?q='+encodeURIComponent(e.target.value)))</script>""",
}


class Demonstrator:
    def __init__(self, run, base):
        self.run, self.base = run, base

    @property
    def client(self):
        return self.run.session._internal.client

    async def click(self, selector):
        x, y = await evaluate(self.client, "(()=>{const r=document.querySelector("
                              + json.dumps(selector) + ").getBoundingClientRect();"
                              "return [r.x+r.width/2,r.y+r.height/2]})()")
        await self.client.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for kind in ("mousePressed", "mouseReleased"):
            await self.client.send("Input.dispatchMouseEvent", {
                "type": kind, "x": x, "y": y, "button": "left", "clickCount": 1,
                "buttons": 1 if kind == "mousePressed" else 0})
        await asyncio.sleep(.15)

    async def wheel(self, down):
        await self.client.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": 200, "y": 100, "deltaX": 0, "deltaY": down})
        await asyncio.sleep(.5)

    async def type(self, text):
        for char in text:
            await self.client.send("Input.dispatchKeyEvent",
                                   {"type": "keyDown", "text": char, "key": char})
            await self.client.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": char})
            await asyncio.sleep(.05)

    async def enter(self):
        keys = {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}
        await self.client.send("Input.dispatchKeyEvent", {"type": "keyDown", "text": "\r", **keys})
        await self.client.send("Input.dispatchKeyEvent", {"type": "keyUp", **keys})
        await asyncio.sleep(.5)


@pytest.fixture
async def browser(tmp_path):
    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 for actual Chrome")

    async def serve(reader, writer):
        try:
            try:
                head = await reader.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError:
                return
            path = head.split(b" ")[1].decode().split("?")[0]
            body = ("<!doctype html><meta charset=utf-8>" + PAGES.get(path, "")).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                         b"Content-Length: " + str(len(body)).encode()
                         + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    service = BrowserService(tmp_path)
    try:
        yield service, f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    finally:
        await service.close_all()
        server.close()
        await server.wait_closed()


async def demonstrate(browser, path, perform):
    service, base = browser
    assert (await service.action("t", BrowserAction(action="open", url=base + path)))["success"]
    run = service.runs["t"]
    await service.control("t", "user")
    recording = (await workflows.start_recording(service, "t"))["recordingId"]
    store = run.recorder.store
    await perform(Demonstrator(run, base))
    await asyncio.sleep(.4)
    async with run.lock:
        await workflows.finish_recording(run)
    return run, store.read_steps(recording), recording


async def replay(browser, run, doc, recording, tmp_path):
    service, _ = browser
    # The page keeps what the demonstration did to it; replay starts where it started.
    await service.action("t", BrowserAction(action="reload", generation=run.generation),
                         actor="user")
    upload = tmp_path / "chosen.txt"
    upload.write_text("chosen")
    await workflows.start_replay(service, "t", recording, {
        item["name"]: json.dumps([str(upload)]) if item.get("kind") == "files" else "hello"
        for item in doc.inputs})
    await asyncio.wait_for(run.demo_task, 40)
    assert (run.demo_status, run.error) == ("passed", None)
    return lambda expression: evaluate(run.session._internal.client, expression)


async def test_typing_and_enter_are_one_fill_and_one_press(browser, tmp_path):
    async def perform(user):
        await user.click("#q")
        await user.type("hello")
        await user.enter()

    run, doc, recording = await demonstrate(browser, "/", perform)
    assert [step.kind for step in doc.steps] == ["open", "fill", "press"]
    assert len(doc.inputs) == 1
    page = await replay(browser, run, doc, recording, tmp_path)
    assert await page("location.pathname+location.search") == "/result?q=hello"


async def test_script_bound_rows_are_steps_on_the_element_observation_lists(browser, tmp_path):
    async def perform(user):
        await user.click(".row span")
        await user.click(".row:nth-of-type(2)")

    run, doc, recording = await demonstrate(browser, "/rows", perform)
    assert [step.kind for step in doc.steps] == ["open", "click", "click"]
    await evaluate(run.session._internal.client, "(()=>{for(const r of "
                   "document.querySelectorAll('.row'))delete r.dataset.hit;return 1})()")
    page = await replay(browser, run, doc, recording, tmp_path)
    hits = "[...document.querySelectorAll('.row')].map(r=>r.dataset.hit).join()"
    assert await page(hits) == "1,1"


async def test_hidden_checkbox_and_file_input_are_recorded_and_replayed(browser, tmp_path):
    async def perform(user):
        await user.client.send("Page.setInterceptFileChooserDialog", {"enabled": True})
        await user.click("#agree")
        await user.click("#pick")
        root = await user.client.send("DOM.getDocument", {})
        node = await user.client.send("DOM.querySelector",
                                      {"nodeId": root["root"]["nodeId"], "selector": "#file"})
        picked = tmp_path / "picked.txt"
        picked.write_text("picked")
        await user.client.send("DOM.setFileInputFiles",
                               {"nodeId": node["nodeId"], "files": [str(picked)]})
        await asyncio.sleep(.2)

    run, doc, recording = await demonstrate(browser, "/controls", perform)
    assert [step.kind for step in doc.steps] == ["open", "set_checked", "click", "upload"]
    page = await replay(browser, run, doc, recording, tmp_path)
    assert await page("document.getElementById('box').checked") is True
    assert await page("document.title") == "picked"


async def test_menu_item_taken_away_on_mousedown_is_recorded_once(browser, tmp_path):
    async def perform(user):
        await user.click("#open")
        await user.click("#option")

    run, doc, recording = await demonstrate(browser, "/menu", perform)
    assert [(step.kind, (step.target or {}).get("name")) for step in doc.steps[1:]] == [
        ("click", "open"), ("click", "pick me")]
    page = await replay(browser, run, doc, recording, tmp_path)
    assert await page("document.title") == "picked"


async def test_back_to_the_start_page_is_replayed(browser, tmp_path):
    async def perform(user):
        await user.click("#detail")
        await asyncio.sleep(.4)
        await user.click("#act")  # This click does not cause the subsequent history navigation.
        await user.client.send("Runtime.evaluate", {"expression": "history.back()"})
        await asyncio.sleep(.5)
        await user.click("#q")
        await user.type("hi")

    run, doc, recording = await demonstrate(browser, "/", perform)
    assert [step.kind for step in doc.steps] == ["open", "click", "click", "open", "fill"]
    page = await replay(browser, run, doc, recording, tmp_path)
    assert await page("location.pathname") == "/"


async def test_live_search_is_a_single_fill_whose_url_comes_from_the_page(browser, tmp_path):
    async def perform(user):
        await user.click("#q")
        await user.type("abc")

    run, doc, recording = await demonstrate(browser, "/live", perform)
    assert [step.kind for step in doc.steps] == ["open", "fill"]
    page = await replay(browser, run, doc, recording, tmp_path)
    assert await page("location.search") == "?q=hello"


async def test_an_icon_on_a_card_is_replayed_as_that_icon(browser, tmp_path):
    async def perform(user):
        await user.click("#close")

    run, doc, recording = await demonstrate(browser, "/card", perform)
    assert [step.kind for step in doc.steps] == ["open", "click"]
    page = await replay(browser, run, doc, recording, tmp_path)
    assert await page("document.title") == "closed"


async def test_reading_a_page_leaves_a_scroll_step_that_replays(browser, tmp_path):
    async def perform(user):
        await user.wheel(1500)

    run, doc, recording = await demonstrate(browser, "/article", perform)
    assert [(step.kind, step.value) for step in doc.steps] == [
        ("open", None), ("scroll_to", "0.000,1500.000")]
    await evaluate(run.session._internal.client, "(()=>{scrollTo(0,0);return 1})()")
    page = await replay(browser, run, doc, recording, tmp_path)
    assert abs(await page("scrollY") - 1500) <= 2


async def test_content_a_panel_loads_on_scroll_is_reached_again(browser, tmp_path):
    async def perform(user):
        await user.wheel(3000)
        await user.wheel(3000)
        await user.click("#more")

    run, doc, recording = await demonstrate(browser, "/lazy", perform)
    assert [step.kind for step in doc.steps] == ["open", "scroll_to", "scroll_to", "click"]
    await evaluate(run.session._internal.client, "(()=>{document.getElementById('more').remove();"
                   "document.getElementById('list').scrollTop=0;document.title='lazy';return 1})()")
    page = await replay(browser, run, doc, recording, tmp_path)
    assert await page("document.title") == "loaded"


async def test_a_page_scrolling_itself_is_not_the_user(browser):
    async def perform(user):
        await asyncio.sleep(.6)
        await user.click("#go")

    _, doc, _ = await demonstrate(browser, "/carousel", perform)
    assert [step.kind for step in doc.steps] == ["open", "click"]


async def test_recording_survives_the_console_reset_of_a_navigation(browser):
    async def perform(user):
        events = user.run.native_events
        client = next(iter(user.run.recorder._clients.values()))
        events.clients.add(client)
        events.console_clients.add(client)
        await events._reset_console(client)
        await user.click("#detail")
        await asyncio.sleep(.4)
        await user.click("#act")

    _, doc, _ = await demonstrate(browser, "/", perform)
    assert [(step.target or {}).get("name") for step in doc.steps[1:]] == ["detail", "act"]


async def test_scroll_down_then_up_keeps_lazy_loaded_content(browser, tmp_path):
    async def perform(user):
        await user.wheel(300)
        await user.wheel(-300)

    run, doc, recording = await demonstrate(browser, '/lazy', perform)
    assert await evaluate(run.session._internal.client, "!!document.getElementById('more')")
    page = await replay(browser, run, doc, recording, tmp_path)
    assert await page("!!document.getElementById('more')")


async def test_edits_around_scrolling_replay_against_the_right_search(browser):
    async def perform(user):
        await user.click("#q")
        await user.type("a")
        await user.wheel(300)
        await user.type("b")

    run, doc, recording = await demonstrate(browser, "/search-scroll", perform)
    assert [step.kind for step in doc.steps] == ["open", "fill", "scroll_to", "fill"]
    service, _ = browser
    await service.action("t", BrowserAction(action="reload", generation=run.generation),
                         actor="user")
    await workflows.start_replay(service, "t", recording, {"q": "first", "q_2": "second"})
    await asyncio.wait_for(run.demo_task, 40)
    assert run.demo_status == "passed", run.error
    assert await evaluate(run.session._internal.client, "searched.includes('first')")
    assert await evaluate(run.session._internal.client, "document.getElementById('q').value") == "second"
