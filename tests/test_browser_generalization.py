"""Common widget patterns, change-only results, real keystrokes, dragging and console reads."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.browser.context import observation_changes, project_result
from deepseek_tui.browser.service import BrowserAction, BrowserService


def observation(elements, text="Orders", **extra):
    return {"observation_id": extra.pop("observation_id", "obs-1"), "tab_id": "t",
            "document_id": "d", "frame_id": "", "level": "interactive", "element_offset": 0,
            "text_offset": 0, "control_generation": 0, "elements": elements, "text": text, **extra}


EDIT = {"ref": "e1", "role": "button", "name": "Edit", "box": {"x": 1}}
DELETE = {"ref": "e2", "role": "button", "name": "Delete", "box": {"x": 2}}


def test_changes_list_only_new_changed_and_removed_elements():
    before = observation([EDIT, DELETE] + [{"ref": f"e{i}", "role": "link", "name": str(i)}
                                           for i in range(3, 9)], text="Orders\nRow 1")
    moved = {**EDIT, "box": {"x": 99}}  # Geometry alone is not a change the model can use.
    confirm = {"ref": "e9", "role": "button", "name": "Confirm delete"}
    after = observation([moved, confirm] + before["elements"][2:], text="Orders\nRow 1\nSure?",
                        observation_id="obs-2")
    changes = observation_changes(before, after)
    assert changes["base"] == "obs-1"
    assert changes["elements"] == [confirm] and changes["removed"] == ["e2"]
    assert changes["unchanged"] == 7 and changes["text"] == ["+ Sure?"]


@pytest.mark.parametrize("field,value", [("document_id", "other"), ("level", "full"),
                                         ("control_generation", 1)])
def test_changes_need_the_same_page_view(field, value):
    before = observation([EDIT])
    assert observation_changes(before, {**observation([EDIT]), field: value}) is None


def test_mostly_changed_page_is_sent_whole():
    before = observation([EDIT, DELETE])
    after = observation([{**EDIT, "name": "Save"}, {**DELETE, "name": "Undo"}])
    assert observation_changes(before, after) is None


def test_projection_keeps_full_snapshot_without_delivered_baseline():
    before = observation([EDIT, DELETE] * 3, text="A\nB")
    after = observation(before["elements"] + [{"ref": "e9", "role": "button", "name": "OK"}],
                        text="A\nB", observation_id="obs-2")
    after["changes"] = observation_changes(before, after)
    data = json.loads(project_result({"success": True, "observation": after}, 10**6))
    seen = data["observation"]
    assert seen["observation_id"] == "obs-2" and "changes_since" not in seen
    assert [e["ref"] for e in seen["elements"]] == [e["ref"] for e in after["elements"]]
    assert seen["text"] == "A\nB" and "text_changes" not in seen
    assert "changes" not in seen


async def test_type_sends_keys_and_commits_other_scripts_as_text():
    from deepseek_tui.browser.input import type_text

    client = SimpleNamespace(send=AsyncMock())
    run = SimpleNamespace(generation=0, session=None)
    await type_text(run, "Ab 中文1", client=client)
    calls = [(c.args[0], c.args[1].get("type"), c.args[1].get("text"))
             for c in client.send.await_args_list]
    assert calls == [
        ("Input.dispatchKeyEvent", "keyDown", "A"), ("Input.dispatchKeyEvent", "keyUp", None),
        ("Input.dispatchKeyEvent", "keyDown", "b"), ("Input.dispatchKeyEvent", "keyUp", None),
        ("Input.dispatchKeyEvent", "keyDown", " "), ("Input.dispatchKeyEvent", "keyUp", None),
        ("Input.insertText", None, "中文"),
        ("Input.dispatchKeyEvent", "keyDown", "1"), ("Input.dispatchKeyEvent", "keyUp", None),
    ]
    client.send.reset_mock()
    await type_text(run, "x" * 301, client=client)
    client.send.assert_awaited_once_with("Input.insertText", {"text": "x" * 301})


@pytest.mark.parametrize("alias,key", [("Esc", "Escape"), ("Return", "Enter"), ("Up", "ArrowUp")])
def test_common_key_names_are_accepted(alias, key):
    from deepseek_tui.browser.input import key_event

    assert key_event(alias).key == key


def test_confirmed_field_changes_count_as_progress():
    from deepseek_tui.engine.ui_progress import UiProgress
    from deepseek_tui.tools.registry import ToolResult

    def fill(progress, call, i):
        browser = {"observation": {"text": "Enter the code"},
                   "receipt": {"action": "fill", "action_id": str(i), "effect": "confirmed"}}
        return progress.record_result("browser_use", ToolResult(
            True, "{}", metadata={"browser": browser, "browser_call": call}))

    progress = UiProgress()
    for i in range(10):  # Field values never appear in page text; the receipts prove change.
        fill(progress, i, i)
    assert progress.blocked_content("browser_use") is None
    # The same fill again and again changes nothing, whatever its receipt says.
    progress = UiProgress()
    for i in range(10):
        fill(progress, "same", i)
    assert progress.blocked_content("browser_use")


async def test_line_breaks_and_tabs_are_typed_as_text_not_keys():
    from deepseek_tui.browser.input import type_text

    client = SimpleNamespace(send=AsyncMock())
    run = SimpleNamespace(generation=0, session=None)
    await type_text(run, "a\tb", client=client)
    calls = [(c.args[0], c.args[1].get("type"), c.args[1].get("text"))
             for c in client.send.await_args_list]
    assert ("Input.insertText", None, "\t") in calls
    assert not any(c[1] == "keyDown" and c[2] == "\t" for c in calls)
    client.send.reset_mock()
    await type_text(run, "line1\nline2", client=client)
    client.send.assert_awaited_once_with("Input.insertText", {"text": "line1\nline2"})


def test_drag_needs_source_and_destination_refs():
    with pytest.raises(ValueError, match="to_ref"):
        BrowserAction(action="drag", ref="e1", observation_id="o")
    with pytest.raises(ValueError, match="to_ref applies to drag"):
        BrowserAction(action="click", ref="e1", to_ref="e2", observation_id="o")


@pytest.mark.parametrize("arguments", [
    {"action": "hover", "x": 10, "y": 20},
    {"action": "drag", "x": 10, "y": 20, "to_x": 30, "to_y": 40},
    {"action": "click", "ref": "e1", "button": "right"},
    {"action": "click", "x": 1, "y": 2, "clicks": 2},
])
def test_pointer_gestures_accept_refs_or_screenshot_points(arguments):
    BrowserAction(**arguments)


@pytest.mark.parametrize("arguments", [
    {"action": "hover", "x": 10},
    *({"action": "drag", "x": 10, "y": 20, "to_x": 30, "to_y": 40, **extra}
      for extra in ({"ref": "e1"}, {"to_ref": "e2"}, {"selector": "#item"})),
    {"action": "drag", "ref": "e1", "to_ref": "e2", "x": 10},
    {"action": "drag", "x": 10, "y": 20, "to_x": 30},
    {"action": "drag", "ref": "e1", "to_x": 30, "to_y": 40},  # One kind of grounding per drag.
    {"action": "drag", "ref": "e1", "to_ref": "e2", "x": 1, "y": 2, "to_x": 3, "to_y": 4},
    {"action": "click", "ref": "e1", "to_x": 1, "to_y": 1},
    {"action": "fill", "ref": "e1", "text": "a", "clicks": 2},
    {"action": "hover", "ref": "e1", "button": "right"},
    {"action": "click", "ref": "e1", "clicks": 4},
    {"action": "click", "ref": "e1", "button": "middle"},
])
def test_pointer_gestures_reject_partial_or_misplaced_arguments(arguments):
    with pytest.raises(ValueError):
        BrowserAction(**arguments)


async def test_double_and_right_clicks_send_their_own_mouse_events(tmp_path):
    client = SimpleNamespace(send=AsyncMock())
    session = SimpleNamespace(click=AsyncMock(), _internal=SimpleNamespace(client=client))
    run = SimpleNamespace(session=session, target_binding_id=None, last_dispatch_id=None)
    service = BrowserService(tmp_path)

    def mouse_events():
        return [(c.args[1]["type"], c.args[1]["button"], c.args[1]["clickCount"])
                for c in client.send.await_args_list if c.args[0] == "Input.dispatchMouseEvent"]

    await service._click(run, BrowserAction(action="click", x=5, y=6, clicks=2))
    assert mouse_events() == [("mousePressed", "left", 1), ("mouseReleased", "left", 1),
                              ("mousePressed", "left", 2), ("mouseReleased", "left", 2)]
    client.send.reset_mock()
    await service._click(run, BrowserAction(action="click", x=5, y=6, button="right"))
    assert mouse_events() == [("mousePressed", "right", 1), ("mouseReleased", "right", 1)]
    session.click.assert_not_awaited()
    await service._click(run, BrowserAction(action="click", x=5, y=6))
    session.click.assert_awaited_once_with(ref=None, selector=None, x=5, y=6)


def test_approval_card_names_the_click_gesture():
    from deepseek_tui.browser.permissions import preview

    assert preview(None, {"action": "click", "button": "right"}, "en")["title"].startswith("Right-click")
    assert preview(None, {"action": "click", "clicks": 2}, "zh")["title"].endswith("双击")
    assert preview(None, {"action": "click"}, "en")["title"].startswith("Click")


PAGE = """<!doctype html><meta charset=utf-8><title>Widgets</title>
<style>.hide input{opacity:0;position:absolute;width:1px;height:1px}
.card{cursor:pointer;padding:6px}.task{cursor:grab;padding:8px;border:1px solid}
.col{display:inline-block;width:200px;min-height:120px;vertical-align:top}</style>
<label class=hide><input id=agree type=checkbox><span>Agree to terms</span></label>
<div class=card id=card>Open order card</div>
<div role=slider id=vol aria-label=Volume aria-valuenow=3 tabindex=0>slider</div>
<ul role=tree><li role=treeitem><a href="#docs">Docs link</a></li></ul>
<div class=col id=todo><div class=task>Write notes</div></div>
<div class=col id=done><div class=task>Set up CI</div></div>
<input aria-label=Box1 maxlength=1><input aria-label=Box2 maxlength=1>
<button id=boom>Save draft</button><p id=out></p>
<script>
const out=document.getElementById('out');
document.getElementById('card').addEventListener('click',()=>out.textContent='card opened');
const vol=document.getElementById('vol');
vol.addEventListener('keydown',e=>{if(e.key==='ArrowRight')vol.setAttribute('aria-valuenow',4)});
document.querySelectorAll('input[maxlength]').forEach((b,i,all)=>b.addEventListener('input',
  ()=>{if(b.value&&all[i+1])all[i+1].focus()}));
