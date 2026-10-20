"""Real Chrome, local fixtures and browser transport; no external pages or paid LLM."""

import asyncio
import os

import pytest

from deepseek_tui.browser.observation import evaluate
from deepseek_tui.browser.service import BrowserAction, BrowserService

PAGE = """<!doctype html><meta charset=utf-8><title>Delivery fixture</title>
<style>.gone{display:none}.transparent{opacity:0}body{margin:20px}button{padding:8px}</style>
<div>川沙附近结果</div><span>测试店 4.8分 800米</span>
<div hidden>HIDDEN_SENTINEL</div><div class=transparent>TRANSPARENT_SENTINEL</div>
<div aria-hidden=true>ARIA_SENTINEL</div>
<textarea>PRIVATE_DRAFT</textarea><div contenteditable>EDITOR_DRAFT</div>
<label for=q>地区</label><input id=q value=old>
<button id=search
 onclick="document.querySelector('#result').textContent='川沙测试店 4.8分 800米'">搜索</button>
<div id=result></div><label><input id=check type=checkbox>通知</label>
<select id=sort onchange="document.querySelector('#result').textContent='已按评分排序'">
<option value=distance>距离</option><option value=rating>评分</option></select>
<button class=duplicate>重复一</button><button class=duplicate>重复二</button>
<div id=shadow></div>
<iframe id=frame srcdoc="<button id='inside'>Frame button</button>"
 onload="this.contentDocument.querySelector('button').onclick=e=>e.target.textContent='FRAME_CLICKED'"></iframe>
<script>
const shadow=document.querySelector('#shadow').attachShadow({mode:'open'});
shadow.innerHTML='<button>Shadow button</button>';
shadow.querySelector('button').onclick=e=>e.target.textContent='SHADOW_CLICKED';
</script>""".encode()


@pytest.fixture
async def chrome(tmp_path):
    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 for actual Chrome")

    async def serve(reader, writer):
        try:
            try:
                await reader.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError:
                return
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                b"Content-Length: "
                + str(len(PAGE)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + PAGE
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    service = BrowserService(tmp_path)
    try:
        opened = await service.action(
            "t",
            BrowserAction(
                action="open", url=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            ),
        )
        assert opened["success"], opened
        yield service, service.runs["t"]
    finally:
        await service.close_all()
        server.close()
        await server.wait_closed()


async def read(service):
    return (await service.action("t", BrowserAction(action="observe", level="full")))["observation"]


def ref(observation, name):
    return next(e["ref"] for e in observation["elements"] if e["name"] == name)


async def act(service, observation, action, **kwargs):
    return await service.action(
        "t",
        BrowserAction(action=action, observation_id=observation["observation_id"], **kwargs),
        require_observation=True,
    )


@pytest.mark.parametrize("tree", ["root", "shadow", "frame"])
async def test_page_cannot_redirect_a_bound_ref_through_main_world_globals(chrome, tree):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, """document.body.innerHTML='<div id=host></div><output id=result></output>';
      window.expectedClicks=0;window.otherClicks=0;true""")
    markup = ("<button id=expected onclick='top.expectedClicks++'>Preview</button>"
              "<button id=other onclick='top.otherClicks++'>Preview</button>")
    import json

    if tree == "root":
        expression = "document.querySelector('#host').innerHTML=" + json.dumps(markup)
        root = "document"
    elif tree == "shadow":
        expression = "document.querySelector('#host').attachShadow({mode:'open'}).innerHTML=" + json.dumps(markup)
        root = "document.querySelector('#host').shadowRoot"
    else:
        expression = "document.querySelector('#host').innerHTML='<iframe id=child></iframe>';" + \
            "document.querySelector('#child').contentDocument.body.innerHTML=" + json.dumps(markup)
        root = "document.querySelector('#child').contentDocument"
    await evaluate(client, expression + ";true")
    observation = await read(service)
    chosen = next(e["ref"] for e in observation["elements"] if e["name"] == "Preview")
    await evaluate(client, "(()=>{const other=" + root + ".querySelector('#other');"
        "const s=window.__deepseekObservation;if(s?.refs.has(" + json.dumps(chosen) +
        "))s.refs.get(" + json.dumps(chosen) + ").element=other;"
        "window.__deepseekTarget=other;return true})()")
    result = await act(service, observation, "click", ref=chosen)
    assert result["success"], result
    assert await evaluate(client, "[window.expectedClicks,window.otherClicks]") == [1, 0]


async def test_shared_dom_marker_cannot_redirect_a_validated_click(chrome, monkeypatch):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, """document.body.innerHTML=`
      <button id=expected onclick='window.expectedClicks++'>Preview</button>
      <button id=other onclick='window.otherClicks++'>Preview</button>`;
      window.expectedClicks=0;window.otherClicks=0;true""")
    observation = await read(service)
    original = service._action

    async def spoof_marker(run, action):
        await evaluate(client, """(()=>{
          const marker=document.querySelector('#expected').getAttribute('data-deepseek-target');
          document.querySelector('#expected').removeAttribute('data-deepseek-target');
          if(marker)document.querySelector('#other').setAttribute('data-deepseek-target',marker);
          window.__deepseekTarget=document.querySelector('#other');return true})()""")
        return await original(run, action)

    monkeypatch.setattr(service, "_action", spoof_marker)
    result = await act(service, observation, "click", selector="#expected")
    assert result["success"], result
    assert await evaluate(client, "[window.expectedClicks,window.otherClicks]") == [1, 0]


@pytest.mark.parametrize("change", ["key", "label", "unrelated_clock"])
async def test_bound_ref_keeps_the_same_business_record(chrome, change):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, """document.body.innerHTML=`
      <section id=row data-record=A><span id=record>Record A</span><time id=clock>12:00</time>
      <button id=details onclick='window.clickedRecord=this.parentElement.dataset.record'>Details</button>
      </section>`;window.clickedRecord=null;true""")
    observation = await read(service)
    if change == "key":
        await evaluate(client, "document.querySelector('#row').dataset.record='B';true")
    elif change == "label":
        await evaluate(client, "document.querySelector('#record').textContent='Record B';true")
    else:
        await evaluate(client, "document.querySelector('#clock').textContent='12:01';true")
    result = await act(service, observation, "click", ref=ref(observation, "Details"))
    if change == "unrelated_clock":
        assert result["success"], result
        assert await evaluate(client, "window.clickedRecord") == "A"
    else:
        assert result["receipt"]["execution"] == "not_executed"
        assert result["receipt"]["reason"] == "target_context_changed"
        assert await evaluate(client, "window.clickedRecord===null") is True


@pytest.mark.parametrize("kind", ["input_value_equals", "title_contains"])
async def test_workflow_verification_waits_for_async_field_and_title(chrome, kind):
    import time
    from deepseek_tui.browser.workflows import _verify

    service, run = chrome
    client = run.session._internal.client
    expression = "document.querySelector('#q').value='ready'" if kind == "input_value_equals" else "document.title='ready'"
    await evaluate(client, "setTimeout(()=>{" + expression + "},350);true")
    started = time.monotonic()
    await _verify(service, run, {"type": kind, "value": "ready", "selector": "#q"})
    assert time.monotonic() - started >= 0.2
    assert run.log[-1]["action"] == "verify" and run.log[-1]["success"]


async def test_condition_deadline_and_shadow_scope_return_only_match_result(chrome):
    import time

    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.querySelector('#shadow').shadowRoot.innerHTML='<input id=private value=PRIVATE_DRAFT>';")
    result = await service.action("t", BrowserAction(action="wait", condition="input_value_equals",
        shadow_path=["#shadow"], selector="#private", text="PRIVATE_DRAFT", timeout_ms=200))
    assert result["success"] and "PRIVATE_DRAFT" not in str(result)
    started = time.monotonic()
    result = await service.action("t", BrowserAction(action="wait", condition="input_value_equals",
        shadow_path=["#shadow"], selector="#private", text="never", timeout_ms=100))
    assert not result["success"] and time.monotonic() - started < 2


async def test_live_input_cannot_cross_a_document_with_the_same_generation(chrome):
    from deepseek_tui.browser.input import BrowserInput

    service, run = chrome
    client = run.session._internal.client
    await service.control("t", "user")
    scene = await service._scene(run)
    await client.send("Page.navigate", {"url": run.url + "/second"})
    for _ in range(30):
        current = await service._scene(run)
        if current["document_id"] != scene["document_id"]:
            break
        await asyncio.sleep(0.05)
    assert current["document_id"] != scene["document_id"]
    with pytest.raises(ValueError, match="page changed"):
        await service.input("t", BrowserInput(kind="text", text="STALE_PRIVATE", generation=run.generation,
            scene_id=scene["scene_id"]))
    await evaluate(client, "document.querySelector('#q').focus();true")
    # Child documents may finish loading after the root navigation; use the
    # coherent frame actually presented to the human for the subsequent input.
    for _ in range(30):
        view = await service.view("t")
        if view["image"]:
            current = view["scene"]
            break
        await asyncio.sleep(.05)
    await service.input("t", BrowserInput(kind="text", text="CURRENT", generation=run.generation,
        scene_id=current["scene_id"]))
    assert await evaluate(client, "document.querySelector('#q').value.includes('CURRENT')") is True
    assert "STALE_PRIVATE" not in str(service.state("t"))


async def test_describe_and_option_handles_preserve_long_values_on_the_backend(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML='<label for=s>Choice</label><select id=s></select>';"
        "const s=document.querySelector('#s');s.add(new Option('Empty',''));"
        "s.add(new Option('Opaque choice','v'.repeat(7000)));true")
    observation = await read(service)
    element = next(e for e in observation["elements"] if e["tag"] == "select")
    described = await service.action("t", BrowserAction(action="describe", ref=element["ref"],
        observation_id=observation["observation_id"]))
    option = described["observation"]["elements"][0]["options"][1]
    assert option["value_omitted"] and "value" not in option
    selected = await act(service, observation, "select", ref=element["ref"], option_ref=option["option_ref"])
    assert selected["success"] and selected["receipt"]["effect"] == "confirmed"
    assert await evaluate(client, "document.querySelector('#s').value.length") == 7000
    assert "v" * 1000 not in str(selected)
    observation = await read(service)
    element = next(e for e in observation["elements"] if e["tag"] == "select")
    handle = element["options"][1]["option_ref"]
    await evaluate(client, "document.querySelector('#s').options[1].value='changed';true")
    rejected = await act(service, observation, "select", ref=element["ref"], option_ref=handle)
    assert rejected["receipt"]["reason"] == "stale_option"


async def test_semantics_and_unicode_name_details_are_consistent(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML='<input type=submit value=Continue>"
        "<span hidden id=hidden>Hidden referenced</span><button aria-labelledby=hidden></button>"
        "<button id=long></button>';document.querySelector('#long').setAttribute('aria-label',"
        "'😀'.repeat(3000)+'Tail');true")
    observation = await read(service)
    assert {"Continue", "Hidden referenced"}.issubset({e["name"] for e in observation["elements"]})
    element = next(e for e in observation["elements"] if e.get("selector") == "#long")
    assert element["name_truncated"] and len(element["name"]) == 300
    first = await service.action("t", BrowserAction(action="describe", ref=element["ref"],
        observation_id=observation["observation_id"]))
    second = await service.action("t", BrowserAction(action="describe", ref=element["ref"],
        observation_id=observation["observation_id"], detail_offset=2000))
    text = first["observation"]["elements"][0]["name"] + second["observation"]["elements"][0]["name"]
    assert text == "😀" * 3000 + "Tail"
    text.encode("utf-8")


async def test_continuation_rejects_a_changed_list_snapshot(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML='<section id=list></section>';"
        "for(let i=0;i<270;i++){const e=document.createElement('button');e.textContent='Item '+i;"
        "document.querySelector('#list').append(e)};true")
    first = await service.action("t", BrowserAction(action="observe", selector="#list", level="full"))
    observation = first["observation"]
    next_page = await service.action("t", BrowserAction(action="observe", scope_ref=observation["observation_id"],
        element_offset=250, level="full"))
    assert len(next_page["observation"]["elements"]) == 20
    observation = (await service.action("t", BrowserAction(action="observe", selector="#list", level="full")))["observation"]
    await evaluate(client, "document.querySelector('#list').prepend(document.createElement('button'));true")
    from deepseek_tui.browser.service import BrowserActionError

    with pytest.raises(BrowserActionError, match="Paging snapshot changed"):
        await service.action("t", BrowserAction(action="observe", scope_ref=observation["observation_id"],
            element_offset=250, level="full"))


