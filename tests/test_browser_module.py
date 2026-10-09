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
async def test_frame_reports_current_page_and_export_preserves_assertions(browser):
    import json
    import zipfile

    run = browser.runs["one"]
    original = run.session._internal.client.send.return_value
    run.session._internal.client.send.side_effect = [
        {"frameTree": {"frame": {"url": "http://localhost/redirected#section"}}}, original
    ]
    await browser.frame("one")
    assert browser.state("one")["url"] == "http://localhost/redirected#section"
    run.session._internal.client.send.side_effect = None
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


def test_replay_resolves_moved_demo_and_rejects_other_local_files():
    from deepseek_tui.browser import workflows

    directory = Path(workflows.__file__).parent
    url = (directory / "browser_demo.html").as_uri()
    assert workflows._url(url) == url
    for legacy in (
        directory.parent / "browser_demo.html",
        directory.parent.parent / "browser" / "browser_demo.html",
    ):
        assert workflows._url(legacy.as_uri()) == url
        assert workflows._demo_url(legacy.as_uri()) == url
    assert workflows._url("https://example.com") == "https://example.com"
    with pytest.raises(ValidationError):
        workflows._url((directory / "other.html").as_uri())


@pytest.mark.asyncio
async def test_workflow_preflight_and_takeover(browser, monkeypatch):
    from deepseek_tui.browser import workflows as flows

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
        assert {".jpg", ".gif"} <= {Path(a["id"]).suffix for a in state["artifacts"]}
        if service.environment()["video_ready"]:
            assert any(a["id"].endswith(".webm") for a in state["artifacts"])
            assert not state["video_error"]
        assert (await service.frame("demo")).startswith("data:image/jpeg;base64,")
        assert service.state("demo")["url"].endswith("browser_demo.html")
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
    from deepseek_tui.browser.workflows import (
        finish_recording,
        read_workflow,
        recording_store,
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
        legacy_url = (
            Path(browser_module.__file__).parent.parent / "browser_demo.html"
        ).as_uri()
        for step in doc.steps:
            if step.url == url:
                step.url = legacy_url
                step.expect = {"urlContains": legacy_url}
        doc.verification = [{"type": "url_contains", "value": legacy_url}]
        recording_store(service, "flow").write_steps(result["recordingId"], doc)
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


async def test_status_without_start_and_during_takeover(browser):
    result = await browser.action("new", BrowserAction(action="status"))
    assert result["content"]["active"] is False
    assert "new" not in browser.runs
    await browser.control("one", "user")
    browser.runs["one"].session._internal.client.send.return_value = {
        "frameTree": {"frame": {"url": "https://example.test/after-login"}}
    }
    result = await browser.action("one", BrowserAction(action="status"))
    assert result["content"] == {
        "active": True,
        "owner": "user",
        "url": "https://example.test/after-login",
        "viewport": {"width": 1200, "height": 760},
    }
    with pytest.raises(ValueError, match="control changed"):
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
    await browser.action("one", BrowserAction(action="wait", selector="#ready"))
    session.wait.assert_awaited_once_with(
        text=None, selector="#ready", url_contains=None, timeout_ms=10000
    )
    await browser.action("one", BrowserAction(action="hover", ref="ref_1"))
    session.hover.assert_awaited_once_with(ref="ref_1")
    await browser.action("one", BrowserAction(action="type", text="中文"))
    session.type.assert_awaited_once_with(text="中文", ref=None, selector=None)
    await browser.action("one", BrowserAction(action="observe"))
    session.dom_tree.assert_awaited_once_with(level="interactive")
    await browser.action("one", BrowserAction(action="observe", level="full"))
    session.dom_tree.assert_awaited_with(level="full")
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
    assert "els.length === 1" in session.eval_js.call_args.args[0]
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