let drag=null;
document.addEventListener('mousedown',e=>{drag=e.target.closest('.task')});
document.addEventListener('mouseup',e=>{const col=document.elementFromPoint(e.clientX,e.clientY)
  ?.closest('.col');if(drag&&col)col.append(drag);drag=null});
document.getElementById('boom').addEventListener('click',()=>{throw new Error('quota of 42 KB exceeded')});
</script>""".encode()


@pytest.fixture
async def page(tmp_path):
    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 for actual Chrome")

    async def serve(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                         b"Content-Length: " + str(len(PAGE)).encode()
                         + b"\r\nConnection: close\r\n\r\n" + PAGE)
            await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    service = BrowserService(tmp_path)
    service.configure("t", persistent=False)
    try:
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        opened = await service.action("t", BrowserAction(action="open", url=url))
        assert opened["success"], opened
        yield service
    finally:
        await service.close_all()
        server.close()


async def act(service, **arguments):
    return await service.action("t", BrowserAction(**arguments), require_observation=True)


async def observe(service):
    return (await service.action("t", BrowserAction(action="observe")))["observation"]


def element(observed, name):
    return next(e for e in observed["elements"] if e["name"].startswith(name))


async def page_text(service):
    return (await observe(service))["text"]


async def test_styled_controls_and_script_bound_elements_are_operable(page):
    observed = await observe(page)
    names = [e["name"] for e in observed["elements"]]
    # The tree item only wraps a link (both are named "Docs link"); the link is the one target.
    assert names.count("Docs link") == 1
    agree = element(observed, "Agree to terms")
    checked = await act(page, action="set_checked", checked=True, ref=agree["ref"],
                        observation_id=observed["observation_id"])
    assert checked["success"] and checked["receipt"]["effect"] == "confirmed"
    observed = await observe(page)
    await act(page, action="click", ref=element(observed, "Open order card")["ref"],
              observation_id=observed["observation_id"])
    assert "card opened" in await page_text(page)
    observed = await observe(page)
    await act(page, action="press", key="ArrowRight", ref=element(observed, "Volume")["ref"],
              observation_id=observed["observation_id"])
    run = page.runs["t"]
    from deepseek_tui.browser.observation import evaluate

    assert await evaluate(run.session._internal.client,
                          "document.getElementById('vol').getAttribute('aria-valuenow')") == "4"


async def test_refs_persist_and_action_results_list_changes(page):
    first = await observe(page)
    card = element(first, "Open order card")
    clicked = await act(page, action="click", ref=card["ref"],
                        observation_id=first["observation_id"])
    changes = clicked["observation"]["changes"]
    assert changes["base"] == first["observation_id"]
    assert changes["text"] == ["+ card opened"] and changes["elements"] == []
    assert element(await observe(page), "Open order card")["ref"] == card["ref"]


async def test_drag_moves_an_item_between_drop_zones(page):
    observed = await observe(page)
    dragged = await act(page, action="drag", ref=element(observed, "Write notes")["ref"],
                        to_ref=element(observed, "Set up CI")["ref"],
                        observation_id=observed["observation_id"])
    assert dragged["success"], dragged
    from deepseek_tui.browser.observation import evaluate

    assert await evaluate(page.runs["t"].session._internal.client,
                          "document.getElementById('done').textContent.includes('Write notes')")


async def test_type_reaches_per_key_code_boxes(page):
    observed = await observe(page)
    typed = await act(page, action="type", text="K7", ref=element(observed, "Box1")["ref"],
                      observation_id=observed["observation_id"])
    assert typed["receipt"]["effect"] == "confirmed" and "following fields" in typed["content"]
    from deepseek_tui.browser.observation import evaluate

    assert await evaluate(page.runs["t"].session._internal.client,
                          "[...document.querySelectorAll('input[maxlength]')].map(b=>b.value).join('')"
                          ) == "K7"


async def test_fill_into_empty_code_box_keeps_focus_on_it(page):
    # Backspace in an empty box moves focus back; fill must not send it there.
    from deepseek_tui.browser.observation import evaluate

    client = page.runs["t"].session._internal.client
    await evaluate(client, "(()=>{const all=[...document.querySelectorAll('input[maxlength]')];"
                   "all.forEach((b,i)=>b.addEventListener('keydown',e=>{if(e.key==='Backspace'"
                   "&&!b.value&&all[i-1])all[i-1].focus()}));return true})()")
    for box, char in (("Box1", "K"), ("Box2", "7")):
        observed = await observe(page)
        filled = await act(page, action="fill", text=char, ref=element(observed, box)["ref"],
                           observation_id=observed["observation_id"])
        assert filled["receipt"]["effect"] == "confirmed", filled


async def test_uncaught_errors_reach_the_action_result_and_console(page):
    observed = await observe(page)
    clicked = await act(page, action="click", ref=element(observed, "Save draft")["ref"],
                        observation_id=observed["observation_id"])
    assert "42 KB" in clicked["console_errors"]["entries"][-1]["text"]
    logs = await page.action("t", BrowserAction(action="console"))
    assert any("42 KB" in entry["text"] for entry in logs["content"]["entries"])
    assert "untrusted" in logs["content"]["source"]


async def test_console_capture_starts_only_when_requested(tmp_path):
    # Sites can detect an enabled Runtime domain; attaching to a page must not enable it.
    from deepseek_tui.browser.native import NativeBrowserEvents

    class Client:
        send = AsyncMock(return_value={"frameTree": {"frame": {"id": "main", "loaderId": "doc"}}})

        def on(self, event, callback):
            pass

    client = Client()
    run = SimpleNamespace(thread_id="one", native=False, generation=0, observation_context=None,
                          session=SimpleNamespace(_internal=SimpleNamespace(client=client)))
    native = NativeBrowserEvents(run, BrowserService(tmp_path))
    await native.install(client)
    enabled = lambda: [c.args[0] for c in client.send.await_args_list
                       if c.args[0] in {"Runtime.enable", "Log.enable"}]
    assert enabled() == []
    await native.watch_console()
    await native.watch_console()
    assert enabled() == ["Runtime.enable", "Log.enable"]


async def test_console_navigation_disables_capture_and_clears_old_messages(tmp_path):
    from deepseek_tui.browser.native import NativeBrowserEvents

    callbacks = {}
    class Client:
        send = AsyncMock(return_value={"frameTree": {"frame": {"id": "main", "loaderId": "doc"}}})
        def on(self, event, callback):
            callbacks[event] = callback
    client = Client()
    run = SimpleNamespace(thread_id="navigation", native=False, generation=0, observation_context=None, recorder=None,
                          session=SimpleNamespace(_internal=SimpleNamespace(client=client)))
    native = NativeBrowserEvents(run, BrowserService(tmp_path))
    await native.install(client)
    await native.watch_console()
    native._log(client, "error", "old document", {})
    callbacks["Page.frameNavigated"]({"frame": {"id": "main", "loaderId": "external", "url": "https://example.com"}})
    await asyncio.gather(*native.console_resets)
    assert client not in native.console_clients
    assert native.console_entries() == []
    commands = [call.args[0] for call in client.send.await_args_list]
    assert commands[-2:] == ["Runtime.disable", "Log.disable"]
    # Explicit console requests can enable it again on the new document.
    await native.watch_console()
    assert client in native.console_clients


@pytest.mark.parametrize("failure", ["before_press", "during_drag", "navigation", "cancel"])
async def test_drag_failure_releases_offscreen_without_reporting_unstarted_press(
    monkeypatch, failure
):
    sent = []
    page_id = ["original"]

    async def send(method, params=None):
        sent.append((method, params))
        if method == "Input.dispatchMouseEvent" and params["type"] == "mouseMoved":
            moves = sum(p is not None and p.get("type") == "mouseMoved" for _, p in sent)
            if failure == "before_press":
                raise RuntimeError("lost before press")
            if moves == 2:
                if failure == "during_drag":
                    raise RuntimeError("lost during drag")
                if failure == "cancel":
                    raise asyncio.CancelledError()
                page_id[0] = "new page"

    monkeypatch.setattr(
        "deepseek_tui.browser.service.document_identity",
        AsyncMock(side_effect=lambda _: page_id[0]),
    )
    run = SimpleNamespace(
        session=SimpleNamespace(_internal=SimpleNamespace(client=SimpleNamespace(send=send))),
        generation=0,
        transferring=False,
        last_dispatch_id=None,
    )
    service = SimpleNamespace(_dispatch_guard=AsyncMock(return_value={}))
    action = BrowserAction(action="drag", x=10, y=20, to_x=30, to_y=40)
    action._action_id = "drag"
    with pytest.raises((RuntimeError, ValueError, asyncio.CancelledError)):
        await BrowserService._drag(service, run, action)
    releases = [p for _, p in sent if p and p.get("type") == "mouseReleased"]
    if failure == "before_press":
        assert not releases and run.last_dispatch_id is None
    else:
        assert len(releases) == 1
        assert (releases[0]["x"], releases[0]["y"]) == (-1, -1)
        assert run.last_dispatch_id == "drag"
