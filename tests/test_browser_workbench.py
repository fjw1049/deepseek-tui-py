"""Workbench tabs: the runtime drives the pages the user sees through the app's bridge."""

import asyncio
import json
import socket

import pytest
import websockets

from deepseek_tui.browser.service import BrowserAction, BrowserService


class FakeBridge:
    """The Workbench side: tabs, their pages, and the token every connection needs."""

    def __init__(self):
        self.token = "t" * 32
        self.tabs = {"tab-a": {"url": "https://example.test/", "title": "Example"}}
        self.active = "tab-a"
        self.opened: list[str] = []
        self.connections: list[str] = []
        self.cookies: dict[tuple, dict] = {}
        self.cleared = 0
        self.methods: list[str] = []

    async def handler(self, ws):
        path = ws.request.path
        if f"token={self.token}" not in path:
            await ws.close(1008)
            return
        tab = path.split("?")[0].removeprefix("/tab/") if path.startswith("/tab/") else None
        self.connections.append(tab or "control")
        async for raw in ws:
            message = json.loads(raw)
            method, params = message["method"], message.get("params", {})
            self.methods.append(method)
            if method == "Workbench.clearCookies":
                self.cookies.clear()
                self.cleared += 1
                result = {}
            elif method == "Network.deleteCookies":
                gone = (params["name"], params["domain"])
                self.cookies = {key: value for key, value in self.cookies.items()
                                if (value["name"], value["domain"]) != gone}
                result = {}
            elif method == "Network.getAllCookies":
                result = {"cookies": list(self.cookies.values())}
            elif method == "Network.setCookies":
                from urllib.parse import urlsplit

                for cookie in params["cookies"]:
                    domain = cookie.get("domain") or urlsplit(cookie["url"]).hostname
                    stored = {"name": cookie["name"], "value": cookie["value"], "domain": domain,
                              "path": cookie.get("path", "/")}
                    self.cookies[(cookie["name"], domain, stored["path"])] = stored
                result = {}
            elif method == "Page.captureScreenshot":
                import base64
                import io

                from PIL import Image

                output = io.BytesIO()
                colour = (len(self.cookies) * 40 % 255, 90, 160)
                Image.new("RGB", (64, 48), colour).save(output, "JPEG")
                result = {"data": base64.b64encode(output.getvalue()).decode()}
            elif method == "Workbench.openSession":
                self.opened.append(params["browserId"])
                result = {"tabs": self.listing()}
            elif method == "Workbench.listTabs":
                result = {"tabs": self.listing()}
            elif method == "Workbench.createTab":
                tab_id = f"tab-{len(self.tabs)}"
                self.tabs[tab_id] = {"url": params["url"], "title": ""}
                self.active = tab_id
                result = {"tabId": tab_id}
            elif method == "Workbench.activateTab":
                self.active = params["tabId"]
                result = {}
            elif method == "Workbench.closeTab":
                self.tabs.pop(params["tabId"])
                result = {}
            elif method == "Target.getTargetInfo":
                result = {"targetInfo": {"targetId": tab}}
            elif method == "Page.getLayoutMetrics":
                result = {"cssLayoutViewport": {"clientWidth": 640, "clientHeight": 480}}
            elif method == "Page.getFrameTree":
                frame = {"id": tab, "loaderId": "doc", "url": self.tabs[tab]["url"]}
                result = {"frameTree": {"frame": frame}}
            else:
                result = {}
            await ws.send(json.dumps({"id": message["id"], "result": result}))

    def listing(self):
        return [{"tab_id": key, "url": tab["url"], "title": tab["title"],
                 "active": key == self.active} for key, tab in self.tabs.items()]


@pytest.fixture
async def bridge():
    fake = FakeBridge()
    async with websockets.serve(fake.handler, "127.0.0.1", 0) as server:
        fake.port = server.sockets[0].getsockname()[1]
        yield fake


@pytest.fixture
def browser(tmp_path, bridge):
    service = BrowserService(tmp_path / "artifacts")
    service.workbench = {"port": bridge.port, "token": bridge.token}
    return service