async def test_visible_text_refs_and_real_interactions(chrome):
    service, run = chrome
    observation = await read(service)
    assert "川沙附近结果" in observation["text"] and "4.8分" in observation["text"]
    assert "SENTINEL" not in observation["text"]
    assert "PRIVATE_DRAFT" not in str(observation)
    assert "EDITOR_DRAFT" not in str(observation)
    filled = await act(service, observation, "fill", ref=ref(observation, "地区"), text="川沙")
    assert filled["success"], filled
    assert (
        await evaluate(run.session._internal.client, "document.querySelector('#q').value") == "川沙"
    )
    clicked = await act(
        service, filled["observation"], "click", ref=ref(filled["observation"], "搜索")
    )
    assert clicked["success"] and "川沙测试店" in clicked["observation"]["text"]
    selected = await act(service, clicked["observation"], "select", selector="#sort", text="rating")
    assert selected["success"] and "已按评分排序" in selected["observation"]["text"]
    checked = await act(
        service, selected["observation"], "set_checked", selector="#check", checked=True
    )
    assert checked["success"], checked
    assert await evaluate(run.session._internal.client, "document.querySelector('#check').checked")
    assert checked["receipt"]["effect"] == "confirmed"


async def test_stale_ambiguous_changed_and_obscured_targets_are_not_clicked(chrome):
    service, run = chrome
    observation = await read(service)
    ambiguous = await act(service, observation, "click", selector=".duplicate")
    assert ambiguous["receipt"]["reason"] == "target_not_unique"
    stale = await act(service, observation, "click", ref=ref(observation, "搜索"))
    assert stale["receipt"]["reason"] == "stale_observation"
    observation = await read(service)
    await evaluate(
        run.session._internal.client, "document.querySelector('#search').textContent='Changed'"
    )
    changed = await act(service, observation, "click", ref=ref(observation, "搜索"))
    assert changed["receipt"]["reason"] == "target_changed"
    observation = await read(service)
    await evaluate(
        run.session._internal.client,
        "(()=>{const e=document.createElement('div');"
        "e.style='position:fixed;inset:0;z-index:999';document.body.append(e);return true})()",
    )
    blocked = await act(service, observation, "click", ref=ref(observation, "Changed"))
    assert blocked["receipt"]["reason"] == "target_obscured"
    assert blocked["receipt"]["execution"] == "not_executed"


async def test_wait_checks_current_condition_including_hidden(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "(()=>{setTimeout(()=>{document.querySelector('#result').textContent='READY'},150);"
        "return true})()",
    )
    ready = await service.action("t", BrowserAction(action="wait", text="READY", timeout_ms=1500))
    assert ready["success"] and ready["receipt"]["effect"] == "confirmed"
    # Existing matching URL must resolve immediately, without requiring a URL transition.
    ready = await service.action(
        "t", BrowserAction(action="wait", url_contains="127.0.0.1", timeout_ms=100)
    )
    assert ready["success"]
    await evaluate(
        client,
        "(()=>{setTimeout(()=>{document.querySelector('#result').hidden=true},150);return true})()",
    )
    hidden = await service.action(
        "t", BrowserAction(action="wait", selector="#result", wait_state="hidden", timeout_ms=1500)
    )
    assert hidden["success"]
    timeout = await service.action("t", BrowserAction(action="wait", text="NEVER", timeout_ms=100))
    assert not timeout["success"] and timeout["receipt"]["effect"] == "not_confirmed"
    invisible = await service.action(
        "t", BrowserAction(action="wait", text="TRANSPARENT_SENTINEL", timeout_ms=100)
    )
    assert not invisible["success"]
    invisible = await service.action(
        "t", BrowserAction(action="check_text", text="TRANSPARENT_SENTINEL")
    )
    assert not invisible["success"]
    wrong_page = await service.action(
        "t",
        BrowserAction(
            action="wait",
            selector="#result",
            wait_state="hidden",
            url_contains="wrong-page",
            timeout_ms=100,
        ),
    )
    assert not wrong_page["success"]


async def test_shadow_and_same_origin_frame_targets(chrome):
    service, _ = chrome
    observation = await read(service)
    shadow = await act(service, observation, "click", ref=ref(observation, "Shadow button"))
    assert shadow["success"], shadow
    assert "SHADOW_CLICKED" in shadow["observation"]["text"]
    frame = await act(
        service, shadow["observation"], "click", ref=ref(shadow["observation"], "Frame button")
    )
    assert frame["success"], frame
    assert "FRAME_CLICKED" in frame["observation"]["text"]


async def test_coordinate_click_requires_current_capture(chrome):
    service, run = chrome
    observation = await read(service)
    no_image = await act(service, observation, "click", x=25, y=25)
    assert no_image["receipt"]["reason"] == "screenshot_required"
    assert "Call screenshot" in no_image["content"]
    screenshot = await service.action("t", BrowserAction(action="screenshot"))
    observation = screenshot["observation"]
    assert observation["screenshot_artifact_id"] == screenshot["artifact"]["id"]
    box = next(e["box"] for e in observation["elements"] if e["name"] == "搜索")
    await evaluate(
        run.session._internal.client, "document.querySelector('#search').style.marginLeft='30px'"
    )
    stale = await act(
        service,
        observation,
        "click",
        x=int(box["x"] + box["width"] / 2),
        y=int(box["y"] + box["height"] / 2),
    )
    assert stale["receipt"]["reason"] == "stale_layout"


@pytest.mark.parametrize("motion", ["css_spinner", "js_clock"])
async def test_coordinate_click_tolerates_unrelated_motion(chrome, motion):
    service, run = chrome
    client = run.session._internal.client
    extra = {
        "css_spinner": "<style>@keyframes s{to{transform:rotate(360deg)}}</style>"
        "<div style='position:absolute;left:500px;top:100px;width:20px;height:20px;"
        "border:3px solid #333;border-top-color:transparent;animation:s 1s linear infinite'></div>",
        "js_clock": "<div id=k style='position:absolute;left:600px;top:300px'></div>",
    }[motion]
    await evaluate(client, "document.body.innerHTML=`<button onclick='window.c=(window.c||0)+1' "
        "style='position:absolute;left:100px;top:100px;width:120px;height:40px'>Go</button>"
        + extra + "`;window.c=0;"
        + ("setInterval(()=>k.textContent=Date.now(),50);" if motion == "js_clock" else "")
        + "true")
    capture = await service.action("t", BrowserAction(action="screenshot"))
    await asyncio.sleep(0.3)
    result = await act(service, capture["observation"], "click", x=160, y=120)
    assert result["success"], result
    assert await evaluate(client, "window.c") == 1


async def test_reload_refuses_form_result_page(chrome):
    service, run = chrome
    await evaluate(run.session._internal.client, "document.body.innerHTML="
        "`<form method=post action=/submit><input name=a value=1><button>Send</button></form>`;true")
    observation = await read(service)
    sent = await act(service, observation, "click", ref=ref(observation, "Send"))
    assert sent["success"], sent
    reloaded = await service.action("t", BrowserAction(action="reload"), require_observation=True)
    assert reloaded["receipt"]["execution"] == "not_executed"
    assert reloaded["receipt"]["reason"] == "reload_would_resubmit_form"
    # Ordinary pages still reload.
    await service.action("t", BrowserAction(action="open", url=run.url.replace("/submit", "/plain")))
    assert (await service.action("t", BrowserAction(action="reload")))["success"]


async def test_coordinate_click_outside_viewport_is_a_recorded_rejection(chrome):
    service, _ = chrome
    for _ in range(2):  # A rejected attempt leaves its operation_id free to retry.
        capture = await service.action("t", BrowserAction(action="screenshot"))
        result = await act(service, capture["observation"], "click", x=1300, y=10,
                           operation_id="outside")
        assert result["receipt"]["execution"] == "not_executed"
        assert result["receipt"]["reason"] == "pointer_outside_viewport"


async def test_coordinate_click_rejects_changed_pixels_at_point(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML=`<button onclick='window.c=(window.c||0)+1' "
        "style='position:absolute;left:100px;top:100px;width:120px;height:40px'>Go</button>`;"
        "window.c=0;true")
    capture = await service.action("t", BrowserAction(action="screenshot"))
    await evaluate(client, "document.body.insertAdjacentHTML('beforeend',"
        "`<div style='position:fixed;inset:0;background:#fff'>modal</div>`);true")
    result = await act(service, capture["observation"], "click", x=160, y=120)
    assert result["receipt"]["reason"] == "screenshot_pixels_changed"
    assert await evaluate(client, "window.c") == 0


async def test_real_engine_observes_clicks_and_returns_answer(chrome, tmp_path):
    """Full engine/tool/CDP chain driven only by the primary model outputs."""
    import json
    from unittest.mock import AsyncMock

    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.config.models import Config, FeatureConfig
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.engine.turn import TurnResult
    from deepseek_tui.protocol.messages import Message, Role
    from deepseek_tui.protocol.responses import ToolCall

    service, run = chrome
    class NoSecondaryRequests(LLMClient):
        async def stream_chat_completion(self, request):
            raise AssertionError("No secondary assessment is allowed")
            yield

    handle = EngineHandle()
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
        browser_service=service, runtime_thread_id="t"
    )
    engine._handle_approval_flow = AsyncMock(return_value=False)
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)
    engine._handle_shell_process_turn_handoff = AsyncMock(return_value=False)
    round_number = 0

    async def primary(request, *args, **kwargs):
        nonlocal round_number
        round_number += 1
        if round_number == 1:
            action = {"action": "observe"}
        elif round_number == 2:
            result = next(m for m in reversed(request.messages) if m.role == Role.TOOL)
            observation = json.loads(result.content[0].content)["observation"]
            action = {
                "action": "click",
                "ref": ref(observation, "搜索"),
                "observation_id": observation["observation_id"],
            }
        else:
            return TurnResult(assistant_message=None, tool_calls=[ToolCall(
                id="finish", name="finish_task", arguments={
                    "status": "completed", "answer": "推荐川沙测试店，评分4.8分，距离800米。",
                    "evidence": ["tool:browser-2"], "remaining": [],
                })])
        return TurnResult(
            assistant_message=None,
            tool_calls=[
                ToolCall(id=f"browser-{round_number}", name="browser_use", arguments=action)
            ],
        )

    engine.turn_loop.run = primary
    try:
        result = await engine._run_conversation(
            [Message.user("用浏览器推荐附近评分好的店，我在川沙")], "test-model", "sys", None
        )
        assert round_number == 3
        assert result.assistant_message.text_content() == "推荐川沙测试店，评分4.8分，距离800米。"
        assert run.log[-1]["after_observation_id"]
    finally:
        await engine.shutdown_session()


async def test_wait_text_is_scoped_to_selector(chrome):
    service, run = chrome
    await evaluate(run.session._internal.client,
        "(()=>{document.body.innerHTML='<div id=order>Pending</div>' +"
        "'<div>Payment successful</div>';return true})()")
    for state, expected in [("visible", False), ("hidden", True)]:
        result = await service.action("t", BrowserAction(
            action="wait", selector="#order", text="Payment successful",
            wait_state=state, timeout_ms=150))
        assert result["success"] is expected
    result = await service.action("t", BrowserAction(
        action="wait", selector="#order", text="Pending", timeout_ms=150))
    assert result["success"]
    for state in ("visible", "hidden"):
        ambiguous = await service.action("t", BrowserAction(
            action="wait", selector="div", text="Pending", wait_state=state, timeout_ms=150))
        assert not ambiguous["success"]


async def test_element_names_exclude_private_and_hidden_descendants(chrome):
    service, run = chrome
    await evaluate(run.session._internal.client,
        "(()=>{document.body.innerHTML='<div role=button>Public' +"
        "'<div contenteditable=true>PRIVATE_DRAFT</div>' +"
        "'<span aria-hidden=true>HIDDEN_SENTINEL</span></div>' +"
        "'<label for=q>Label<textarea>PRIVATE_LABEL</textarea></label>' +"
        "'<input id=q><div id=name>Name<span hidden>PRIVATE_NAME</span></div>' +"
        "'<button aria-labelledby=name></button>';return true})()")
    observation = await read(service)
    assert "PRIVATE_" not in str(observation)
    assert "HIDDEN_SENTINEL" not in str(observation)
    assert any(e["name"] == "Public" for e in observation["elements"])
    assert any(e["name"] == "Label" for e in observation["elements"])
    assert any(e["name"] == "Name" for e in observation["elements"])


