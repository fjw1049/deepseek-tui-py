"""Browser module: actions, isolation, takeover, recording and tool approvals."""

import asyncio
import base64
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import ValidationError

from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService
from deepseek_tui.tools.approval import build_approval_key
from deepseek_tui.tools.browser import BrowserUseTool
from deepseek_tui.tools.registry import ApprovalRequirement, ToolContext


def fake_session():
    output = io.BytesIO()
    Image.new("RGB", (1200, 760), "white").save(output, format="JPEG")
    result = SimpleNamespace(success=True, content="done", error=None)
    async def send(method, params=None):
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 1}
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "main", "loaderId": "doc", "url": "https://example.test"}}}
        if method == "Runtime.evaluate":
            if "function textFrom" in params["expression"]:
                import json

                args = json.loads(params["expression"].rsplit("})(", 1)[1][:-1])
                result = await session.eval_js(params["expression"])
                body = json.loads(result.content) if result.success else None
                passed = isinstance(body, str) and args["text"] in body
                if args["state"] == "hidden":
                    passed = not passed
                return {"result": {"value": passed}}
            if "const s=window.__deepseekObservation" in params["expression"]:
                return {"result": {"value": {}}}
            if "const refs = new Map" in params["expression"]:
                return {"result": {"value": {"url": "https://example.test", "text": "Saved", "elements": []}}}
            return {"result": {"value": True}}
        return {"data": base64.b64encode(output.getvalue()).decode()}
    session = SimpleNamespace(
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
                send=AsyncMock(side_effect=send, return_value={"data": base64.b64encode(output.getvalue()).decode()})
            )
        ),
    )
    return session


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
async def test_frame_reports_current_page_and_export_preserves_assertions(browser):
    import json
    import zipfile

    run = browser.runs["one"]
    original = run.session._internal.client.send.return_value
    original_handler = run.session._internal.client.send.side_effect
    run.session._internal.client.send.side_effect = [
        {"frameTree": {"frame": {"url": "http://localhost/redirected#section"}}}, original
    ]
    await browser.frame("one")
    assert browser.state("one")["url"] == "http://localhost/redirected#section"
    run.session._internal.client.send.side_effect = original_handler
    await browser.action("one", BrowserAction(action="check_text", text="Missing"))
    await browser.close("one")
    with zipfile.ZipFile(browser.export_evidence("one")) as archive:
        report = json.loads(archive.read("report.json"))
        assert report["verification"] == "failed"
        assert report["assertions"][-1]["expected"] == "Missing"
        assert report["artifacts"][0]["id"] in archive.namelist()
        assert "path" not in report["artifacts"][0]
    with pytest.raises(ValueError, match="No browser evidence"):
        browser.export_evidence("two")


@pytest.mark.asyncio
async def test_export_does_not_claim_business_success_for_actions_only(browser):
    import json
    import zipfile

    await browser.action("one", BrowserAction(action="click", selector="#save"))
    with zipfile.ZipFile(browser.export_evidence("one")) as archive:
        assert json.loads(archive.read("report.json"))["verification"] == "not_checked"
    browser.runs["one"].demo_status = "running"
    with pytest.raises(ValueError, match="finish"):
        browser.export_evidence("one")


@pytest.mark.asyncio
async def test_video_records_between_actions_and_close_finalizes(browser, monkeypatch):
    import shutil

    from deepseek_tui.browser.video import BrowserVideo

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is required for video encoding")
    run = browser.runs["one"]
    await browser.action("one", BrowserAction(action="video_start"))
    with pytest.raises(ValueError, match="already recording"):
        await browser.action("one", BrowserAction(action="video_start"))
    with pytest.raises(ValueError, match="Stop recording"):
        browser.export_evidence("one")
    async with run.lock:
        await asyncio.sleep(0.7)
        assert run.video.frames >= 2
    video = run.video
    await browser.close("one")
    assert video.task.done() and video.process.returncode == 0
    artifact = browser.state("one")["artifacts"][-1]
    assert browser.artifact("one", artifact["id"]).read_bytes().startswith(b"\x1aE\xdf\xa3")
    monkeypatch.setattr("deepseek_tui.browser.video.shutil.which", lambda _: None)
    with pytest.raises(ValueError, match="FFmpeg"):
        await BrowserVideo(run.directory / "missing.webm", lambda: browser._capture(run)).start()


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
    assert run.log[-1]["action"] == "click" and not run.log[-1]["success"]
    assert run.log[-1]["execution"] == "unknown"
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
    session.click.assert_awaited_once_with(ref=None, selector="#notify")
    await browser.action("one", BrowserAction(action="select", selector="#plan", text="pro"))
    session.select.assert_awaited_once_with(value="pro", selector="#plan", ref=None)