async def test_runs_drive_the_visible_workbench_tab_at_its_real_size(browser, bridge):
    run = await browser.ensure("thr_one")
    assert run.native and bridge.opened == ["thr_one"]
    assert (run.width, run.height) == (640, 480)  # The panel's size, never a forced viewport.
    assert browser.state("thr_one")["surface"] == "native"
    tabs = await run.session.list_tabs()
    assert tabs.metadata["tabs"] == [{"tab_id": "tab-a", "url": "https://example.test/",
                                      "title": "Example", "active": True, "shown": True}]
    await browser.close("thr_one")
    assert bridge.tabs  # Ending the session leaves the user's tabs open.


async def test_tab_operations_go_through_workbench_and_follow_the_new_tab(browser, bridge):
    run = await browser.ensure("thr_one")
    created = await run.session.new_tab(force_new=True)
    assert created.success and run.session.tab_id == "tab-1" and bridge.active == "tab-1"
    assert bridge.tabs["tab-1"]["url"] == "about:blank"
    assert bridge.connections[-1] == "tab-1"  # Reconnected to the page it opened.
    switched = await run.session.switch_tab("tab-a")
    assert switched.success and run.session.tab_id == "tab-a" and bridge.active == "tab-a"
    closed = await run.session.close_tab("tab-1")
    assert closed.success and "tab-1" not in bridge.tabs
    listing = await browser.action("thr_one", BrowserAction(action="tabs"))
    assert listing["success"]


async def test_without_workbench_only_native_requests_fail_and_the_bridge_is_forgotten(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]  # Nothing listens here once the socket closes.
    service = BrowserService(tmp_path / "artifacts")
    service.workbench = {"port": port, "token": "t" * 32}
    with pytest.raises(ValueError, match="Workbench browser is unavailable"):
        await service.ensure("thr_one", native_only=True)
    assert service.workbench is None and "thr_one" not in service.runs


async def test_a_rejected_token_falls_back_without_forgetting_workbench(browser, bridge):
    bridge.token = "x" * 32
    with pytest.raises(ValueError, match="unavailable"):
        await browser.ensure("thr_one", native_only=True)
    assert browser.workbench is not None


@pytest.mark.asyncio
async def test_workbench_announces_its_bridge_and_panels_bind_native_tabs(tmp_path, bridge):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from deepseek_tui.server.browser_routes import (
        WorkbenchBridge,
        attach,
        register_workbench,
        unregister_workbench,
    )

    service = BrowserService(tmp_path / "artifacts")
    manager = SimpleNamespace(browser_service=service,
                              store=SimpleNamespace(load_thread=lambda _: None),
                              browser_task_state=lambda _: {"task_running": False})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_manager=manager)))
    with pytest.raises(HTTPException):
        await attach(request, "thr_one")  # No Workbench: panels never start a private browser.
    await register_workbench(request, WorkbenchBridge(port=bridge.port, token=bridge.token))
    state = await attach(request, "thr_one")
    assert state["surface"] == "native" and state["owner"] == "user"
    await unregister_workbench(request)
    assert service.workbench is None
    await asyncio.gather(service.close_all())


async def test_answering_a_dialog_does_not_wait_for_a_blocked_page(browser):
    from unittest.mock import AsyncMock

    run = await browser.ensure("thr_one")
    client = run.session._internal.client
    original = client.send

    async def send(method, params=None, **kwargs):
        if method == "Page.getLayoutMetrics":
            raise AssertionError("A page showing a dialog cannot lay out")
        return await original(method, params, **kwargs)

    class Dialog:
        dialog = {"id": "d", "type": "confirm", "message": "Proceed?", "generation": run.generation}
        install = AsyncMock()
        handle_dialog = AsyncMock(side_effect=lambda action: setattr(Dialog, "dialog", None))

        def state(self):
            return {"dialog": self.dialog, "file_chooser": None, "downloads": [], "loading": False}

    client.send = send
    run.native_events = Dialog()
    result = await browser.action(
        "thr_one", BrowserAction(action="handle_dialog", dialog_id="d", accept=True))
    assert result["success"] and Dialog.handle_dialog.await_count == 1


async def test_recording_a_workbench_tab_connects_through_the_bridge(browser, bridge, monkeypatch):
    from deepseek_tui.browser import recording
    from deepseek_tui.browser.workbench import tab_url

    run = await browser.ensure("thr_one")
    connected = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def connect(self, url):
            connected.append(url)
            raise ConnectionError("stop after connecting")

        async def close(self):
            pass

    async def page(client, expression):
        return {"url": "https://example.test/", "title": "Example"}

    monkeypatch.setattr(recording, "CDPClient", Client)
    monkeypatch.setattr(recording, "evaluate", page)
    with pytest.raises(ConnectionError):
        await recording.create_recording(run, object())
    assert connected == [tab_url(browser.workbench, "tab-a")]  # Never the user's Chrome port.