@pytest.mark.parametrize("editable", ["", '=""', '=true', '=plaintext-only'])
async def test_contenteditable_variants_can_be_filled(chrome, editable):
    service, run = chrome
    import json

    html = f'<div id=editor contenteditable{editable} aria-label=Editor>draft</div>'
    html += '<div id=readonly contenteditable=false>Read only</div>'
    await evaluate(run.session._internal.client,
        f"(()=>{{document.body.innerHTML={json.dumps(html)};return true}})()")
    observation = await read(service)
    assert len(observation["elements"]) == 1
    result = await act(service, observation, "fill", selector="#editor", text="replacement")
    assert result["success"], result
    assert await evaluate(run.session._internal.client,
        "document.querySelector('#editor').textContent") == "replacement"


@pytest.mark.parametrize("nested", ["frame", "shadow", "element"])
async def test_nested_scroll_invalidates_coordinate_capture(chrome, nested):
    service, run = chrome
    client = run.session._internal.client
    roots = {"frame": "document.querySelector('#frame').contentDocument.body",
             "shadow": "document.querySelector('#shadow').shadowRoot",
             "element": "document.body"}
    root = roots[nested]
    await evaluate(client, "(()=>{const root=" + root + ";root.innerHTML="
        "'<div id=scroller style=\"height:80px;overflow:auto\">' +"
        "'<div style=height:2000px>Static content</div></div>';return true})()")
    capture = await service.action("t", BrowserAction(action="screenshot"))
    await evaluate(client, "(()=>{const e=(" + root + ").querySelector('#scroller');"
        "e.scrollTop=150;return e.scrollTop})()")
    result = await act(service, capture["observation"], "click", x=50, y=50)
    assert result["receipt"]["execution"] == "not_executed"
    assert result["receipt"]["reason"] == "stale_layout"


async def test_frame_viewport_scroll_invalidates_coordinate_capture(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client,
        "(()=>{document.querySelector('#frame').contentDocument.body.innerHTML="
        "'<div style=height:2000px>Static frame content</div>';return true})()")
    capture = await service.action("t", BrowserAction(action="screenshot"))
    offset = await evaluate(client,
        "(()=>{const view=document.querySelector('#frame').contentWindow;"
        "view.scrollTo(0,150);return view.scrollY})()")
    assert offset == 150
    result = await act(service, capture["observation"], "click", x=50, y=50)
    assert result["receipt"]["execution"] == "not_executed"
    assert result["receipt"]["reason"] == "stale_layout"


async def test_harness_rejects_wrong_controls_without_click(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "document.body.innerHTML=`<button id=submit onclick='window.clicks++'>Submit</button>"
        "<input id=ro readonly value=old><input id=q value=old>`;window.clicks=0",
    )
    for selector, reason in [("#submit", "target_not_editable"), ("#ro", "target_readonly")]:
        observation = await read(service)
        result = await act(service, observation, "fill", selector=selector, text="draft")
        assert result["receipt"]["execution"] == "not_executed"
        assert result["receipt"]["reason"] == reason
    assert await evaluate(client, "window.clicks") == 0
    await client.send("Page.bringToFront")
    observation = await read(service)
    await evaluate(client, "document.querySelector('#q').focus();true")
    result = await act(service, observation, "type", text="draft")
    assert result["receipt"]["reason"] == "focus_changed"


async def test_harness_verifies_states_and_chords(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "document.body.innerHTML=`<select id=s><option value=valid>Valid</option></select>"
        "<input id=c type=checkbox onclick='event.preventDefault()'><input id=q value=old>`;true",
    )
    result = await act(service, await read(service), "select", selector="#s", text="missing")
    assert result["receipt"]["execution"] == "not_executed"
    assert await evaluate(client, "document.querySelector('#s').value") == "valid"
    result = await act(service, await read(service), "set_checked", selector="#c", checked=True)
    assert not result["success"] and result["receipt"]["effect"] == "not_confirmed"
    assert result["receipt"]["execution"] == "executed"
    await evaluate(client, "document.querySelector('#q').focus();true")
    result = await act(service, await read(service), "press", key="Ctrl+A")
    assert result["success"]
    assert await evaluate(
        client,
        "[document.querySelector('#q').selectionStart,document.querySelector('#q').selectionEnd]",
    ) == [0, 3]


async def test_harness_continues_long_pages_and_checks_full_scope(chrome):
    service, run = chrome
    client = run.session._internal.client
    html = (
        "<p>"
        + "reading " * 3000
        + "LATE_SENTINEL</p>"
        + "".join(f"<button id=b{i}>Button {i}</button>" for i in range(270))
    )
    await evaluate(client, "document.body.innerHTML=" + __import__("json").dumps(html))
    first = await read(service)
    assert first["next_element_offset"] == 250
    second = (
        await service.action(
            "t",
            BrowserAction(
                action="observe",
                level="full",
                element_offset=250,
                text_offset=first["next_text_offset"],
                scope_ref=first["observation_id"],
            ),
        )
    )["observation"]
    assert any(e["name"] == "Button 269" for e in second["elements"])
    assert "LATE_SENTINEL" in second["text"]
    assert (await service.action("t", BrowserAction(action="check_text", text="LATE_SENTINEL")))[
        "success"
    ]


async def test_harness_scrolls_target_and_only_requested_axis(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "document.body.innerHTML=`<div id=box role=textbox "
        "style='width:100px;height:300px;overflow:auto'>"
        "<div style='height:3000px;width:3000px'>Content</div></div>`;"
        "window.lastWheel=null;window.onwheel=e=>window.lastWheel={x:e.deltaX,y:e.deltaY};true",
    )
    result = await act(service, await read(service), "scroll", selector="#box", amount=300)
    assert result["success"]
    await asyncio.sleep(0.15)
    assert await evaluate(client, "document.querySelector('#box').scrollTop") > 0
    assert result["receipt"]["effect"] == "confirmed"
    assert result["receipt"]["verification"]["kind"] == "observed_scroll_position"
    result = await act(service, await read(service), "scroll", selector="#box", direction="right")
    await asyncio.sleep(0.15)
    assert await evaluate(client, "window.lastWheel") == {"x": 300, "y": 0}


async def test_observation_reports_page_and_panel_scroll_sizes(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "document.body.innerHTML=`<div id=small style='height:50px;overflow:auto'>"
        "<div style='height:500px'>Code</div></div>"
        "<div id=list aria-label=Messages style='height:300px;overflow:auto'>"
        "<div style='height:2000px'>Rows</div></div>"
        "<div style='height:3000px;overflow:hidden'><div style='height:9000px'></div></div>`;"
        "scrollTo(0,0);true",
    )
    first = await read(service)
    assert first["viewport"]["scroll_y"] == 0
    assert first["viewport"]["scroll_height"] > 3000 > first["viewport"]["height"]
    assert first["total_scroll_containers"] == 2  # overflow:hidden does not scroll
    panel, small = first["scroll_containers"]  # largest first
    assert panel["name"] == "Messages" and small["viewport"]["scroll_height"] == 500
    assert panel["ref"] == "c0" and panel["viewport"] == {
        "width": panel["box"]["width"], "height": 300, "scroll_x": 0, "scroll_y": 0,
        "scroll_width": panel["box"]["width"], "scroll_height": 2000,
    }

    clicked = await act(service, first, "click", ref=panel["ref"])
    assert clicked["receipt"]["reason"] == "target_scroll_only"
    scrolled = await act(service, await read(service), "scroll", ref="c0", amount=300)
    assert scrolled["receipt"]["effect"] == "confirmed"
    await asyncio.sleep(0.15)
    assert await evaluate(client, "document.querySelector('#list').scrollTop") > 0
    assert (await read(service))["scroll_containers"][0]["viewport"]["scroll_y"] > 0
    by_selector = await act(service, await read(service), "scroll", selector="#small", amount=100)
    assert by_selector["receipt"]["effect"] == "confirmed"


async def test_scroll_amount_stays_in_css_pixels_under_page_zoom(chrome, monkeypatch):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "document.body.innerHTML=`<div id=box role=textbox style='height:300px;overflow:auto'>"
        "<div style='height:3000px'>Content</div></div>`;"
        "window.lastWheel=null;window.onwheel=e=>window.lastWheel=e.deltaY;true",
    )
    send = client.send

    async def zoomed(method, params=None, **kwargs):
        result = await send(method, params, **kwargs)
        if method == "Page.getLayoutMetrics":  # Headless Chrome cannot set page zoom itself.
            result = {**result, "cssVisualViewport": {**result["cssVisualViewport"], "zoom": 1.5}}
        return result

    monkeypatch.setattr(client, "send", zoomed)
    await act(service, await read(service), "scroll", selector="#box", amount=300)
    await asyncio.sleep(0.15)
    # Wheel deltas are device-independent: 450 at 150% zoom moves 300 CSS pixels.
    assert await evaluate(client, "window.lastWheel") == 450


async def test_recording_failure_preserves_completed_click(chrome, monkeypatch):
    from unittest.mock import AsyncMock

    service, run = chrome
    await evaluate(
        run.session._internal.client,
        "document.body.innerHTML=`<button id=b onclick='window.clicks++'>Click</button>`;"
        "window.clicks=0",
    )
    observation = await read(service)
    run.recording = True
    monkeypatch.setattr(
        service, "_capture", AsyncMock(side_effect=RuntimeError("capture unavailable"))
    )
    result = await act(service, observation, "click", selector="#b")
    assert result["success"] and result["receipt"]["execution"] == "executed"
    assert result["evidence_warning"]
    assert await evaluate(run.session._internal.client, "window.clicks") == 1


async def test_replay_uses_guarded_fill_and_validates_target(chrome):
    from types import SimpleNamespace

    from deepseek_tui.browser.workflows import _step, _verify

    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "document.body.innerHTML=`<input id=q value=old>"
        "<button id=b onclick='window.clicks++'>Submit</button>`;window.clicks=0",
    )
    step = SimpleNamespace(
        kind="fill", target={"selectorCandidates": ["#gone", "#q"]}, value="replacement", key=None
    )
    result = await _step(service, run, step, {})
    assert result["success"] and result["receipt"]["effect"] == "confirmed"
    assert await evaluate(client, "document.querySelector('#q').value") == "replacement"
    await _verify(
        service, run, {"type": "input_value_equals", "selector": "#q", "value": "replacement"}
    )
    step.target = {"selectorCandidates": ["#b"]}
    result = await _step(service, run, step, {})
    assert result["receipt"]["execution"] == "not_executed"
    assert await evaluate(client, "window.clicks") == 0