def test_replay_opens_only_web_pages():
    from deepseek_tui.browser import workflows

    assert workflows._url("https://example.com") == "https://example.com"
    with pytest.raises(ValidationError):
        workflows._url((Path(workflows.__file__).parent / "page.html").as_uri())


@pytest.mark.asyncio
async def test_workflow_preflight_and_takeover(browser, monkeypatch):
    from deepseek_tui.browser import workflows as flows

    models = pytest.importorskip("octop_browser.record.models")
    doc = models.StepsDocument(
        recordingId="rec_test",
        steps=[models.SemanticStep(id="1", kind="unsupported", url="https://example.com")],
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
    dispatched = asyncio.Event()
    hold = asyncio.Event()
    original_step = flows._step

    async def blocked_step(*args):
        dispatched.set()
        await hold.wait()
        return await original_step(*args)

    monkeypatch.setattr(flows, "_step", blocked_step)
    await flows.start_replay(browser, "one", "rec_test", {})
    await dispatched.wait()
    await browser.control("one", "user")
    assert browser.state("one")["demo_status"] == "stopped"
    assert browser.runs["one"].session.press.await_count < 4
    assert browser.state("two")["log"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,value,key,error",
    [
        ("press", None, "UnsupportedKey", "Unsupported"),
        ("set_checked", "maybe", None, "Checkbox"),
        ("set_checked", "{{confirmation}}", None, "Missing"),
    ],
)
async def test_workflow_rejects_invalid_later_input_before_taking_control(
    browser, monkeypatch, kind, value, key, error
):
    from octop_browser.record.models import SemanticStep, StepsDocument

    from deepseek_tui.browser import workflows

    doc = StepsDocument(
        recordingId="rec_invalid",
        steps=[
            SemanticStep(id="1", kind="click", target={"selectorCandidates": ["#save"]}),
            SemanticStep(
                id="2", kind=kind, value=value, key=key, target={"selectorCandidates": ["#q"]}
            ),
        ],
    )
    monkeypatch.setattr(workflows, "read_workflow", lambda *args: doc)
    await browser.control("one", "user")
    run = browser.runs["one"]
    generation = run.generation
    with pytest.raises(ValueError, match=error):
        await workflows.start_replay(browser, "one", "rec_invalid", {})
    assert run.owner == "user" and run.generation == generation and run.demo_task is None
    run.session.click.assert_not_called()


def test_profile_preferences_require_closed_session_and_survive_restart(browser):
    with pytest.raises(ValueError, match="End"):
        browser.configure("one", True)
    with pytest.raises(ValueError, match="End"):
        browser.clear_profile("one")
    browser.configure("saved", True)
    restarted = BrowserService(browser.artifact_root)
    assert restarted.preferences("saved") == {"persistent": True}
    assert restarted.preferences("other") == {"persistent": True}
    browser.configure("temporary", False)
    assert restarted.preferences("temporary") == {"persistent": False}


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
        {"action": "click", "x": 2400, "y": 1},
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


SETTINGS_PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Settings</title>
<input id="name" type="text"><label><input id="notifications" type="checkbox"> Notify</label>
<button id="save">Save</button><div id="status" role="status"></div>
<script>document.querySelector('#save').onclick=()=>{document.querySelector('#status')
.textContent='已保存：'+document.querySelector('#name').value}</script></html>"""


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_real_record_replay_and_persistent_profile(tmp_path):
    import functools
    import http.server
    import json
    import os
    import threading

    from deepseek_tui.browser.workflows import (
        finish_recording,
        read_workflow,
        start_recording,
        start_replay,
    )

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    (tmp_path / "settings.html").write_text(SETTINGS_PAGE, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmp_path)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/settings.html"
    service = BrowserService(tmp_path / "artifacts")
    service.configure("flow", True)
    assert service.environment()["ready"]
    try:
        run = await service.ensure("flow")
        await run.session.navigate(url)
        await service.control("flow", "user")
        await start_recording(service, "flow")
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
        httpd.shutdown()


async def test_status_without_start_and_during_takeover(browser):
    result = await browser.action("new", BrowserAction(action="status"))
    assert result["content"]["active"] is False
    assert "new" not in browser.runs
    browser.runs["one"].agent_task = True  # The takeover happens during the agent's task.
    await browser.control("one", "user")
    browser.runs["one"].session._internal.client.send.side_effect = None
    browser.runs["one"].session._internal.client.send.return_value = {
        "frameTree": {"frame": {"url": "https://example.test/after-login"}}
    }
    result = await browser.action("one", BrowserAction(action="status"))
    assert result["content"] == {
        "active": True,
        "owner": "user",
        "url": "https://example.test/after-login",
        "viewport": {"width": 1200, "height": 760},
        "unresolved": [], "unresolved_total": 0, "next_operation_offset": None,
    }
    with pytest.raises(ValueError, match="user controls this browser.*request_user_input"):
        await browser.action("one", BrowserAction(action="reload"))


@pytest.mark.parametrize("action", ["switch_tab", "hover", "wait"])
def test_browser_requires_grounded_targets(action):
    with pytest.raises(ValidationError):
        BrowserAction(action=action)


async def test_navigation_wait_and_tabs_use_owned_session(browser):
    session = browser.runs["one"].session
    result = SimpleNamespace(success=True, content="ok", error=None)
    session.list_tabs = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            content="[popup] Login",
            error=None,
            metadata={
                "tabs": [{"tab_id": "popup", "url": "https://example.test", "title": "Login"}]
            },
        )
    )
    session.switch_tab = AsyncMock(return_value=result)
    session.wait = AsyncMock(return_value=result)
    session.hover = AsyncMock(return_value=result)
    session.reload = AsyncMock(return_value=result)
    session.type = AsyncMock(return_value=result)
    tabs = await browser.action("one", BrowserAction(action="tabs"))
    assert tabs["tabs"][0]["tab_id"] == "popup"
    await browser.action("one", BrowserAction(action="switch_tab", tab_id="popup"))
    session.switch_tab.assert_awaited_once_with("popup")
    async def observed(method, params=None):
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 2}
        if method == "Runtime.evaluate":
            if "const nodes=" in params["expression"]:
                return {"result": {"value": True}}
            return {"result": {"value": {"text": "ready", "elements": [], "url": "https://example.test"}}}
        return {"frameTree": {"frame": {"id": "popup", "loaderId": "doc"}}}
    session._internal.client.send.side_effect = observed
    await browser.action("one", BrowserAction(action="wait", selector="#ready"))
    session.wait.assert_not_called()
    await browser.action("one", BrowserAction(action="hover", ref="ref_1",
        observation_id=browser.runs["one"].latest_observation["observation_id"]))
    session.hover.assert_awaited_once_with(ref="ref_1")
    await browser.action("one", BrowserAction(action="type", text="中文"))
    assert any(
        call.args == ("Input.insertText", {"text": "中文"})
        for call in session._internal.client.send.await_args_list
    )
    observation = await browser.action("one", BrowserAction(action="observe"))
    assert observation["observation"]["text"] == "ready"
    await browser.action("one", BrowserAction(action="observe", level="full"))
    session.dom_tree.assert_not_called()
    session._internal.client.send.side_effect = ConnectionError("disconnected after reload")
    completed = await browser.action("one", BrowserAction(action="reload"))
    assert completed["success"] and completed["page"]["stale"]
    session.reload.assert_awaited_once()


@pytest.mark.parametrize("vision", [False, True])
async def test_screenshot_and_failure_evidence_respect_model_capability(
    browser, tmp_path, vision, monkeypatch
):
    import json

    from deepseek_tui.config.models import Config, ProviderConfig

    monkeypatch.setattr("deepseek_tui.media.user_media_dir", lambda: tmp_path / "media")
    config = Config(providers={"deepseek": ProviderConfig(image_input=vision)})
    context = ToolContext(
        working_directory=tmp_path,
        metadata={
            "browser_service": browser,
            "runtime_thread_id": "one",
            "task_config": config,
            "task_model": "deepseek-chat",
        },
    )
    for action in ({"action": "screenshot"}, {"action": "check_text", "text": "missing"}):
        result = await BrowserUseTool().execute(action, context)
        payload = json.loads(result.content)
        assert Path(payload["artifact"]["path"]).exists()
        assert bool(result.images) is vision
        assert payload["vision_available"] is vision


async def test_unknown_model_keeps_evidence_without_injecting_images(browser, tmp_path):
    context = ToolContext(
        working_directory=tmp_path,
        metadata={
            "browser_service": browser,
            "runtime_thread_id": "one",
        },
    )
    result = await BrowserUseTool().execute({"action": "screenshot"}, context)
    assert result.success and not result.images


async def test_scoped_assertion_does_not_accept_missing_region(browser):
    session = browser.runs["one"].session
    session.eval_js.return_value = SimpleNamespace(success=True, content="null")
    result = await browser.action(
        "one", BrowserAction(action="check_text", selector="#current-record", text="Saved")
    )
    assert not result["success"]
    assert "els.length !== 1" in session.eval_js.call_args.args[0]
    assert "#current-record" in session.eval_js.call_args.args[0]


@pytest.mark.e2e
async def test_real_browser_tabs_wait_and_focused_unicode_input(tmp_path):
    import json
    import os

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    page = (b'<title>Browser task</title><input id="name">'
            b'<div id="old">Saved</div><div id="current">Pending</div>')

    async def serve(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: "
            + str(len(page)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + page
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    service = BrowserService(tmp_path / "browser")
    try:
        result = await service.action("task", BrowserAction(action="open", url=url))
        assert result["success"] and result["page"]["url"].rstrip("/") == url
        tabs = await service.action("task", BrowserAction(action="tabs"))
        first = next(tab["tab_id"] for tab in tabs["tabs"] if tab["active"])
        await service.action("task", BrowserAction(action="new_tab", url=url + "/second"))
        await service.action("task", BrowserAction(action="switch_tab", tab_id=first))
        wait = await service.action("task", BrowserAction(action="wait", selector="#name"))
        assert wait["success"]
        await service.control("task", "user")
        await service.action("task", BrowserAction(action="click", selector="#name"), actor="user")
        await service.action(
            "task", BrowserAction(action="fill", selector=":focus", text="中文粘贴"), actor="user"
        )
        await service.action("task", BrowserAction(action="type", text="输入"), actor="user")
        value = await service.runs["task"].session.eval_js('document.querySelector("#name").value')
        assert json.loads(value.content) == "中文粘贴输入"
        await service.control("task", "agent")
        check = await service.action(
            "task", BrowserAction(action="check_text", selector="#current", text="Saved")
        )
        assert not check["success"]
        state = await service.action("task", BrowserAction(action="status"))
        assert state["content"]["owner"] == "agent"
    finally:
        await service.close_all()
        server.close()
        await server.wait_closed()


async def test_image_attachment_error_does_not_reverse_success(browser, tmp_path, monkeypatch):
    import json

    from deepseek_tui.config.models import Config, ProviderConfig

    def fail_import(data):
        raise OSError("media unavailable")

    monkeypatch.setattr("deepseek_tui.media.import_image", fail_import)
    context = ToolContext(working_directory=tmp_path, metadata={
        "browser_service": browser, "runtime_thread_id": "one",
        "task_config": Config(providers={"deepseek": ProviderConfig(image_input=True)}),
    })
    result = await BrowserUseTool().execute({"action": "screenshot"}, context)
    assert result.success and not result.images
    assert "image_warning" in json.loads(result.content)


@pytest.mark.asyncio
async def test_missing_browser_dependency_reports_actual_runtime(tmp_path, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "octop_browser", None)
    service = BrowserService(tmp_path / "artifacts")
    with pytest.raises(ValueError) as error:
        await service.ensure("missing")
    assert sys.executable in str(error.value)
    if sys.version_info >= (3, 11):
        assert "dependency could not be imported" in str(error.value)
        assert "requires Python 3.11+" not in str(error.value)
    assert "missing" not in service.runs


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_real_new_tab_cold_start(tmp_path):
    import os

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    service = BrowserService(tmp_path / "artifacts")
    try:
        result = await service.action("cold-start", BrowserAction(action="new_tab"))
        assert result["success"], result
        assert service.state("cold-start")["active"]
        assert (await service.frame("cold-start")).startswith("data:image/jpeg;base64,")
    finally:
        await service.close_all()


@pytest.mark.parametrize("action", ["open", "new_tab", "switch_tab", "back", "forward",
                                     "reload", "hover", "scroll", "screenshot"])
def test_navigation_and_inspection_do_not_prompt_for_approval(action):
    assert BrowserUseTool().approval_requirement_for_input({"action": action}) == ApprovalRequirement.AUTO


async def test_reading_does_not_invalidate_approval_scope(browser):
    scope = browser.approval_scope("one")
    await browser.action("one", BrowserAction(action="observe"))
    assert browser.approval_scope("one") == scope


async def test_replay_evidence_failure_preserves_success(browser, monkeypatch):
    from deepseek_tui.browser import workflows

    run = browser.runs["one"]
    document = SimpleNamespace(steps=[], verification=[])
    monkeypatch.setattr(browser, "stop_video", AsyncMock(side_effect=OSError("video unavailable")))
    await workflows._replay(browser, run, document, {})
    assert run.demo_status == "passed"
    assert not run.recording
    assert any(item["action"] == "evidence" and not item["success"] for item in run.log)


async def test_close_session_returns_list_of_persisted_unresolved_operations(browser):
    run = browser.runs["one"]
    run.unresolved["pending"] = {"action_id": "pending", "execution": "unknown"}
    result = await browser.action("one", BrowserAction(action="close_session"))
    assert result["success"]
    assert result["content"]["unresolved"] == [run.unresolved["pending"]]
    assert browser.state("one")["unresolved"] == [run.unresolved["pending"]]


async def test_session_cap_reclaims_only_the_longest_idle_unused_session(tmp_path):
    import time

    service = BrowserService(tmp_path / "artifacts")
    now = time.monotonic()
    for index in range(8):
        directory = tmp_path / f"run{index}"
        directory.mkdir()
        run = BrowserRun(f"t{index}", directory)
        run.last_used = now - 60  # Recently used.
        service.runs[run.thread_id] = run
    service.runs["t1"].last_used = now - 3600
    service.runs["t1"].owner = "user"  # The user may come back to a page they hold.
    service.runs["t2"].last_used = now - 1800
    service.runs["t3"].last_used = now - 2400
    service.runs["t3"].recording = True
    await service._reclaim_idle_session()
    assert set(service.runs) == {f"t{i}" for i in range(8)} - {"t2"}
    service.runs["t2"] = BrowserRun("t2", tmp_path / "run2")
    with pytest.raises(ValueError, match="maximum 8"):
        await service._reclaim_idle_session()
    service.runs["t1"].handed_back = True  # Only handed back after a task, never taken over.
    await service._reclaim_idle_session()
    assert "t1" not in service.runs


async def test_navigation_does_not_import_chrome_cookies(browser, monkeypatch):
    monkeypatch.setattr("deepseek_tui.browser.cookies.profiles", lambda: [{"id": "Default"}])
    browser.cookies.configure("enabled", "Default")
    browser.cookies.read_source = AsyncMock(side_effect=AssertionError("Explicit import only"))
    result = await browser.action("one", BrowserAction(action="open", url="https://example.test"))
    assert result["success"]
    browser.cookies.read_source.assert_not_called()

@pytest.mark.parametrize('action,target,resolved', [
    ('open', 'https://example.test', True),
    ('open', 'https://other.test', False),
    ('click', 'https://example.test', False),
    ('open', None, False),
])
async def test_fresh_observation_only_resolves_visible_navigation_target(browser, action, target, resolved):
    run = browser.runs['one']
    receipt = {'action_id': 'pending', 'action': action, 'execution': 'unknown', 'target_url': target}
    run.unresolved['pending'] = dict(receipt)
    run.operations['pending'] = {'success': False, 'receipt': dict(receipt)}
    result = await browser.action('one', BrowserAction(action='observe'))
    assert result['success']
    assert ('pending' not in run.unresolved) == resolved
    if resolved:
        assert run.operations['pending']['receipt']['execution'] == 'unknown'
        assert run.operations['pending']['receipt']['reconciliation']['outcome'] == 'target_visible'


@pytest.mark.parametrize("incomplete", [False, True])
async def test_returning_control_ends_the_user_demonstration(browser, monkeypatch, incomplete):
    from deepseek_tui.browser import workflows

    async def finish(run):
        run.recorder = None
        if incomplete:
            raise ValueError("Recording contains incomplete browser capture")
        return {"recordingId": "rec_demo", "steps": 1}

    monkeypatch.setattr(workflows, "finish_recording", finish)
    run = browser.runs["one"]
    run.owner, run.recorder = "user", object()
    state = await browser.control("one", "agent")
    assert run.owner == "agent" and run.recorder is None
    assert any(entry.get("error") for entry in run.log) == incomplete
    # The user gets the result to review, as after finishing the demonstration themselves.
    assert state["demonstration"] == ({"error": "Recording contains incomplete browser capture"}
                                      if incomplete else {"recordingId": "rec_demo", "steps": 1})
    assert "demonstration" not in await browser.control("one", "user")


async def test_close_keeps_gif_evidence_when_demonstration_capture_is_incomplete(
    browser, monkeypatch
):
    from deepseek_tui.browser import workflows

    async def finish(run):
        run.recorder = None
        raise ValueError("Recording contains incomplete browser capture")

    monkeypatch.setattr(workflows, "finish_recording", finish)
    run = browser.runs["one"]
    output = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(output, format="JPEG")
    run.recorder, run.recording, run.frames = object(), True, [output.getvalue()]
    await browser.close("one")
    assert "one" not in browser.runs
    assert [item["label"] for item in browser.state("one")["artifacts"]] == ["操作动图"]


@pytest.mark.parametrize("owner", ["user", "agent"])
async def test_agent_capture_survives_handoffs_and_is_not_a_user_demonstration(
    browser, monkeypatch, owner
):
    from deepseek_tui.browser import workflows

    finish = AsyncMock()
    monkeypatch.setattr(workflows, "finish_recording", finish)
    run = browser.runs["one"]
    run.owner = "user" if owner == "agent" else "agent"
    run.recorder = SimpleNamespace(actor="agent")
    assert browser.state("one")["workflow_recording"] is False
    await browser.control("one", owner)
    assert run.recorder is not None and not finish.called


async def test_new_agent_task_takes_over_browsing_but_not_user_work(browser):
    browsed, demonstrating = browser.runs["one"], browser.runs["two"]
    await browser.control("one", "user")  # The user browsed before asking the agent.
    await browser.action("one", BrowserAction(action="status"))
    assert browsed.owner == "agent" and browsed.agent_task
    await browser.control("two", "user")
    demonstrating.recorder = SimpleNamespace(actor="user")
    with pytest.raises(ValueError, match="user controls this browser"):
        await browser.action("two", BrowserAction(action="reload"))
    assert demonstrating.owner == "user" and demonstrating.agent_task


async def test_stop_loading_bypasses_a_running_navigation(browser):
    from deepseek_tui.browser.input import BrowserInput

    run = browser.runs["one"]
    await browser.control("one", "user")
    async with run.lock:  # An open action is still waiting for its page.
        result = await browser.input("one", BrowserInput(kind="stop", generation=run.generation))
    assert result == {"success": True}
    run.session._internal.client.send.assert_any_await("Page.stopLoading")
    with pytest.raises(ValueError, match="control changed"):
        await browser.input("one", BrowserInput(kind="stop", generation=run.generation - 1))


async def test_view_reports_main_frame_loading(tmp_path):
    from deepseek_tui.browser.native import NativeBrowserEvents

    handlers = {}

    class Client:  # Hashable, like the CDP client the native events track.
        send = AsyncMock(return_value={"frameTree": {"frame": {"id": "main", "loaderId": "doc"}}})

        def on(self, event, callback):
            handlers[event] = callback

    client = Client()
    run = SimpleNamespace(thread_id="one", native=False, generation=0, session=SimpleNamespace(
        _internal=SimpleNamespace(client=client)))
    native = NativeBrowserEvents(run, BrowserService(tmp_path))
    await native.install(client)
    handlers["Page.frameStartedLoading"]({"frameId": "child"})
    assert native.state()["loading"] is False
    handlers["Page.frameStartedLoading"]({"frameId": "main"})
    assert native.state()["loading"] is True
    handlers["Page.frameStoppedLoading"]({"frameId": "main"})
    assert native.state()["loading"] is False


async def test_temporary_session_never_attaches_shared_workbench(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from deepseek_tui.browser.service import BrowserService

    browser = BrowserService(tmp_path)
    browser.configure("private", False)
    browser.workbench = {"port": 1, "token": "unused"}
    attach = AsyncMock(return_value=True)
    monkeypatch.setattr(browser, "_attach_workbench", attach)
    with pytest.raises(ValueError, match="Workbench browser is unavailable"):
        await browser.ensure("private", native_only=True)
    attach.assert_not_awaited()
    assert browser.state("private")["persistent"] is False
    with pytest.raises(ValueError, match="temporary"):
        await browser.sync_cookies("private")


async def test_native_download_reconciles_after_tab_connection_changes(tmp_path):
    from deepseek_tui.browser.native import NativeBrowserEvents
    from deepseek_tui.browser.service import BrowserRun

    service = BrowserService(tmp_path)
    run = BrowserRun("one", tmp_path / "one", native=True)
    directory = tmp_path / "one" / "downloads"
    directory.mkdir(parents=True)
    saved = directory / "download-id"
    saved.write_bytes(b"complete")

    class Client:
        def __init__(self):
            self.handlers = {}

        async def send(self, method, params=None):
            if method == "Workbench.getDownloads":
                return {
                    "downloads": [
                        {
                            "begin": {"guid": "download-id", "suggestedFilename": "invoice.pdf"},
                            "progress": {
                                "guid": "download-id",
                                "state": "completed",
                                "receivedBytes": 8,
                            },
                        }
                    ]
                }
            return {"frameTree": {"frame": {"id": "main", "loaderId": "doc"}}}

        def on(self, event, callback):
            self.handlers[event] = callback

    client = Client()
    run.session = SimpleNamespace(_internal=SimpleNamespace(client=client))
    service.runs["one"] = run
    native = NativeBrowserEvents(run, service)
    await native.install(client)
    assert native.state()["downloads"][0]["path"] == str(saved)
    # Repeated start events from another attached tab must not erase completion.
    client.handlers["Browser.downloadWillBegin"](
        {"guid": "download-id", "suggestedFilename": "invoice.pdf"}
    )
    assert native.state()["downloads"][0]["state"] == "completed"


@pytest.mark.asyncio
async def test_video_limit_finalizes_without_manual_stop(browser, monkeypatch):
    import shutil
    from deepseek_tui.browser.video import BrowserVideo

    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is required for video encoding')
    monkeypatch.setattr(BrowserVideo, 'max_seconds', 0.2)
    run = browser.runs['one']
    await browser.start_video(run)
    video = run.video
    await video.task
    await asyncio.sleep(0)
    assert not browser.state('one')['video_recording']
    assert run.video_error is None
    assert len(run.artifacts) == 1
    assert Path(run.artifacts[0]['path']).read_bytes().startswith(b'\x1aE\xdf\xa3')
    assert browser._finish_video(run, video) == run.artifacts[0]
    await browser.stop_video(run)
    assert len(run.artifacts) == 1


@pytest.mark.asyncio
async def test_video_failure_is_reported_without_manual_stop(browser, monkeypatch):
    import shutil

    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is required for video encoding')
    monkeypatch.setattr(browser, '_capture_recording', AsyncMock(side_effect=RuntimeError('disconnected')))
    run = browser.runs['one']
    await browser.start_video(run)
    video = run.video
    await video.task
    await asyncio.sleep(0)
    state = browser.state('one')
    assert state['video_recording'] is False
    assert state['video_error'] == 'disconnected'
    assert not run.artifacts
    assert not video.path.exists()


@pytest.mark.asyncio
async def test_simultaneous_video_stops_save_once(browser):
    import shutil

    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is required for video encoding')
    run = browser.runs['one']
    await browser.start_video(run)
    while not run.video.frames:
        await asyncio.sleep(0.01)
    first, second = await asyncio.gather(browser.stop_video(run), browser.stop_video(run))
    assert first == second == run.artifacts[0]
    assert len(run.artifacts) == 1


@pytest.mark.asyncio
async def test_gif_save_failure_preserves_frames_for_retry(browser, monkeypatch):
    run = browser.runs['one']
    await browser.action('one', BrowserAction(action='record_start'))
    frames = list(run.frames)
    save = browser._save
    def fail_save(*args):
        raise OSError('disk full')
    monkeypatch.setattr(browser, '_save', fail_save)
    assert browser._finish_recording(run) is None
    assert run.frames == frames
    state = browser.state('one')
    assert state['recording'] is False
    assert state['recording_pending_save'] is True
    assert state['recording_error'] == 'disk full'
    with pytest.raises(ValueError, match='already running'):
        await browser.action('one', BrowserAction(action='record_start'))
    monkeypatch.setattr(browser, '_save', save)
    result = await browser.action('one', BrowserAction(action='record_stop'))
    assert result['artifact']['id'].endswith('.gif')
    assert not run.frames and run.recording_error is None
    assert browser.state('one')['recording_pending_save'] is False


@pytest.mark.asyncio
async def test_video_capture_failure_preserves_partial_file(browser, monkeypatch):
    import shutil
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is required for video encoding')
    run = browser.runs['one']
    frame = await browser._capture(run)
    monkeypatch.setattr(browser, '_capture_recording', AsyncMock(side_effect=[frame, RuntimeError('tab closed')]))
    await browser.start_video(run)
    video = run.video
    await video.task
    await asyncio.sleep(0)
    assert run.video is None
    assert run.video_error == 'tab closed'
    assert len(run.artifacts) == 1
    assert Path(run.artifacts[0]['path']).stat().st_size > 0


@pytest.mark.asyncio
async def test_gif_sampler_failure_stops_and_keeps_prior_frames(browser, monkeypatch):
    run = browser.runs['one']
    run.frames = [await browser._capture(run)]
    run.recording = True
    monkeypatch.setattr(browser, '_capture_recording', AsyncMock(side_effect=RuntimeError('tab closed')))
    await browser._sample_frames(run, interval=0)
    assert browser.state('one')['recording_pending_save'] is True
    assert run.recording_error == 'tab closed'
    assert not run.recording and len(run.frames) == 1


@pytest.mark.asyncio
async def test_gif_sampler_rides_out_a_missed_sample(browser, monkeypatch):
    run = browser.runs['one']
    frame = await browser._capture(run)
    run.frames = [frame] * 39
    run.recording = True
    missed = RuntimeError('No visible browser tab to record')
    capture = AsyncMock(side_effect=[missed, missed, frame])
    monkeypatch.setattr(browser, '_capture_recording', capture)
    await browser._sample_frames(run, interval=0)
    assert run.recording_error is None
    assert run.artifacts[-1]['id'].endswith('.gif')


@pytest.mark.asyncio
async def test_gif_limit_automatically_saves(browser, monkeypatch):
    run = browser.runs['one']
    frame = await browser._capture(run)
    run.frames = [frame] * 39
    run.recording = True
    monkeypatch.setattr(browser, '_capture_recording', AsyncMock(return_value=frame))
    await browser._sample_frames(run, interval=0)
    assert not run.recording and not run.frames
    assert run.artifacts[-1]['id'].endswith('.gif')
    assert browser.state('one')['recording_pending_save'] is False


async def test_a_reclaimed_private_browser_says_so_to_its_chat(tmp_path):
    import time

    from deepseek_tui.browser.service import BrowserRun, BrowserService

    service = BrowserService(tmp_path / "artifacts")
    for index in range(8):
        run = BrowserRun(f"t{index}", tmp_path / f"d{index}")
        run.last_used = time.monotonic() - 3600 + index
        service.runs[run.thread_id] = run
    await service._reclaim_idle_session()
    assert "t0" not in service.runs
    assert service.state("t0")["reclaimed"] is True


async def test_real_private_browser_keeps_page_opened_windows_with_the_user(tmp_path):
    import functools
    import http.server
    import os
    import threading

    from deepseek_tui.browser.service import BrowserActionError

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    (tmp_path / "signin.html").write_text(
        "<button id='login' onclick=\"window.open('/login.html','login','width=400,height=500')\">"
        "Sign in</button>", encoding="utf-8")
    (tmp_path / "login.html").write_text("<button>Allow</button>", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmp_path)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    service = BrowserService(tmp_path / "artifacts")
    service.configure("t", False)
    try:
        opened = await service.action("t", BrowserAction(
            action="open", url=f"http://127.0.0.1:{httpd.server_address[1]}/signin.html"))
        login = next(e for e in opened["observation"]["elements"] if e.get("name") == "Sign in")
        clicked = await service.action("t", BrowserAction(
            action="click", ref=login["ref"], observation_id=opened["observation"]["observation_id"]),
            require_observation=True)
        assert "the page opened a window" in clicked["content"]
        popup = next(tab for tab in service.runs["t"].tabs if tab.get("popup"))
        with pytest.raises(BrowserActionError, match="window the page opened"):
            await service.action("t", BrowserAction(action="switch_tab", tab_id=popup["tab_id"]))
    finally:
        await service.close_all()
        httpd.shutdown()