async def test_a_new_task_works_in_the_tab_the_user_is_viewing(browser, bridge):
    run = await browser.ensure("thr_one")
    await browser.control("thr_one", "user")
    bridge.tabs["tab-b"] = {"url": "https://example.test/b", "title": "B"}
    bridge.active = "tab-b"  # The user switched tabs in Workbench.
    await browser.action("thr_one", BrowserAction(action="status"))
    assert run.owner == "agent" and run.session.tab_id == "tab-b"
    tabs = (await run.session.list_tabs()).metadata["tabs"]
    assert {tab["tab_id"]: (tab["active"], tab["shown"]) for tab in tabs} == {
        "tab-a": (False, False), "tab-b": (True, True)}


async def test_reclaiming_waits_for_a_control_change_in_flight(browser):
    run = await browser.ensure("thr_one")
    await browser.control("thr_one", "user")
    run.transferring = True  # The user's hand-off is still settling.

    async def settle():
        await asyncio.sleep(0.1)
        run.transferring = False

    pending = asyncio.create_task(settle())
    await browser.action("thr_one", BrowserAction(action="status"))
    await pending
    assert run.owner == "agent" and run.agent_task


async def test_the_page_returns_to_the_user_between_tasks(browser):
    from deepseek_tui.server.threads.manager import RuntimeThreadManager

    manager = RuntimeThreadManager.__new__(RuntimeThreadManager)
    manager.browser_service = browser
    run = await browser.ensure("thr_one")
    run.agent_task = True  # The next turn already started using it.
    await manager._hand_browser_back("thr_one")
    assert run.owner == "agent"
    run.agent_task, run.assistance = False, {"id": "help"}
    await manager._hand_browser_back("thr_one")
    assert run.owner == "agent"  # A help request keeps waiting on the agent's page.
    run.assistance = None
    await manager._hand_browser_back("thr_one")
    assert run.owner == "user"


async def test_clearing_cookies_clears_the_workbench_browser_too(browser, bridge):
    await browser.ensure("thr_one")  # A Workbench tab no longer blocks clearing.
    bridge.cookies[("sid", "example.test", "/")] = {"name": "sid", "domain": "example.test"}
    await browser.clear_cookies()
    assert bridge.cleared == 1 and not bridge.cookies


async def test_saved_logins_reach_the_workbench_browser_once_and_after_offline_syncs(
        browser, bridge, monkeypatch):
    from deepseek_tui.browser.cookies import cookie_key

    cookie = {"name": "sid", "value": "old", "domain": "example.test", "path": "/", "expires": -1}

    def seed(data):
        data["cookies"] = {cookie_key(cookie): cookie}
        data["chrome_sites"] = ["example.test"]
        return True

    await browser.cookies._edit(seed)
    run = await browser.ensure("thr_one")
    # Migrated from the old private browser.
    assert [c["value"] for c in bridge.cookies.values()] == ["old"]
    bridge.cookies.clear()  # The user signs out in Workbench.
    await browser.close("thr_one")
    await browser.ensure("thr_one")
    assert not bridge.cookies  # A sign-out is not undone by the saved copy.

    monkeypatch.setattr(browser.cookies, "settings",
                        lambda: {"consent": "enabled", "profile": "Default"})

    def chrome_sync(data):
        data["cookies"][cookie_key(cookie)] = {**cookie, "value": "chrome"}
        data["native_pending"] = True  # Synced while Workbench's browser was closed.
        return True

    await browser.cookies._edit(chrome_sync)
    await browser.close("thr_one")
    run = await browser.ensure("thr_one")
    assert [c["value"] for c in bridge.cookies.values()] == ["chrome"]
    assert run.native