async def test_popup_snapshot_and_dead_session_are_visible_to_agent(chrome):
    from types import SimpleNamespace

    from deepseek_tui.tools.browser import BrowserUseTool

    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "document.body.innerHTML=`<button id=b "
        "onclick=\"window.open(location.href,'_blank')\">Popup</button>`;true",
    )
    result = await act(service, await read(service), "click", selector="#b")
    assert len(result["tabs"]) == 2
    assert len(result["tab_changes"]["opened"]) == 1
    assert len(service.state("t")["tabs"]) == 2
    await client.close()
    output = await BrowserUseTool().execute(
        {"action": "status"},
        SimpleNamespace(metadata={"browser_service": service, "runtime_thread_id": "t"}),
    )
    assert not output.success and "recover" in output.content
    assert not service.state("t")["active"]


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
async def test_scoped_cross_origin_frames_and_parent_overlay(chrome, host):
    import json

    service, run = chrome
    body = (
        b"<title>Cross frame</title><input id=q aria-label=Draft value=old>"
        b"<button id=b onclick=\"this.textContent='FRAME_DONE'\">Submit</button>"
        b"<div id=shadow></div><script>"
        b"document.querySelector('#shadow').attachShadow({mode:'open'}).innerHTML="
        b"'<input aria-label=ShadowDraft value=old>';</script>"
    )

    async def serve(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        url = f"http://{host}:{server.sockets[0].getsockname()[1]}/"
        await evaluate(
            run.session._internal.client,
            "document.body.innerHTML="
            + json.dumps(f"<iframe src='{url}' style='width:600px;height:300px'></iframe>"),
        )
        for _ in range(20):
            parent = await read(service)
            frame = next((f for f in parent["frames"] if f["url"] == url), None)
            if frame:
                break
            await asyncio.sleep(0.05)
        assert frame and frame["scoped_observation"], {
            "frames": parent["frames"],
            "targets": await run.session._internal.client.send("Target.getTargets"),
        }
        observed = (
            await service.action("t", BrowserAction(action="observe", frame_id=frame["frame_id"]))
        )["observation"]
        assert "Submit" in observed["text"] and observed["frame_id"] == frame["frame_id"]
        shadow_pressed = await act(
            service, observed, "press", ref=ref(observed, "ShadowDraft"), key="Ctrl+A"
        )
        assert await evaluate(
            run.observation_context,
            "(()=>{const e=document.querySelector('#shadow').shadowRoot.querySelector('input');"
            "return [e.selectionStart,e.selectionEnd]})()",
        ) == [0, 3]
        observed = shadow_pressed["observation"]
        pressed = await act(service, observed, "press", ref=ref(observed, "Draft"), key="Ctrl+A")
        assert pressed["success"], pressed
        assert await evaluate(
            run.observation_context,
            "[document.querySelector('#q').selectionStart,document.querySelector('#q').selectionEnd]",
        ) == [0, 3]
        observed = pressed["observation"]
        filled = await act(
            service, observed, "fill", ref=ref(observed, "Draft"), text="replacement"
        )
        assert filled["success"] and filled["receipt"]["effect"] == "confirmed", (
            filled["receipt"],
            filled["content"],
            await evaluate(
                run.observation_context,
                "[document.querySelector('#q').value,document.activeElement.id]",
            ),
        )
        assert filled["observation"]["frame_id"] == frame["frame_id"]
        clicked = await act(
            service, filled["observation"], "click", ref=ref(filled["observation"], "Submit")
        )
        assert "FRAME_DONE" in clicked["observation"]["text"], clicked
        shadow_filled = await act(
            service,
            clicked["observation"],
            "fill",
            ref=ref(clicked["observation"], "ShadowDraft"),
            text="shadow replacement",
        )
        assert shadow_filled["success"], shadow_filled
        scoped = (
            await service.action(
                "t",
                BrowserAction(
                    action="observe", frame_id=frame["frame_id"], shadow_path=["#shadow"]
                ),
            )
        )["observation"]
        assert len(scoped["elements"]) == 1 and scoped["elements"][0]["name"] == "ShadowDraft"
        typed = await act(service, scoped, "type", ref=scoped["elements"][0]["ref"], text="!")
        assert typed["success"], typed
        value = await evaluate(
            run.observation_context,
            "document.querySelector('#shadow').shadowRoot.querySelector('input').value",
        )
        assert value.count("!") == 1 and value.replace("!", "") == "shadow replacement"
        shadow_filled = typed
        clicked = shadow_filled
        await evaluate(
            run.session._internal.client, "document.body.style.transform='scale(.8)';true"
        )
        transformed = await act(
            service, clicked["observation"], "click", ref=ref(clicked["observation"], "FRAME_DONE")
        )
        assert transformed["receipt"]["execution"] == "not_executed"
        assert transformed["receipt"]["reason"] == "frame_coordinates_unavailable"
        await evaluate(run.session._internal.client, "document.body.style.transform='none';true")
        clicked = {
            "observation": (
                await service.action(
                    "t", BrowserAction(action="observe", frame_id=frame["frame_id"])
                )
            )["observation"]
        }
        await evaluate(
            run.session._internal.client,
            "document.body.insertAdjacentHTML('beforeend',"
            "`<div style='position:fixed;inset:0;z-index:999'></div>`);true",
        )
        blocked = await act(
            service, clicked["observation"], "click", ref=ref(clicked["observation"], "FRAME_DONE")
        )
        assert blocked["receipt"]["execution"] == "not_executed"
        assert blocked["receipt"]["reason"] == "target_obscured"
        from deepseek_tui.browser.workflows import (
            finish_recording,
            read_workflow,
            start_recording,
            start_replay,
        )

        await evaluate(
            run.session._internal.client,
            "document.querySelector('[style*=\"z-index:999\"]').remove();"
            "document.querySelector('iframe').id='recorded';true",
        )
        await service.control("t", "user")
        await start_recording(service, "t")
        scoped = (
            await service.action(
                "t", BrowserAction(action="observe", frame_id=frame["frame_id"]), actor="user"
            )
        )["observation"]
        await service.action(
            "t",
            BrowserAction(
                action="fill",
                ref=ref(scoped, "ShadowDraft"),
                observation_id=scoped["observation_id"],
                text="PRIVATE_FRAME_DRAFT",
            ),
            actor="user",
        )
        finished = await finish_recording(run)
        doc = read_workflow(service, "t", finished["recordingId"])
        fills = [step for step in doc.steps if step.kind == "fill"]
        assert len(fills) == 1 and fills[0].target["framePath"] == ["iframe#recorded"]
        assert fills[0].target["shadowPath"] == ["div#shadow"]
        await start_replay(
            service,
            "t",
            finished["recordingId"],
            {item["name"]: "frame replayed" for item in doc.inputs},
        )
        await asyncio.wait_for(run.demo_task, timeout=15)
        assert run.demo_status == "passed", run.error
        assert (
            await evaluate(
                run.observation_context,
                "document.querySelector('#shadow').shadowRoot.querySelector('input').value",
            )
            == "frame replayed"
        )
    finally:
        server.close()
        await server.wait_closed()


async def test_async_form_rollback_is_not_reported_as_confirmed(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        "document.body.innerHTML=`<input id=q value=old "
        "oninput=\"setTimeout(()=>this.value='old',30)\">`;true",
    )
    result = await act(service, await read(service), "fill", selector="#q", text="replacement")
    assert not result["success"]
    assert result["receipt"]["execution"] == "executed"
    assert result["receipt"]["effect"] == "not_confirmed"
    assert (
        await evaluate(run.session._internal.client, "document.querySelector('#q').value") == "old"
    )


async def test_full_page_and_crop_screenshots_preserve_coordinate_scope(chrome):
    from PIL import Image

    service, run = chrome
    await evaluate(run.session._internal.client, "document.body.style.height='2100px';true")
    full = await service.action("t", BrowserAction(action="screenshot", full_page=True))
    with Image.open(service.artifact("t", full["artifact"]["id"])) as image:
        assert image.height > run.height
    assert full["observation"]["screenshot_scope"] == "full_page"
    assert "screenshot_artifact_id" not in full["observation"]
    cropped = await service.action(
        "t", BrowserAction(action="screenshot", crop=(10, 800, 200, 100))
    )
    with Image.open(service.artifact("t", cropped["artifact"]["id"])) as image:
        assert image.size == (200, 100)
    assert cropped["observation"]["screenshot_scope"] == "crop"
    rejected = await act(service, cropped["observation"], "click", x=20, y=20)
    assert rejected["receipt"]["reason"] == "screenshot_required"
    from deepseek_tui.browser.service import BrowserActionError

    with pytest.raises(BrowserActionError, match="outside page bounds"):
        await service.action("t", BrowserAction(action="screenshot", crop=(0, 0, 10000, 10000)))


async def test_dead_session_recovery_does_not_replay_completed_actions(chrome):
    from deepseek_tui.browser.service import BrowserActionError

    service, run = chrome
    await act(service, await read(service), "click", selector="#search")
    previous_generation = run.generation
    await run.session._internal.client.close()
    with pytest.raises(ValueError, match="recover"):
        await service.ensure("t")
    with pytest.raises(BrowserActionError):
        await service.action("t", BrowserAction(action="observe"))
    state = await service.recover("t", actor="agent")
    assert state["active"] and state["generation"] > previous_generation
    assert sum(item["action"] == "click" for item in state["log"]) == 1
    observation = await read(service)
    assert "川沙附近结果" in observation["text"]
    assert (
        await evaluate(
            service.runs["t"].session._internal.client,
            "document.querySelector('#result').textContent",
        )
        == ""
    )


async def test_click_observation_waits_for_requests_it_started(chrome):
    async def api(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            await asyncio.sleep(0.8)
            writer.write(b"HTTP/1.1 200 OK\r\nAccess-Control-Allow-Origin: *\r\n"
                         b"Content-Length: 12\r\nConnection: close\r\n\r\nRESULT READY")
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(api, "127.0.0.1", 0)
    service, run = chrome
    try:
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/api"
        await evaluate(run.session._internal.client, "document.body.innerHTML="
            f"`<button onclick=\"fetch('{url}').then(r=>r.text()).then(t=>out.textContent=t)\">"
            "Load</button><div id=out></div>`;true")
        observation = await read(service)
        clicked = await act(service, observation, "click", ref=ref(observation, "Load"))
        assert "RESULT READY" in clicked["observation"]["text"]
        assert not clicked["observation"].get("warnings")
    finally:
        server.close()
        await server.wait_closed()


async def test_fill_sets_picker_inputs_and_confirms_their_value(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML=`<input type=date aria-label=Day "
        "onchange='window.changes=(window.changes||0)+1'><input type=time aria-label=At>"
        "<input type=color aria-label=Tint>`;true")
    observation = await read(service)
    assert next(e for e in observation["elements"] if e["name"] == "Day")["editable"]
    for name, value in [("Day", "2026-10-14"), ("At", "13:45"), ("Tint", "#ff0000")]:
        result = await act(service, observation, "fill", ref=ref(observation, name), text=value)
        assert result["success"] and result["receipt"]["effect"] == "confirmed", result
        observation = result["observation"]
    day = "document.querySelector('[aria-label=Day]').value"
    assert await evaluate(client, day) == "2026-10-14"
    assert await evaluate(client, "window.changes") == 1
    invalid = await act(service, observation, "fill", ref=ref(observation, "Day"),
                        text="14/10/2026")
    assert not invalid["success"] and invalid["receipt"]["effect"] == "not_confirmed"
    observation = invalid["observation"]
    typed = await act(service, observation, "type", ref=ref(observation, "At"), text="1")
    assert typed["receipt"]["reason"] == "target_not_editable"


async def test_direct_service_fill_cannot_click_submit_button(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        "document.body.innerHTML=`<button id=b onclick='window.clicks++'>Submit</button>`;"
        "window.clicks=0",
    )
    result = await service.action("t", BrowserAction(action="fill", selector="#b", text="draft"))
    assert result["receipt"]["execution"] == "not_executed"
    assert result["receipt"]["reason"] == "target_not_editable"
    assert await evaluate(run.session._internal.client, "window.clicks") == 0


async def test_replay_rejects_changed_semantic_target(chrome):
    from types import SimpleNamespace

    from deepseek_tui.browser.workflows import _step

    service, run = chrome
    await evaluate(
        run.session._internal.client,
        "document.body.innerHTML=`<input id=q aria-label=Other value=old>`;true",
    )
    step = SimpleNamespace(
        kind="fill",
        target={"selectorCandidates": ["#q"], "name": "Original"},
        value="replacement",
        key=None,
    )
    with pytest.raises(ValueError, match="matching"):
        await _step(service, run, step, {})
    assert (
        await evaluate(run.session._internal.client, "document.querySelector('#q').value") == "old"
    )


async def test_long_select_options_can_be_continued(chrome):
    import json

    service, run = chrome
    html = (
        "<select id=s>"
        + "".join(f"<option value=v{i}>Choice {i}</option>" for i in range(60))
        + "</select>"
    )
    await evaluate(run.session._internal.client, "document.body.innerHTML=" + json.dumps(html))
    first = (await service.action("t", BrowserAction(action="observe", selector="#s")))[
        "observation"
    ]
    assert first["scope_selector"] == "#s"
    assert first["elements"][0]["next_option_offset"] == 50
    last = (
        await service.action("t", BrowserAction(action="observe", scope_ref=first["observation_id"], option_offset=50))
    )["observation"]
    assert last["elements"][0]["options"][-1]["value"] == "v59"
    result = await act(service, last, "select", ref=last["elements"][0]["ref"], text="v59")
    assert result["success"] and result["receipt"]["effect"] == "confirmed"


async def test_contenteditable_multiline_fill_has_correct_postcondition(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        "document.body.innerHTML=`<div id=q contenteditable aria-label=Draft>old</div>`;true",
    )
    result = await act(service, await read(service), "fill", selector="#q", text="one\ntwo")
    assert result["success"] and result["receipt"]["effect"] == "confirmed", result


@pytest.mark.parametrize(
    "key,expected", [("a", "a"), ("Shift+a", "A"), ("Space", " "), ("+", "+"), ("Shift+1", "!")]
)
async def test_press_printable_key_inserts_once_with_native_events(chrome, key, expected):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML='<input id=q>';
      window.events=[]; const q=document.querySelector('#q');
      ['keydown','beforeinput','input','keyup'].forEach(type=>
        q.addEventListener(type,e=>window.events.push([e.type,e.isTrusted])));true""",
    )
    result = await act(service, await read(service), "press", selector="#q", key=key)
    assert result["success"], result
    assert (
        await evaluate(run.session._internal.client, "document.querySelector('#q').value")
        == expected
    )
    assert await evaluate(run.session._internal.client, "window.events") == [
        ["keydown", True],
        ["beforeinput", True],
        ["input", True],
        ["keyup", True],
    ]


async def test_press_rejects_target_that_cannot_gain_focus(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML=
      '<input id=q><div id=b role=button>Submit</div>';window.keys=0;
      document.querySelector('#q').addEventListener('keydown',()=>window.keys++);
      document.querySelector('#q').focus();true""",
    )
    result = await act(service, await read(service), "press", selector="#b", key="Enter")
    assert not result["success"] and result["receipt"]["execution"] == "not_executed", result
    assert await evaluate(run.session._internal.client, "window.keys") == 0


async def test_shadow_label_uses_its_own_tree_and_guards_semantic_changes(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML=
      '<span id=name>Outer name</span><div id=host></div>';
      const root=document.querySelector('#host').attachShadow({mode:'open'});
      root.innerHTML='<span id=name>Inner name</span><input aria-labelledby=name>';true""",
    )
    observation = await read(service)
    target_ref = ref(observation, "Inner name")
    await evaluate(
        run.session._internal.client,
        "document.querySelector('#host').shadowRoot.querySelector('#name').textContent='Changed'",
    )
    result = await act(service, observation, "fill", ref=target_ref, text="draft")
    assert result["receipt"]["reason"] == "target_changed"
    assert (
        await evaluate(
            run.session._internal.client,
            "document.querySelector('#host').shadowRoot.querySelector('input').value",
        )
        == ""
    )


@pytest.mark.parametrize("missing", [False, True])
async def test_shadow_path_replay_never_fills_similar_parent_target(chrome, missing):
    from types import SimpleNamespace

    from deepseek_tui.browser.workflows import _step

    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML=
      '<input id=q aria-label=Draft value=parent><div id=host></div>';
      const root=document.querySelector('#host').attachShadow({mode:'open'});
      root.innerHTML='<div id=nested></div>';
      root.querySelector('#nested').attachShadow({mode:'open'}).innerHTML=
        '<input id=q aria-label=Draft value=child>';true""",
    )
    step = SimpleNamespace(
        kind="fill",
        value="replacement",
        key=None,
        target={
            "selectorCandidates": ["#q"],
            "name": "Draft",
            "tag": "input",
            "shadowPath": ["#missing" if missing else "#host", "#nested"],
        },
    )
    if missing:
        with pytest.raises(ValueError, match="matching"):
            await _step(service, run, step, {})
    else:
        result = await _step(service, run, step, {})
        assert result["success"] and result["receipt"]["effect"] == "confirmed", result
        assert (
            await evaluate(
                run.session._internal.client,
                "document.querySelector('#host').shadowRoot.querySelector('#nested').shadowRoot"
                ".querySelector('#q').value",
            )
            == "replacement"
        )
    assert (
        await evaluate(run.session._internal.client, "document.querySelector('#q').value")
        == "parent"
    )


async def test_scoped_shadow_observation_can_continue_large_tree(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML='<div id=host></div>';
      const root=document.querySelector('#host').attachShadow({mode:'open'});
      root.innerHTML=Array.from({length:270},(_,i)=>
        '<button>Choice '+i+'</button>').join('');true""",
    )
    first = (
        await service.action(
            "t", BrowserAction(action="observe", shadow_path=["#host"], level="full")
        )
    )["observation"]
    assert first["scope_shadow_path"] == ["#host"] and first["next_element_offset"] == 250
    last = (
        await service.action(
            "t",
            BrowserAction(
                action="observe",
                shadow_path=["#host"],
                element_offset=first["next_element_offset"],
                scope_ref=first["observation_id"],
                level="full",
            ),
        )
    )["observation"]
    assert last["elements"][0]["name"] == "Choice 250" and len(last["elements"]) == 20


@pytest.mark.parametrize("action", ["fill", "type"])
async def test_field_input_does_not_edit_previous_field_when_click_cannot_focus(chrome, action):
    from deepseek_tui.browser.service import BrowserActionError

    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML=
      '<input id=previous value=KEEP><input id=q value=TARGET>';window.inputs=0;
      document.querySelector('#q').addEventListener('mousedown',e=>e.preventDefault());
      document.addEventListener('input',()=>window.inputs++);
      document.querySelector('#previous').focus();true""",
    )
    with pytest.raises(BrowserActionError, match="no keyboard input"):
        await act(service, await read(service), action, selector="#q", text="replacement")
    assert await evaluate(
        run.session._internal.client,
        "[document.querySelector('#previous').value,document.querySelector('#q').value,window.inputs]",
    ) == ["KEEP", "TARGET", 0]


async def test_transformed_same_origin_frame_is_rejected_before_click(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        "document.querySelector('#frame').style.transform='scale(0.8)';true",
    )
    observation = await read(service)
    result = await act(service, observation, "click", ref=ref(observation, "Frame button"))
    assert result["receipt"]["execution"] == "not_executed", result
    assert result["receipt"]["reason"] == "frame_coordinates_unavailable"
    assert (
        await evaluate(
            run.session._internal.client,
            "document.querySelector('#frame').contentDocument.querySelector('button').textContent",
        )
        == "Frame button"
    )


async def test_printable_press_respects_cancelled_browser_default(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML='<input id=q>';
      document.querySelector('#q').addEventListener('keydown',e=>e.preventDefault());true""",
    )
    result = await act(service, await read(service), "press", selector="#q", key="a")
    assert result["success"], result
    assert await evaluate(run.session._internal.client, "document.querySelector('#q').value") == ""


async def test_fill_balances_shortcut_keys_before_replacing_text(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML='<input id=q value=old>';
      window.keys=[];['keydown','keyup'].forEach(type=>
        document.querySelector('#q').addEventListener(type,e=>
          window.keys.push([e.type,e.key,e.ctrlKey || e.metaKey])));true""",
    )
    result = await act(service, await read(service), "fill", selector="#q", text="replacement")
    assert result["success"] and result["receipt"]["effect"] == "confirmed", result
    assert await evaluate(run.session._internal.client, "window.keys") == [
        ["keydown", "a", True],
        ["keyup", "a", True],
        ["keydown", "Backspace", False],
        ["keyup", "Backspace", False],
    ]


async def test_public_shadow_workflow_replay_completes_with_guarded_target(chrome, monkeypatch):
    from octop_browser.record.models import SemanticStep, StepsDocument

    from deepseek_tui.browser import workflows

    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML=
      '<input id=q aria-label=Draft value=parent><div id=host></div>';
      document.querySelector('#host').attachShadow({mode:'open'}).innerHTML=
        '<input id=q aria-label=Draft value=child>';true""",
    )
    doc = StepsDocument(
        recordingId="rec_shadow",
        steps=[
            SemanticStep(
                id="1",
                kind="fill",
                value="replacement",
                target={
                    "selectorCandidates": ["#q"],
                    "name": "Draft",
                    "tag": "input",
                    "shadowPath": ["#host"],
                },
            )
        ],
    )
    monkeypatch.setattr(workflows, "read_workflow", lambda *args: doc)
    await service.control("t", "user")
    await workflows.start_replay(service, "t", "rec_shadow", {})
    await asyncio.wait_for(run.demo_task, timeout=15)
    assert run.demo_status == "passed", run.error
    assert await evaluate(
        run.session._internal.client,
        "[document.querySelector('#q').value,document.querySelector('#host').shadowRoot"
        ".querySelector('#q').value]",
    ) == ["parent", "replacement"]


@pytest.mark.parametrize("key", ["Ctrl+Alt+a", "Ctrl+Shift+a"])
async def test_extra_modifiers_do_not_trigger_select_all_editing_command(chrome, key):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML='<input id=q value=draft>';
      const q=document.querySelector('#q');q.focus();q.setSelectionRange(1,1);true""",
    )
    result = await act(service, await read(service), "press", selector="#q", key=key)
    assert result["success"], result
    assert await evaluate(
        run.session._internal.client,
        "[document.querySelector('#q').selectionStart,document.querySelector('#q').selectionEnd]",
    ) == [1, 1]


@pytest.mark.parametrize("late_shadow", [False, True])
async def test_recorded_shadow_input_and_click_replay_in_the_original_tree(chrome, late_shadow):
    from deepseek_tui.browser.workflows import (
        finish_recording,
        read_workflow,
        recording_store,
        start_recording,
        start_replay,
    )

    service, run = chrome
    client = run.session._internal.client
    setup = """document.body.innerHTML=
      '<input id=q aria-label=Draft value=parent><div id=host></div>';
      const root=document.querySelector('#host').attachShadow({mode:'open'});
      root.innerHTML='<input id=q aria-label=Draft value=child><button id=save>Save</button>';
      root.querySelector('#save').onclick=()=>window.saved=root.querySelector('#q').value;
      window.saved='';window.savedCount=0;
      root.querySelector('#save').onclick=()=>{window.saved=root.querySelector('#q').value;window.savedCount++};true"""
    if not late_shadow:
        await evaluate(client, setup)
    await service.control("t", "user")
    await start_recording(service, "t")
    if late_shadow:
        await evaluate(client, setup)
    observation = (await service.action("t", BrowserAction(action="observe"), actor="user"))[
        "observation"
    ]
    result = await service.action(
        "t",
        BrowserAction(
            action="fill",
            observation_id=observation["observation_id"],
            ref=ref(observation, "Draft"),
            text="parent",
        ),
        actor="user",
    )
    observation = result["observation"]
    shadow = next(
        e for e in observation["elements"] if e["name"] == "Draft" and not e.get("selector")
    )
    await service.action(
        "t",
        BrowserAction(
            action="fill",
            observation_id=observation["observation_id"],
            ref=shadow["ref"],
            text="PRIVATE_RECORDED_DRAFT",
        ),
        actor="user",
    )
    box = await evaluate(
        client,
        "(()=>{const r=document.querySelector('#host').shadowRoot"
        ".querySelector('#save').getBoundingClientRect();"
        "return {x:r.x+r.width/2,y:r.y+r.height/2}})()",
    )
    for kind in ("mousePressed", "mouseReleased"):
        await client.send(
            "Input.dispatchMouseEvent", {"type": kind, **box, "button": "left", "clickCount": 1}
        )
    await asyncio.sleep(0.35)
    finished = await finish_recording(run)
    doc = read_workflow(service, "t", finished["recordingId"])
    fill = next(
        step for step in doc.steps if step.kind == "fill" and (step.target or {}).get("shadowPath")
    )
    click = next(
        step
        for step in doc.steps
        if step.kind == "click" and (step.target or {}).get("name") == "Save"
    )
    assert fill.target["shadowPath"] == click.target["shadowPath"] == ["div#host"]
    assert len([step for step in doc.steps if (step.target or {}).get("name") == "Save"]) == 1
    assert doc.steps.index(fill) < doc.steps.index(click)
    assert "PRIVATE_RECORDED_DRAFT" not in str(
        recording_store(service, "t").read_events(finished["recordingId"])
    )
    await evaluate(
        client,
        "document.querySelector('#host').shadowRoot.querySelector('#q').value='child';"
        "window.saved='';window.savedCount=0",
    )
    await start_replay(
        service, "t", finished["recordingId"], {item["name"]: "replayed" for item in doc.inputs}
    )
    await asyncio.wait_for(run.demo_task, timeout=15)
    assert run.demo_status == "passed", run.error
    assert await evaluate(client, "window.saved") == "replayed"
    assert await evaluate(client, "window.savedCount") == 1


async def test_stopping_recording_flushes_the_last_input_without_waiting(chrome):
    from deepseek_tui.browser.workflows import finish_recording, read_workflow, start_recording

    service, run = chrome
    await service.control("t", "user")
    started = await start_recording(service, "t")
    await evaluate(run.session._internal.client, "document.querySelector('#q').focus();true")
    await run.session._internal.client.send("Input.insertText", {"text": "PRIVATE_FINAL_INPUT"})
    await finish_recording(run)
    doc = read_workflow(service, "t", started["recordingId"])
    assert any(step.kind == "fill" for step in doc.steps)


async def test_recording_starts_on_the_current_tab(chrome):
    from deepseek_tui.browser.workflows import finish_recording, start_recording

    service, run = chrome
    current = (await run.session._internal.client.send("Target.getTargetInfo"))["targetInfo"]
    await service.action("t", BrowserAction(action="new_tab", url=current["url"] + "?other"))
    await service.action("t", BrowserAction(action="switch_tab", tab_id=current["targetId"]))
    await service.control("t", "user")
    started = await start_recording(service, "t")
    assert started["startUrl"] == current["url"]
    target = await run.recorder.client.send("Target.getTargetInfo")
    assert target["targetInfo"]["targetId"] == current["targetId"]
    await finish_recording(run)


async def test_recorded_direct_frame_path_replays_in_the_child_document(chrome):
    from deepseek_tui.browser.workflows import (
        finish_recording,
        read_workflow,
        start_recording,
        start_replay,
    )

    service, run = chrome
    await service.control("t", "user")
    await start_recording(service, "t")
    observation = (await service.action("t", BrowserAction(action="observe"), actor="user"))[
        "observation"
    ]
    await service.action(
        "t",
        BrowserAction(
            action="click",
            ref=ref(observation, "Frame button"),
            observation_id=observation["observation_id"],
        ),
        actor="user",
    )
    finished = await finish_recording(run)
    doc = read_workflow(service, "t", finished["recordingId"])
    clicks = [step for step in doc.steps if step.kind == "click"]
    assert len(clicks) == 1 and clicks[0].target["framePath"] == ["iframe#frame"]
    await evaluate(
        run.session._internal.client,
        "document.querySelector('#frame').contentDocument.querySelector('button')"
        ".textContent='Frame button'",
    )
    await start_replay(service, "t", finished["recordingId"], {})
    await asyncio.wait_for(run.demo_task, timeout=15)
    assert run.demo_status == "passed", run.error
    assert (
        await evaluate(
            run.session._internal.client,
            "document.querySelector('#frame').contentDocument.querySelector('button').textContent",
        )
        == "FRAME_CLICKED"
    )


async def test_recording_metadata_does_not_persist_editable_contents(chrome):
    from deepseek_tui.browser.workflows import finish_recording, recording_store, start_recording

    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML=
      '<textarea id=a>PRIVATE_TEXTAREA_CONTENT</textarea>'+
      '<div id=b contenteditable>PRIVATE_EDITOR_CONTENT</div>'+
      '<input id=c value=PRIVATE_INPUT_ATTRIBUTE>';true""",
    )
    await service.control("t", "user")
    started = await start_recording(service, "t")
    for selector in ["#a", "#b", "#c"]:
        await service.action("t", BrowserAction(action="click", selector=selector), actor="user")
    await finish_recording(run)
    events = str(recording_store(service, "t").read_events(started["recordingId"]))
    assert all(
        value not in events
        for value in [
            "PRIVATE_TEXTAREA_CONTENT",
            "PRIVATE_EDITOR_CONTENT",
            "PRIVATE_INPUT_ATTRIBUTE",
        ]
    )


async def test_second_recording_restores_hooks_and_captures_spa_navigation(chrome):
    from deepseek_tui.browser.workflows import finish_recording, recording_store, start_recording

    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "window.oldPush=history.pushState;window.oldShadow=Element.prototype.attachShadow;true",
    )
    await service.control("t", "user")
    first = await start_recording(service, "t")
    await finish_recording(run)
    assert (
        await evaluate(
            client,
            "history.pushState===window.oldPush && "
            "Element.prototype.attachShadow===window.oldShadow"
            " && !window.__deepseekRecorder",
        )
        is True
    )
    count = len(recording_store(service, "t").read_events(first["recordingId"]))
    second = await start_recording(service, "t")
    await evaluate(client, "history.pushState({},'', '/second-recording');true")
    await finish_recording(run)
    events = recording_store(service, "t").read_events(second["recordingId"])
    assert (
        len(
            [
                e
                for e in events
                if e["kind"] == "navigation" and "/second-recording" in e.get("urlAfter", "")
            ]
        )
        == 1
    )
    assert len(recording_store(service, "t").read_events(first["recordingId"])) == count


async def test_replay_rejects_frame_url_change_before_click(chrome):
    from types import SimpleNamespace

    from deepseek_tui.browser.workflows import _step

    service, run = chrome
    step = SimpleNamespace(
        kind="click",
        key=None,
        value=None,
        target={
            "selectorCandidates": ["#inside"],
            "name": "Frame button",
            "tag": "button",
            "framePath": ["#frame"],
            "frameUrl": "https://example.invalid/other",
        },
    )
    with pytest.raises(ValueError, match="frame URL"):
        await _step(service, run, step, {})
    assert (
        await evaluate(
            run.session._internal.client,
            "document.querySelector('#frame').contentDocument.querySelector('button').textContent",
        )
        == "Frame button"
    )


async def test_observe_can_resolve_a_recorded_frame_owner_selector(chrome):
    service, run = chrome
    observed = (
        await service.action(
            "t", BrowserAction(action="observe", frame_selector="#frame", selector="#inside")
        )
    )["observation"]
    assert observed["frame_id"] and observed["scope_frame_selector"] == "#frame"
    result = await act(service, observed, "click", ref=ref(observed, "Frame button"))
    assert result["success"] and "FRAME_CLICKED" in result["observation"]["text"]


async def test_script_triggered_click_is_not_replayed_a_second_time(chrome):
    from deepseek_tui.browser.workflows import (
        finish_recording,
        read_workflow,
        start_recording,
        start_replay,
    )

    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        """document.body.innerHTML=
      '<button id=primary>Primary</button><button id=secondary>Secondary</button>';
      window.count=0;document.querySelector('#secondary').onclick=()=>window.count++;
      document.querySelector('#primary').onclick=()=>document.querySelector('#secondary').click();true""",
    )
    await service.control("t", "user")
    started = await start_recording(service, "t")
    await service.action("t", BrowserAction(action="click", selector="#primary"), actor="user")
    await finish_recording(run)
    doc = read_workflow(service, "t", started["recordingId"])
    clicks = [step for step in doc.steps if step.kind == "click"]
    assert len(clicks) == 1 and clicks[0].target["name"] == "Primary"
    await evaluate(client, "window.count=0")
    await start_replay(service, "t", started["recordingId"], {})
    await asyncio.wait_for(run.demo_task, timeout=15)
    assert run.demo_status == "passed" and await evaluate(client, "window.count") == 1


async def test_nested_frame_capture_can_finish_without_incomplete_warning(chrome):
    from deepseek_tui.browser.workflows import (
        finish_recording,
        read_workflow,
        recording_store,
        start_recording,
        start_replay,
    )

    service, run = chrome
    await evaluate(
        run.session._internal.client,
        """document.body.innerHTML=
      `<iframe srcdoc="<iframe srcdoc='nested'></iframe>"></iframe>`;true""",
    )
    for _ in range(20):
        observed = await read(service)
        if len(observed["frames"]) == 2:
            break
        await asyncio.sleep(0.05)
    assert len(observed["frames"]) == 2
    await service.control("t", "user")
    started = await start_recording(service, "t")
    await finish_recording(run)
    assert run.recorder is None and read_workflow(service, "t", started["recordingId"]).steps
    assert recording_store(service, "t").read_manifest(started["recordingId"]).status == "stopped"


async def test_page_scripts_cannot_reach_recorder_or_forge_steps(chrome):
    from deepseek_tui.browser.workflows import finish_recording, read_workflow, start_recording

    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML='<button id=danger>Delete account</button>';true")
    await service.control("t", "user")
    await start_recording(service, "t")
    exposed = await evaluate(client, "(()=>Object.keys(window).filter(k=>/HBR|deepseek|binding/i"
        ".test(k) || (typeof window[k]==='function' && /^__/.test(k))))()")
    assert exposed == []
    async with run.lock:
        result = await finish_recording(run)
    steps = read_workflow(service, "t", result["recordingId"]).steps
    assert not any(s.kind == "click" for s in steps)


async def test_partial_recording_install_failure_disposes_injected_hooks(chrome, monkeypatch):
    from deepseek_tui.browser.recording import WorkbenchRecordSession
    from deepseek_tui.browser.workflows import start_recording

    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "window.before=history.pushState;true")
    original = WorkbenchRecordSession._install_on_client

    async def fail_after_install(self, client, target_id):
        await original(self, client, target_id)
        raise RuntimeError("failure after injection")

    monkeypatch.setattr(WorkbenchRecordSession, "_install_on_client", fail_after_install)
    await service.control("t", "user")
    with pytest.raises(RuntimeError, match="failure after injection"):
        await start_recording(service, "t")
    assert run.recorder is None
    assert (
        await evaluate(client, "!window.__deepseekRecorder && history.pushState===window.before")
        is True
    )


@pytest.mark.parametrize("shadow_owner", [False, True])
async def test_nested_frame_paths_validate_geometry_focus_and_ancestor_record(chrome, shadow_owner):
    import json

    service, run = chrome
    client = run.session._internal.client
    inner = '<label for=q>Nested draft</label><input id=q><button id=save onclick="document.body.dataset.saved=1">Nested save</button>'
    outer = '<section data-record=A><iframe id=inner style="width:600px;height:200px"></iframe></section>'
    await evaluate(client, "document.body.innerHTML='<div id=host></div>';true")
    root = "document.querySelector('#host').attachShadow({mode:'open'})" if shadow_owner else "document.body"
    await evaluate(client, "(()=>{const r=" + root + ";r.innerHTML='<iframe id=outer style=\"width:700px;height:350px\"></iframe>';"
        "r.querySelector('iframe').srcdoc=" + json.dumps(outer) + ";return true})()")
    outer_node = "document.querySelector('#host').shadowRoot.querySelector('#outer')" if shadow_owner else "document.querySelector('#outer')"
    for _ in range(50):
        ready = await evaluate(client, "!!" + outer_node + ".contentDocument?.querySelector('#inner')")
        if ready:
            break
        await asyncio.sleep(.02)
    await evaluate(client, outer_node + ".contentDocument.querySelector('#inner').srcdoc=" + json.dumps(inner) + ";true")
    path = [{"selector": "#outer", "shadowPath": ["#host"]}, "#inner"] if shadow_owner else ["#outer", "#inner"]
    for _ in range(50):
        try:
            observed = (await service.action("t", BrowserAction(action="observe", frame_path=path)))["observation"]
            if any(e["name"] == "Nested draft" for e in observed["elements"]):
                break
        except RuntimeError:
            pass
        await asyncio.sleep(.02)
    filled = await act(service, observed, "fill", ref=ref(observed, "Nested draft"), text="你好 nested")
    assert filled["success"], filled
    assert await evaluate(run.observation_context, "document.querySelector('#q').value") == "你好 nested"
    observed = (await service.action("t", BrowserAction(action="observe", frame_path=path)))["observation"]
    await evaluate(client, outer_node + ".contentDocument.querySelector('section').dataset.record='B';true")
    rejected = await act(service, observed, "click", ref=ref(observed, "Nested save"))
    assert not rejected["success"] and rejected["receipt"]["execution"] == "not_executed", rejected
    await service.action("t", BrowserAction(action="observe", frame_path=path))
    assert await evaluate(run.observation_context, "!document.body.dataset.saved")


async def test_native_dialog_ends_the_dispatched_action_without_duplicate_click(chrome):
    service, run = chrome
    await evaluate(run.session._internal.client, "document.body.innerHTML=`<button id=ask onclick=\"window.n=(window.n||0)+1;window.answer=prompt('Answer');\">Ask</button>`;true")
    observed = await read(service)
    result = await act(service, observed, "click", ref=ref(observed, "Ask"))
    assert result["receipt"]["execution"] == "executed" and result["dialog"]["type"] == "prompt", result
    dialog = service.state("t")["dialog"]
    with pytest.raises(RuntimeError):
        await service.action("t", BrowserAction(action="handle_dialog", dialog_id="old", accept=True))
    # A stale dialog answer is rejected before dispatch; clear that test receipt via human review.
    if run.unresolved:
        await service.action("t", BrowserAction(action="resolve_operation", operation_id=next(iter(run.unresolved)),
            outcome="not_executed", reason="stale dialog was not answered"), actor="user")
    answered = await service.action("t", BrowserAction(action="handle_dialog", dialog_id=dialog["id"], accept=True, text="yes"))
    assert answered["success"]
    assert await evaluate(run.session._internal.client, "[window.n,window.answer]") == [1, "yes"]
    assert service.operation("t", result["receipt"]["action_id"])["receipt"]["execution"] == "executed"


async def test_human_viewport_dialog_returns_a_dispatched_receipt_and_readable_dialog(chrome):
    from deepseek_tui.browser.input import BrowserInput

    service, run = chrome
    await evaluate(run.session._internal.client, "document.body.innerHTML=`<button id=ask onclick=\"window.n=(window.n||0)+1;window.answer=confirm('Save?');\">Ask</button>`;true")
    await service.control("t", "user")
    scene = (await service.view("t"))["scene"]["scene_id"]
    box = await evaluate(run.session._internal.client, "(()=>{const r=document.querySelector('button').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
    for event in ["mousePressed", "mouseReleased"]:
        result = await service.input("t", BrowserInput(kind="mouse", event=event, button="left",
            generation=run.generation, scene_id=scene, **box))
    assert result["receipt"]["execution"] == "executed" and result["receipt"]["effect"] == "awaiting_dialog"
    view = await service.view("t")
    assert view["dialog"] and not run.unresolved
    await service.action("t", BrowserAction(action="handle_dialog", dialog_id=view["dialog"]["id"],
        accept=True, generation=run.generation), actor="user")
    assert await evaluate(run.session._internal.client, "[window.n,window.answer]") == [1, True]


async def test_explicit_upload_and_native_chooser_stay_inside_authorized_files(chrome, tmp_path):
    service, run = chrome
    run.upload_root = tmp_path
    path = tmp_path / "draft.txt"
    path.write_text("uploaded test draft")
    await evaluate(run.session._internal.client, "document.body.innerHTML=`<input id=file type=file><input id=hidden type=file hidden><button id=choose onclick=\"document.querySelector('#hidden').click()\">Choose</button>`;true")
    observed = await read(service)
    result = await act(service, observed, "upload", selector="#file", files=[str(path)])
    assert result["success"], result
    assert await evaluate(run.session._internal.client, "document.querySelector('#file').files[0].name") == "draft.txt"
    observed = await read(service)
    result = await act(service, observed, "click", selector="#choose")
    assert result["success"], result
    chooser = service.state("t")["file_chooser"]
    assert chooser and chooser["mode"] == "selectSingle"
    result = await service.action("t", BrowserAction(action="upload", chooser_id=chooser["id"], files=[str(path)]))
    assert result["success"] and await evaluate(run.session._internal.client, "document.querySelector('#hidden').files.length") == 1


async def test_native_download_is_retained_as_a_thread_owned_file(chrome):
    service, run = chrome
    await evaluate(run.session._internal.client, "document.body.innerHTML=`<a id=download download=report.txt>Download</a>`;"
        "document.querySelector('a').href=URL.createObjectURL(new Blob(['download evidence']));true")
    observed = await read(service)
    result = await act(service, observed, "click", selector="#download")
    assert result["success"], result
    for _ in range(50):
        downloads = service.state("t")["downloads"]
        if downloads and downloads[0].get("path"):
            break
        await asyncio.sleep(.05)
    from pathlib import Path

    assert downloads and downloads[0]["state"] == "completed", downloads
    assert Path(downloads[0]["path"]).is_relative_to(service.artifact_root / "t" / "downloads")
    assert Path(downloads[0]["path"]).read_text() == "download evidence"


async def test_visible_record_change_discards_queued_human_input_without_control_change(chrome):
    from deepseek_tui.browser.input import BrowserInput

    service, run = chrome
    await evaluate(run.session._internal.client, "document.body.innerHTML='<section data-record=A><input id=q></section>';true")
    await service.control("t", "user")
    scene = (await service.view("t"))["scene"]["scene_id"]
    await evaluate(run.session._internal.client, "document.querySelector('section').dataset.record='B';document.querySelector('input').focus();true")
    with pytest.raises(ValueError, match="page changed"):
        await service.input("t", BrowserInput(kind="text", text="OLD_RECORD_INPUT",
            generation=run.generation, scene_id=scene))
    assert await evaluate(run.session._internal.client, "document.querySelector('input').value") == ""


async def test_typing_survives_url_rewrites_but_not_record_changes(chrome):
    from deepseek_tui.browser.input import BrowserInput

    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML=`<section data-record=A><input id=q "
        "oninput=\"history.replaceState(null,'','?q='+this.value)\"></section>`;true")
    await service.control("t", "user")
    await service.action("t", BrowserAction(action="click", selector="#q", generation=run.generation),
                         actor="user")
    scene = (await service.view("t"))["scene"]["scene_id"]
    for ch in "hello":  # Each keystroke rewrites the URL before the next frame arrives.
        await service.input("t", BrowserInput(kind="text", text=ch, generation=run.generation,
                                              scene_id=scene))
    assert await evaluate(client, "document.querySelector('#q').value") == "hello"
    await evaluate(client, "document.querySelector('section').dataset.record='B';true")
    with pytest.raises(ValueError, match="page changed"):
        await service.input("t", BrowserInput(kind="text", text="!", generation=run.generation,
                                              scene_id=scene))
    assert await evaluate(client, "document.querySelector('#q').value") == "hello"


async def test_upload_and_prompt_are_captured_as_explicit_private_replay_inputs(chrome, tmp_path):
    import json
    from deepseek_tui.browser.workflows import start_recording, finish_recording, read_workflow, start_replay

    service, run = chrome
    path = tmp_path / "private-local-file.txt"
    path.write_text("private test file contents")
    await evaluate(run.session._internal.client, "document.body.innerHTML=`<input id=file type=file><button id=ask onclick=\"window.reply=prompt('Answer');\">Ask</button>`;true")
    await service.control("t", "user")
    started = await start_recording(service, "t")
    await service.action("t", BrowserAction(action="upload", selector="#file", files=[str(path)]), actor="user")
    await service.action("t", BrowserAction(action="click", selector="#ask"), actor="user")
    dialog = service.state("t")["dialog"]
    await service.action("t", BrowserAction(action="handle_dialog", dialog_id=dialog["id"], accept=True,
        text="PRIVATE_PROMPT_ANSWER"), actor="user")
    await finish_recording(run)
    doc = read_workflow(service, "t", started["recordingId"])
    assert [s.kind for s in doc.steps] == ["open", "upload", "click", "handle_dialog"], doc
    assert len(doc.inputs) == 2 and "PRIVATE_PROMPT_ANSWER" not in doc.model_dump_json()
    assert "private-local-file.txt" not in doc.model_dump_json()
    values = {s.value[2:-2]: json.dumps([str(path)]) if s.kind == "upload" else "replayed prompt"
        for s in doc.steps if s.kind in {"upload", "handle_dialog"}}
    await start_replay(service, "t", started["recordingId"], values)
    await asyncio.wait_for(run.demo_task, 30)
    assert run.demo_status == "passed", {"error": run.error, "doc": doc, "log": run.log}
    assert await evaluate(run.session._internal.client, "window.reply") == "replayed prompt"


async def test_real_multitab_recording_replays_with_logical_tab_aliases(chrome):
    from deepseek_tui.browser.workflows import start_recording, finish_recording, read_workflow, start_replay

    service, run = chrome
    await service.control("t", "user")
    first = next(t["tab_id"] for t in run.tabs if t["active"])
    started = await start_recording(service, "t")
    await service.action("t", BrowserAction(action="fill", selector="#q", text="first draft"), actor="user")
    await service.action("t", BrowserAction(action="new_tab", url=run.url), actor="user")
    await run.recorder._attach_known_targets()
    await run.recorder._sync_frames()
    await service.action("t", BrowserAction(action="fill", selector="#q", text="second draft"), actor="user")
    await service.action("t", BrowserAction(action="switch_tab", tab_id=first), actor="user")
    await service.action("t", BrowserAction(action="fill", selector="#q", text="final draft"), actor="user")
    await finish_recording(run)
    doc = read_workflow(service, "t", started["recordingId"])
    assert any(s.kind == "new_tab" for s in doc.steps) and any(s.kind == "switch_tab" for s in doc.steps), doc
    fills = [s for s in doc.steps if s.kind == "fill"]
    assert len(fills) == 3, doc
    inputs = {s.value[2:-2]: value for s, value in zip(fills, ["replayed first", "replayed second", "replayed final"], strict=True)}
    await start_replay(service, "t", started["recordingId"], inputs)
    await asyncio.wait_for(run.demo_task, 30)
    assert run.demo_status == "passed", {"error": run.error, "doc": doc, "log": run.log}
    assert set(run.replay_tabs) == {"main", "tab_1"}
    assert await evaluate(run.session._internal.client, "document.querySelector('#q').value") == "replayed final"
    await service.action("t", BrowserAction(action="switch_tab", tab_id=run.replay_tabs["tab_1"]))
    assert await evaluate(run.session._internal.client, "document.querySelector('#q').value") == "replayed second"


async def test_nested_recording_replays_shadow_frame_owner_and_last_native_input(chrome):
    import json
    from deepseek_tui.browser.input import BrowserInput
    from deepseek_tui.browser.workflows import start_recording, finish_recording, read_workflow, start_replay

    service, run = chrome
    client = run.session._internal.client
    url = run.url
    # The recording's start URL must recreate the fixture in replay, so use the existing
    # page and retain its current tab; replay's open reuses that exact task tab.
    inner = '<label for=q>Scoped draft</label><input id=q>'
    await evaluate(client, "document.body.innerHTML='<div id=host></div>';const h=document.querySelector('#host').attachShadow({mode:'open'});"
        "h.innerHTML='<iframe id=outer style=\"width:700px;height:350px\"></iframe>';h.querySelector('iframe').srcdoc=" +
        json.dumps('<iframe id=inner style="width:600px;height:200px"></iframe>') + ";true")
    for _ in range(50):
        if await evaluate(client, "!!document.querySelector('#host').shadowRoot.querySelector('iframe').contentDocument?.querySelector('#inner')"):
            break
        await asyncio.sleep(.02)
    await evaluate(client, "document.querySelector('#host').shadowRoot.querySelector('iframe').contentDocument.querySelector('#inner').srcdoc=" + json.dumps(inner) + ";true")
    path = [{"selector": "#outer", "shadowPath": ["#host"]}, "#inner"]
    await service.control("t", "user")
    started = await start_recording(service, "t")
    observed = (await service.action("t", BrowserAction(action="observe", frame_path=path), actor="user"))["observation"]
    await service.action("t", BrowserAction(action="click", ref=ref(observed, "Scoped draft"),
        observation_id=observed["observation_id"]), actor="user")
    await service.input("t", BrowserInput(kind="text", text="PRIVATE_FRAME_DRAFT", generation=run.generation))
    await finish_recording(run)
    doc = read_workflow(service, "t", started["recordingId"])
    fills = [s for s in doc.steps if s.kind == "fill"]
    assert len(fills) == 1 and len(fills[0].target["framePath"]) == 2, doc
    assert isinstance(fills[0].target["framePath"][0], dict)
    assert "PRIVATE_FRAME_DRAFT" not in doc.model_dump_json()
    await start_replay(service, "t", started["recordingId"], {fills[0].value[2:-2]: "replayed nested draft"})
    await asyncio.wait_for(run.demo_task, 30)
    assert run.demo_status == "passed", {"error": run.error, "doc": doc, "log": run.log}
    await service.action("t", BrowserAction(action="observe", frame_path=path))
    assert await evaluate(run.observation_context, "document.querySelector('#q').value") == "replayed nested draft"


async def test_nested_remote_renderers_keep_the_full_ancestor_input_chain(chrome):
    import json

    service, run = chrome
    port = 0
    async def serve(reader, writer):
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            body = (f'<iframe id=inner src="http://127.0.0.1:{port}/inner" style="width:600px;height:220px"></iframe>'.encode()
                if b'/outer ' in request else b'<label for=q>Remote nested draft</label><input id=q>')
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: ' + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
            await writer.drain()
        finally:
            writer.close()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        await evaluate(run.session._internal.client, "document.body.innerHTML='<div id=host></div>';"
            "const h=document.querySelector('#host').attachShadow({mode:'open'});h.innerHTML=" +
            json.dumps(f'<iframe id=outer src="http://localhost:{port}/outer" style="width:750px;height:350px"></iframe>') + ";true")
        path = [{"selector": "#outer", "shadowPath": ["#host"]}, "#inner"]
        for _ in range(40):
            try:
                observation = (await service.action("t", BrowserAction(action="observe", frame_path=path)))["observation"]
                if any(e["name"] == "Remote nested draft" for e in observation["elements"]):
                    break
            except RuntimeError:
                pass
            await asyncio.sleep(.05)
        result = await act(service, observation, "fill", ref=ref(observation, "Remote nested draft"), text="remote nested")
        assert result["success"], result
        assert await evaluate(run.observation_context, "document.querySelector('#q').value") == "remote nested"
        await evaluate(run.session._internal.client, "document.querySelector('#host').remove();true")
        rejected = await act(service, result["observation"], "fill", ref=ref(result["observation"], "Remote nested draft"), text="must not arrive")
        assert rejected["receipt"]["execution"] == "not_executed", rejected
    finally:
        server.close()
        await server.wait_closed()


async def test_close_session_returns_success(chrome):
    service, run = chrome
    result = await service.action("t", BrowserAction(action="close_session"))
    assert result["success"]


async def test_iframe_continuation(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        "document.querySelector('#frame').contentDocument.body.innerHTML='<div>'+('long content '.repeat(2000))+'</div>';true",
    )
    root = await read(service)
    first = await service.action(
        "t", BrowserAction(action="observe", frame_id=root["frames"][0]["frame_id"])
    )
    obs = first["observation"]
    assert obs["next_text_offset"] is not None
    second = await service.action(
        "t",
        BrowserAction(
            action="observe", scope_ref=obs["observation_id"], text_offset=obs["next_text_offset"]
        ),
    )
    assert second["success"]
    assert obs["text"] + second["observation"]["text"] == ("long content " * 2000).strip()
    await evaluate(run.observation_context, "document.body.append('changed');true")
    with pytest.raises(RuntimeError, match="Paging snapshot changed"):
        await service.action("t", BrowserAction(
            action="observe", scope_ref=second["observation"]["observation_id"], text_offset=1))


async def test_status_exposes_native_chooser(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client, "document.body.innerHTML='<input type=file id=f>';true"
    )
    obs = await read(service)
    await act(service, obs, "click", selector="#f")
    assert run.native_events.chooser
    from deepseek_tui.tools.browser import BrowserUseTool
    from deepseek_tui.tools.registry import ToolContext

    context = ToolContext(working_directory=run.directory, metadata={
        "browser_service": service, "runtime_thread_id": "t"})
    status = await BrowserUseTool().execute({"action": "status"}, context)
    assert status.metadata["browser"]["content"]["file_chooser"]["id"] == run.native_events.chooser["id"]


async def test_user_new_tab_installs_native_events(chrome):
    service, run = chrome
    await service.control("t", "user")
    await service.action("t", BrowserAction(action="new_tab", url=run.url), actor="user")
    assert run.session._internal.client in run.native_events.clients


async def test_approval_changes_with_recipient(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "document.body.innerHTML='<form><label>Recipient<input id=to value=alice></label><button id=send type=button>Send</button></form>';true",
    )
    first = await read(service)
    args = {"action": "click", "selector": "#send", "observation_id": first["observation_id"]}
    original = service.approval_fingerprint("t", args, "same-task")
    await evaluate(client, "document.querySelector('#to').value='bob';true")
    second = await read(service)
    args["observation_id"] = second["observation_id"]
    changed = service.approval_fingerprint("t", args, "same-task")
    assert original != changed, "Different recipient reuses same approval fingerprint"


@pytest.mark.parametrize("switch_back", [False, True])
async def test_human_dialog_on_new_tab(chrome, switch_back):
    from deepseek_tui.browser.input import BrowserInput

    service, run = chrome
    await service.control("t", "user")
    await service.action("t", BrowserAction(action="new_tab", url=run.url), actor="user")
    if switch_back:
        original = next(tab["tab_id"] for tab in run.tabs if not tab.get("active"))
        await service.action("t", BrowserAction(action="switch_tab", tab_id=original), actor="user")
    await evaluate(
        run.session._internal.client,
        "document.body.innerHTML=`<button onclick=\"window.answer=confirm('Confirm?')\">Ask</button>`;true",
    )
    box = await evaluate(
        run.session._internal.client,
        "(()=>{const r=document.querySelector('button').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()",
    )
    for event in ["mousePressed", "mouseReleased"]:
        result = await service.input(
            "t",
            BrowserInput(
                kind="mouse", event=event, button="left", generation=run.generation, **box
            ),
        )
    assert run.native_events.dialog, result
    await service.action("t", BrowserAction(action="handle_dialog",
        dialog_id=run.native_events.dialog["id"], accept=True), actor="user")
    assert await evaluate(run.session._internal.client, "window.answer") is True
    assert not run.unresolved


async def test_new_tab_captures_dialog_during_navigation(chrome, monkeypatch):
    import sys

    service, run = chrome
    monkeypatch.setattr(sys.modules[__name__], "PAGE",
        b"<!doctype html><script>window.answer=confirm('On load')</script>")
    result = await service.action("t", BrowserAction(action="new_tab", url=run.url))
    assert result["dialog"]["message"] == "On load"
    await service.action("t", BrowserAction(action="handle_dialog",
        dialog_id=result["dialog"]["id"], accept=True))
    assert await evaluate(run.session._internal.client, "window.answer") is True


async def test_hidden_scoped_text_after_removal(chrome):
    service, run = chrome
    await evaluate(
        run.session._internal.client,
        "document.body.innerHTML='<div id=loading>Loading</div>';setTimeout(()=>document.querySelector('#loading').remove(),100);true",
    )
    result = await service.action(
        "t",
        BrowserAction(
            action="wait", selector="#loading", text="Loading", wait_state="hidden", timeout_ms=500
        ),
    )
    assert result["success"], result


async def test_human_handoff_reconciles_real_page_and_invalidates_old_actions(chrome):
    import json
    from types import SimpleNamespace
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.server.threads.manager import RuntimeThreadManager

    service, run = chrome
    before = await service.action("t", BrowserAction(action="observe"))
    old_id = before["observation"]["observation_id"]
    manager = RuntimeThreadManager.__new__(RuntimeThreadManager)
    manager.browser_service = service
    handle = EngineHandle()
    handle._mark_turn_active()
    manager._active = {"t": SimpleNamespace(handle=handle, active_turn=SimpleNamespace(turn_id="turn"))}
    await manager.control_browser("t", "user", run.generation)
    await run.session._internal.client.send("Runtime.evaluate", {
        "expression": "document.querySelector('#result').textContent='MANUAL_DONE'",
        "returnByValue": True,
    })
    await manager.control_browser("t", "agent", run.generation)
    assert not handle.pause.paused
    assert "MANUAL_DONE" in handle.resume_context
    report = json.loads(handle.resume_context.split("Resume reconciliation:\n")[1].split("\nFresh browser observation:")[0])
    assert report["visible_text_changed"] is True
    assert run.latest_observation["observation_id"] != old_id
    rejected = await service.action(
        "t", BrowserAction(action="click", selector="#search", observation_id=old_id),
        require_observation=True,
    )
    assert not rejected["success"], rejected
    assert rejected["receipt"]["execution"] == "not_executed"
    assert "MANUAL_DONE" in rejected["observation"]["text"]


@pytest.mark.parametrize("focus_changes", [False, True])
async def test_press_recovers_inactive_page_focus_then_revalidates(chrome, monkeypatch, focus_changes):
    from unittest.mock import AsyncMock
    import deepseek_tui.browser.service as module

    service, run = chrome
    client = run.session._internal.client
    await evaluate(
        client,
        "document.addEventListener('keydown', e => { if(e.key==='Escape') document.querySelector('#result').textContent='ESCAPED'; }); true",
    )
    observation = await read(service)
    original = module.target
    calls = 0

    async def target_with_lost_focus(run, action):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"error": "focus_not_active"}
        if calls == 2 and focus_changes:
            await evaluate(client, "document.querySelector('#q').focus(); true")
        return await original(run, action)

    send = AsyncMock(wraps=client.send)
    monkeypatch.setattr(client, "send", send)
    monkeypatch.setattr(module, "target", target_with_lost_focus)
    result = await act(service, observation, "press", key="Escape")
    assert result["success"] is not focus_changes, result
    assert calls >= 2
    assert any(c.args[0] == "Page.bringToFront" for c in send.call_args_list)
    assert await evaluate(client, "document.querySelector('#result').textContent") == (
        "" if focus_changes else "ESCAPED"
    )
    if focus_changes:
        assert result["receipt"]["execution"] == "not_executed"
        assert result["receipt"]["reason"] == "focus_changed"


async def test_scroll_outside_list_reports_no_observed_movement(chrome):
    service, run = chrome
    await evaluate(run.session._internal.client,
        "document.body.innerHTML=`<div id=box style='width:100px;height:100px;overflow:auto'>"
        "<div style='height:3000px'>Content</div></div>`;true")
    result = await act(service, await read(service), "scroll", amount=300)
    assert result["success"]  # Dispatch succeeded; effect did not.
    assert result["receipt"]["execution"] == "executed"
    assert result["receipt"]["effect"] == "not_confirmed"
    assert "outside the list" in result["content"]


async def test_missing_observation_is_not_reported_as_expired(chrome):
    service, run = chrome
    result = await service.action("t", BrowserAction(action="scroll"), require_observation=True)
    assert not result["success"]
    assert result["receipt"]["reason"] == "missing_observation_id"
    assert result["receipt"]["execution"] == "not_executed"
    assert result["observation"]["observation_id"]


async def test_review_coordinate_rejects_reused_control_for_other_record(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML=`<section data-record=A><span id=label style='position:absolute;left:20px;top:20px'>Record A</span><button style='position:absolute;left:100px;top:100px;width:120px;height:40px' onclick='window.deleted=this.parentElement.dataset.record'>Delete</button></section>`;window.deleted=null;true")
    capture = await service.action('t', BrowserAction(action='screenshot'))
    await evaluate(client, "document.querySelector('section').dataset.record='B';document.querySelector('#label').textContent='Record B';true")
    result = await act(service, capture['observation'], 'click', x=160, y=120)
    deleted = await evaluate(client, "window.deleted || ''")
    assert deleted == '', f'Wrong record deleted: {deleted}; receipt={result["receipt"]}'

@pytest.mark.parametrize("change_url", [True, False])
async def test_review_typing_rejects_changed_record_without_data_attributes(chrome, change_url):
    from deepseek_tui.browser.input import BrowserInput
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML=`<form><label id=who>Customer A</label><input id=q></form>`;history.replaceState(null,'','?customer=A');true")
    await service.control('t', 'user')
    await service.action('t', BrowserAction(action='click', selector='#q', generation=run.generation), actor='user')
    scene = (await service.view('t'))['scene']['scene_id']
    await evaluate(client, "document.querySelector('#who').textContent='Customer B';"
                   + ("history.replaceState(null,'','?customer=B');" if change_url else "") + "true")
    try:
        await service.input('t', BrowserInput(kind='text', text='private A note', generation=run.generation, scene_id=scene))
    except ValueError:
        pass
    value = await evaluate(client, "document.querySelector('#q').value")
    assert value == '', f'Queued input entered changed customer form: {value}'


async def test_human_click_then_typing_keeps_scene_binding(chrome):
    from deepseek_tui.browser.input import BrowserInput

    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML=`<form><label>Search</label>"
                   "<input id=q style='position:absolute;left:100px;top:100px;width:200px;height:40px'>"
                   "</form>`;true")
    await service.control("t", "user")
    scene = (await service.view("t"))["scene"]["scene_id"]
    for event in ("mousePressed", "mouseReleased"):
        await service.input("t", BrowserInput(kind="mouse", event=event, x=150, y=120,
                            button="left", generation=run.generation, scene_id=scene))
    for text in "hello":
        await service.input("t", BrowserInput(kind="text", text=text,
                            generation=run.generation, scene_id=scene))
    assert await evaluate(client, "document.querySelector('#q').value") == "hello"


async def test_shared_form_scope_scanned_once_per_scene(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, "document.body.innerHTML='<form><h2>Customer A</h2>'+"
                   "'<label>Field<input></label>'.repeat(100)+'</form>';true")
    from deepseek_tui.browser.observation import root_context
    context = await root_context(run)
    await evaluate(context, "window.auditScopeWalks=0;const original=document.createTreeWalker;"
                   "document.createTreeWalker=function(...args){window.auditScopeWalks++;"
                   "return original.apply(this,args)};true")
    first = await service._scene(run)
    assert await evaluate(context, "window.auditScopeWalks") == 1
    await evaluate(client, "document.querySelector('h2').textContent='Customer B';true")
    second = await service._scene(run)
    assert first["scene_id"] != second["scene_id"]
    assert await evaluate(context, "window.auditScopeWalks") == 2