async def test_step_recording_samples_a_workbench_tab(browser, bridge):
    run = await browser.ensure("thr_one")
    await browser.action("thr_one", BrowserAction(action="record_start"))
    await asyncio.sleep(1.2)
    # The page changes colour.
    bridge.cookies[("x", "y", "/")] = {"name": "x", "value": "", "domain": "y", "path": "/"}
    await asyncio.sleep(1.1)
    sampler = run.frame_task
    result = await browser.action("thr_one", BrowserAction(action="record_stop"))
    assert result["artifact"]["path"].endswith(".gif")
    await asyncio.sleep(0)
    assert sampler.done() and run.frame_task is None


async def test_switching_tabs_does_not_pile_up_closed_connections(browser, bridge):
    run = await browser.ensure("thr_one")
    for _ in range(3):
        await browser.action("thr_one", BrowserAction(action="new_tab"))
    await browser.action("thr_one", BrowserAction(action="tabs"))
    clients = run.native_events.clients
    assert clients and all(client._ws is not None for client in clients)


async def test_idle_pages_left_with_the_user_can_still_be_reclaimed(browser, bridge, monkeypatch):
    from deepseek_tui.browser import service as module

    for index in range(8):
        run = await browser.ensure(f"thr_{index}")
        await browser.control(f"thr_{index}", "user")  # Every task hands the page back.
        run.last_used = run.last_view_at = 0
    monkeypatch.setattr(module.time, "monotonic", lambda: 10_000.0)
    await browser.ensure("thr_new")
    assert "thr_new" in browser.runs and len(browser.runs) == 8
    assert bridge.tabs  # Reclaiming only detached a Workbench run.


async def test_tab_changes_keep_the_panel_size_without_forcing_a_viewport(browser, bridge):
    await browser.ensure("thr_one")
    await browser.action("thr_one", BrowserAction(action="new_tab"))
    await browser.action("thr_one", BrowserAction(action="switch_tab", tab_id="tab-a"))
    assert "Emulation.setDeviceMetricsOverride" not in bridge.methods


async def test_turn_end_leaves_an_agent_recording_running(browser):
    from deepseek_tui.server.threads.manager import RuntimeThreadManager

    manager = RuntimeThreadManager.__new__(RuntimeThreadManager)
    manager.browser_service = browser
    run = await browser.ensure("thr_one")
    await browser.action("thr_one", BrowserAction(action="record_start"))
    run.agent_task = False
    await manager._hand_browser_back("thr_one")
    assert run.owner == "agent" and run.recording
    await browser.action("thr_one", BrowserAction(action="record_stop"))


async def test_a_takeover_during_the_turn_is_not_undone_by_that_turn(browser):
    from types import SimpleNamespace

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.server.threads.manager import RuntimeThreadManager

    manager = RuntimeThreadManager.__new__(RuntimeThreadManager)
    manager.browser_service = browser
    handle = EngineHandle()
    handle._mark_turn_active()
    turn = SimpleNamespace(turn_id="t")
    manager._active = {"thr_one": SimpleNamespace(handle=handle, active_turn=turn)}
    run = await browser.ensure("thr_one")
    run.agent_task = False  # The turn is busy with other tools.
    await manager.control_browser("thr_one", "user")
    with pytest.raises(ValueError, match="user controls this browser"):
        await browser.action("thr_one", BrowserAction(action="reload"))
    await manager._hand_browser_back("thr_one")
    run.agent_task = False  # The next turn asks for the browser again.
    await browser.action("thr_one", BrowserAction(action="status"))
    assert run.owner == "agent"


async def test_sign_outs_from_a_sync_reach_the_workbench_browser(browser, bridge):
    def removed(data):
        data["native_migrated"] = True
        data["native_removed"] = [{"name": "sid", "domain": "bank.example", "path": "/"}]
        return True

    bridge.cookies[("sid", "bank.example", "/")] = {"name": "sid", "value": "v",
                                                     "domain": "bank.example", "path": "/"}
    await browser.cookies._edit(removed)
    await browser.ensure("thr_one")
    assert not bridge.cookies


async def test_a_failed_close_never_kills_another_browser(browser, monkeypatch):
    from unittest.mock import AsyncMock

    from octop_browser.cdp import launcher

    terminate = AsyncMock()
    monkeypatch.setattr(launcher, "terminate_browser", terminate)
    run = await browser.ensure("thr_one")
    run.session.close = AsyncMock(side_effect=RuntimeError("socket error"))
    with pytest.raises(RuntimeError):
        await browser.close("thr_one")
    terminate.assert_not_called()


async def test_user_screenshot_follows_visible_tab(browser, bridge):
    run = await browser.ensure('thr_one')
    await browser.control('thr_one', 'user')
    bridge.tabs['tab-b'] = {'url': 'https://example.test/b', 'title': 'B'}
    bridge.active = 'tab-b'  # Native UI changes the shown tab without a runtime action.
    result = await browser.action('thr_one', BrowserAction(action='screenshot'), actor='user')
    assert result['success']
    assert run.session.tab_id == bridge.active, 'Saved evidence targets the old hidden tab'

async def test_attach_recovers_a_user_closed_native_tab(browser, bridge):
    run = await browser.ensure('thr_one')
    await browser.control('thr_one', 'user')
    bridge.tabs['tab-b'] = {'url': 'https://example.test/b', 'title': 'B'}
    bridge.tabs.pop('tab-a')
    bridge.active = 'tab-b'
    await run.session._internal.client._ws.close()  # guest destruction closes the transport remotely
    await __import__('asyncio').sleep(0.01)
    from types import SimpleNamespace
    from deepseek_tui.server.browser_routes import attach

    manager = SimpleNamespace(browser_service=browser,
        store=SimpleNamespace(load_thread=lambda _: None),
        browser_task_state=lambda _: {'task_running': False})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_manager=manager)))
    state = await attach(request, 'thr_one')
    status = await browser.action('thr_one', BrowserAction(action='status'), actor='user')
    assert status['success'], 'Attach leaves the disconnected BrowserRun in place'
    assert run.session.tab_id == 'tab-b'


async def test_explicit_human_tab_does_not_drift_with_later_selection(browser, bridge):
    run = await browser.ensure("thr_one")
    await browser.control("thr_one", "user")
    bridge.tabs["tab-b"] = {"url": "https://example.test/b", "title": "B"}
    bridge.active = "tab-a"  # The UI selection changed after the request was submitted.
    await browser.action("thr_one", BrowserAction(action="screenshot", tab_id="tab-b",
                                                generation=run.generation), actor="user")
    assert run.session.tab_id == "tab-b" and bridge.active == "tab-a"
    with pytest.raises(ValueError, match="no longer exists"):
        await browser.action("thr_one", BrowserAction(action="screenshot", tab_id="missing"), actor="user")
    assert run.session.tab_id == "tab-b"


async def test_an_active_agent_does_not_follow_manual_tab_selection(browser, bridge):
    run = await browser.ensure("thr_one")
    await browser.action("thr_one", BrowserAction(action="status"))
    bridge.tabs["tab-b"] = {"url": "https://example.test/b", "title": "B"}
    bridge.active = "tab-b"
    await browser.action("thr_one", BrowserAction(action="status"))
    assert run.session.tab_id == "tab-a" and run.agent_task


async def test_reattach_keeps_receipts_and_does_not_retarget_a_running_agent(browser, bridge):
    run = await browser.ensure("thr_one")
    run.operations = {"op": {"receipt": {"execution": "unknown"}}}
    run.unresolved = {"op": {"action_id": "op"}}
    bridge.tabs["tab-b"] = {"url": "https://example.test/b", "title": "B"}
    bridge.tabs.pop("tab-a")
    bridge.active = "tab-b"
    await run.session._internal.client._ws.close()
    run.agent_task = True
    with pytest.raises(ValueError, match="disconnected"):
        await browser.attach_native("thr_one")
    assert run.session.tab_id == "tab-a"
    run.agent_task = False
    run.owner = "user"
    generation = run.generation
    await browser.attach_native("thr_one")
    assert browser.runs["thr_one"] is run
    assert run.generation == generation + 1
    assert run.operations["op"]["receipt"]["execution"] == "unknown" and "op" in run.unresolved
    assert run.session.tab_id == "tab-b"
    assert bridge.tabs["tab-b"]["url"] == "https://example.test/b"


@pytest.mark.parametrize('fail_capture', [False, True])
async def test_native_recorder_discovers_new_tabs_and_reports_capture_failures(
        browser, bridge, monkeypatch, fail_capture):
    from unittest.mock import AsyncMock
    from deepseek_tui.browser import recording
    from deepseek_tui.browser.workflows import recording_store

    run = await browser.ensure('thr_one')
    installed = []

    async def install(self, client, target_id):
        if target_id == 'tab-b' and fail_capture:
            raise RuntimeError('test capture unavailable')
        await client.enable_domain('Runtime')
        installed.append(target_id)

    monkeypatch.setattr(recording, 'evaluate', AsyncMock(return_value={
        'url': 'https://example.test/', 'title': 'Example'}))
    monkeypatch.setattr(recording.WorkbenchRecordSession, '_install_on_client', install)
    sync_frames = AsyncMock()
    monkeypatch.setattr(recording.WorkbenchRecordSession, '_sync_frames', sync_frames)
    recorder, _ = await recording.create_recording(run, recording_store(browser, 'thr_one'))
    try:
        assert recorder._poll_task is not None
        bridge.tabs['tab-b'] = {'url': 'https://example.test/b', 'title': 'B'}
        bridge.active = 'tab-b'
        for _ in range(30):
            if ('tab-b' in installed or recorder.capture_warnings) and sync_frames.await_count >= 2:
                break
            await asyncio.sleep(.05)
        if fail_capture:
            assert recorder.capture_warnings and 'tab-b' not in recorder._clients
            # The blocked tab says why instead of looking busy forever.
            assert recorder.tab_errors == {'tab-b': 'test capture unavailable'}
            run.recorder = recorder
            assert browser.state('thr_one')['workflow_tab_errors'] == recorder.tab_errors
            bridge.tabs.pop('tab-b')
            bridge.active = 'tab-a'
            for _ in range(30):
                if not recorder.tab_errors:
                    break
                await asyncio.sleep(.05)
            assert recorder.tab_errors == {}
        else:
            assert 'tab-b' in recorder._clients and installed == ['tab-a', 'tab-b']
            assert not recorder.capture_warnings and not recorder.tab_errors
        assert sync_frames.await_count >= 2
    finally:
        run.recorder = None
        await recorder.close()
        await browser.close_all()


async def test_native_recorder_only_reports_tabs_opened_during_the_recording(
        browser, bridge, monkeypatch):
    from unittest.mock import AsyncMock

    from deepseek_tui.browser import recording
    from deepseek_tui.browser.workflows import recording_store

    bridge.tabs['tab-old'] = {'url': 'https://example.test/old', 'title': 'Old'}
    run = await browser.ensure('thr_one')
    events = []
    original = recording.WorkbenchRecordSession._append

    def append(self, event):
        events.append(event)
        return original(self, event)

    async def install(self, client, target_id):
        await client.enable_domain('Runtime')

    monkeypatch.setattr(recording.WorkbenchRecordSession, '_append', append)
    monkeypatch.setattr(recording, 'evaluate', AsyncMock(return_value={
        'url': 'https://example.test/', 'title': 'Example'}))
    monkeypatch.setattr(recording.WorkbenchRecordSession, '_install_on_client', install)
    monkeypatch.setattr(recording.WorkbenchRecordSession, '_sync_frames', AsyncMock())
    recorder, _ = await recording.create_recording(run, recording_store(browser, 'thr_one'))
    try:
        bridge.tabs['tab-new'] = {'url': 'https://example.test/new', 'title': 'New'}
        for _ in range(30):
            if 'tab-new' in recorder._clients:
                break
            await asyncio.sleep(.05)
        # Existing tabs are recorded if used, but were not opened by the demonstration.
        assert {'tab-a', 'tab-old', 'tab-new'} <= set(recorder._clients)
        assert [e['targetId'] for e in events if e.get('kind') == 'page_opened'] == ['tab-new']
    finally:
        await recorder.close()
        await browser.close_all()


async def test_agent_can_list_and_switch_after_controlled_popup_closes(browser, bridge):
    run = await browser.ensure("thr_one")
    await browser.action("thr_one", BrowserAction(action="new_tab"))
    closed = run.session.tab_id
    await run.session._internal.client.close()
    bridge.tabs.pop(closed)
    bridge.active = "tab-a"
    run.healthy = False
    tabs = await browser.action("thr_one", BrowserAction(action="tabs"))
    assert tabs["success"] and [t["tab_id"] for t in tabs["tabs"]] == ["tab-a"]
    switched = await browser.action("thr_one", BrowserAction(action="switch_tab", tab_id="tab-a"))
    assert switched["success"]
    assert run.session.connected and run.session.tab_id == "tab-a" and run.healthy
    assert not run.unresolved
    await browser.close("thr_one")
