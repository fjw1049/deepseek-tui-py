"""Recording compilation must preserve scopes and distinct masked edits."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from octop_browser.record.settings import RecordReplaySettings
from octop_browser.record.store import RecordingStore

from deepseek_tui.browser.recording import ScopedSemanticProcessor, create_recording


@pytest.mark.parametrize("second_scope", [{}, {"shadowPath": ["#host"]}, {"framePath": ["#frame"]}])
def test_distinct_redacted_edits_are_not_merged_across_fields_or_time(second_scope):
    target = {
        "id": "q",
        "name": "Draft",
        "tag": "input",
        "type": "text",
        "role": "textbox",
        "selectorCandidates": ["#q"],
    }
    events = [
        {
            "seq": 1,
            "kind": "recorder_installed",
            "targetId": "tab",
            "page": {"url": "https://example.test/"},
        }
    ]
    for seq, scope in [(2, {}), (3, second_scope)]:
        events.append(
            {
                "seq": seq,
                "kind": "input",
                "targetId": "tab",
                "target": {**target, **scope},
                "value": "{{sensitive_value}}",
                "redacted": True,
                "page": {"url": "https://example.test/"},
            }
        )
    doc = ScopedSemanticProcessor("rec_test", events).process()
    fills = [step for step in doc.steps if step.kind == "fill"]
    assert len(fills) == 2 and len(doc.inputs) == 2 and fills[0].value != fills[1].value
    assert len({step.id for step in doc.steps}) == len(doc.steps)
    assert events[-1]["value"] == "{{sensitive_value}}"


def test_masked_checkbox_event_preserves_false_state():
    doc = ScopedSemanticProcessor(
        "rec_test",
        [
            {
                "seq": 1,
                "kind": "input",
                "redacted": True,
                "checked": False,
                "value": "{{sensitive_value}}",
                "target": {
                    "tag": "input",
                    "type": "checkbox",
                    "id": "check",
                    "selectorCandidates": ["#check"],
                },
            }
        ],
    ).process()
    assert len(doc.steps) == 1 and doc.steps[0].kind == "set_checked"
    assert doc.steps[0].value == "false" and not doc.inputs


async def test_failed_recorder_start_closes_its_connection_and_marks_failed(tmp_path, monkeypatch):
    from deepseek_tui.browser import recording

    client = SimpleNamespace(connect=AsyncMock(), close=AsyncMock(), send=AsyncMock())
    monkeypatch.setattr(recording, "CDPClient", lambda **kwargs: client)
    monkeypatch.setattr(
        recording.WorkbenchRecordSession,
        "start",
        AsyncMock(side_effect=RuntimeError("capture setup failed")),
    )
    owned = SimpleNamespace(
        send=AsyncMock(
            side_effect=[
                {
                    "result": {
                        "value": {"url": "https://example.test/?token=PRIVATE", "title": "Page"}
                    }
                },
                {"targetInfo": {"targetId": "current"}},
            ]
        )
    )
    run = SimpleNamespace(
        session=SimpleNamespace(_internal=SimpleNamespace(client=owned)),
        profiles=SimpleNamespace(get_or_create=lambda name: SimpleNamespace(cdp_port=12345)),
        settings=SimpleNamespace(cdp_timeout=1, cdp_host="127.0.0.1"),
    )
    store = RecordingStore(RecordReplaySettings(base_dir=tmp_path))
    with pytest.raises(RuntimeError, match="capture setup failed"):
        await create_recording(run, store)
    client.close.assert_awaited_once()
    manifests = store.list_recordings()
    assert len(manifests) == 1 and manifests[0].status == "failed"
    assert "PRIVATE" not in manifests[0].target.start_url


@pytest.mark.parametrize("failure", ["size", "rate", "store"])
async def test_capture_limits_and_storage_failures_mark_recording_incomplete(
    tmp_path, failure, monkeypatch
):
    import json

    from octop_browser.record.models import PrivacySettings, RecordingManifest

    from deepseek_tui.browser.recording import WorkbenchRecordSession

    settings = RecordReplaySettings(
        base_dir=tmp_path, max_event_bytes=1000, max_events_per_second=1
    )
    store = RecordingStore(settings)
    manifest = RecordingManifest(
        recordingId="rec_limits",
        createdAt="2026-10-12",
        privacy=PrivacySettings(input_policy="mask-all"),
    )
    store.create(manifest)
    session = WorkbenchRecordSession(SimpleNamespace(), store, manifest, rr_settings=settings)
    session.active = True
    payload = {"nonce": session.nonce, "event": {"kind": "input", "value": "PRIVATE_VALUE"}}
    if failure == "size":
        payload["event"]["value"] *= 1000
    elif failure == "rate":
        assert session._rate_limit_ok()
    else:
        original = store.append_event

        def append(recording_id, event):
            if event["kind"] != "capture_warning":
                raise OSError("storage unavailable")
            original(recording_id, event)

        monkeypatch.setattr(store, "append_event", append)
    session._on_binding_called({"name": session.binding_name, "payload": json.dumps(payload)})
    assert session.capture_warnings
    events = store.read_events("rec_limits")
    assert events[-1]["kind"] == "capture_warning" and "PRIVATE_VALUE" not in str(events)


def test_frame_url_survives_compilation_after_secret_query_redaction(tmp_path):
    from octop_browser.record.models import RecordingManifest

    from deepseek_tui.browser.recording import WorkbenchRecordSession

    store = RecordingStore(RecordReplaySettings(base_dir=tmp_path))
    manifest = RecordingManifest(recordingId="rec_url", createdAt="2026-10-12")
    store.create(manifest)
    session = WorkbenchRecordSession(SimpleNamespace(), store, manifest)
    session._append(
        {
            "kind": "input",
            "value": "draft",
            "target": {
                "tag": "input",
                "id": "q",
                "framePath": ["#frame"],
                "frameUrl": "https://example.test/?token=PRIVATE&item=1",
            },
        }
    )
    events = store.read_events("rec_url")
    doc = ScopedSemanticProcessor("rec_url", events).process()
    assert "PRIVATE" not in str(events) and "PRIVATE" not in doc.model_dump_json()
    assert doc.steps[0].target["frameUrl"].endswith("token=%2A%2A%2A&item=1")


@pytest.mark.parametrize(
    "target",
    [
        {"framePath": False},
        {"shadowPath": "#host"},
        {"framePath": ["#outer"] * 9},
        {"frameUrl": False},
    ],
)
async def test_invalid_saved_scope_cannot_take_control(tmp_path, monkeypatch, target):
    from octop_browser.record.models import SemanticStep, StepsDocument

    from deepseek_tui.browser import workflows
    from deepseek_tui.browser.service import BrowserRun, BrowserService

    service = BrowserService(tmp_path)
    run = BrowserRun("one", tmp_path, owner="user", generation=3)
    service.runs["one"] = run
    doc = StepsDocument(
        recordingId="rec_scope",
        steps=[SemanticStep(id="1", kind="click", target={"selectorCandidates": ["#q"], **target})],
    )
    monkeypatch.setattr(workflows, "read_workflow", lambda *args: doc)
    with pytest.raises(ValueError):
        await workflows.start_replay(service, "one", "rec_scope", {})
    assert run.owner == "user" and run.generation == 3 and run.demo_task is None


@pytest.mark.parametrize(
    "changes,inputs,verification",
    [
        ({}, {"draft": "x" * 8001}, []),
        ({"target": {"selectorCandidates": ["x" * 1001]}}, {"draft": "ok"}, []),
        ({"target": {"selectorCandidates": "#q"}}, {"draft": "ok"}, []),
        ({"target": {}}, {"draft": "ok"}, []),
        ({"target": {"selectorCandidates": ["#q"], "name": 7}}, {"draft": "ok"}, []),
        ({"expect": {"urlContains": "x" * 4097}}, {"draft": "ok"}, []),
        ({"expect": {"unsupported": "ok"}}, {"draft": "ok"}, []),
        ({}, {"draft": "ok"}, [{"type": "text_contains", "value": "x" * 8001}]),
        ({}, {"draft": "ok"}, [{"type": "selector_exists", "value": "x" * 1001}]),
        ({}, {"draft": "ok"}, [{"type": "input_value_equals", "value": "ok", "selector": 7}]),
    ],
)
async def test_all_replay_parameters_are_checked_before_ensure(
    tmp_path, monkeypatch, changes, inputs, verification
):
    from octop_browser.record.models import SemanticStep, StepsDocument

    from deepseek_tui.browser import workflows
    from deepseek_tui.browser.service import BrowserService

    step = SemanticStep(
        id="2", kind="fill", value="{{draft}}", target={"selectorCandidates": ["#q"]}
    ).model_copy(update=changes)
    doc = StepsDocument(
        recordingId="rec_preflight",
        steps=[SemanticStep(id="1", kind="click", target={"selectorCandidates": ["#save"]}), step],
        verification=verification,
    )
    service = BrowserService(tmp_path)
    service.ensure = AsyncMock()
    monkeypatch.setattr(workflows, "read_workflow", lambda *args: doc)
    with pytest.raises(ValueError):
        await workflows.start_replay(service, "one", "rec_preflight", inputs)
    service.ensure.assert_not_awaited()


async def test_replay_compiles_an_input_snapshot_without_mutating_saved_steps(tmp_path, monkeypatch):
    from octop_browser.record.models import SemanticStep, StepsDocument

    from deepseek_tui.browser import workflows
    from deepseek_tui.browser.service import BrowserRun, BrowserService

    doc = StepsDocument(
        recordingId="rec_snapshot",
        steps=[SemanticStep(id="1", kind="fill", value="{{draft}}",
                            target={"selectorCandidates": ["#q"]})],
    )
    run = BrowserRun("one", tmp_path, owner="user", generation=3)
    service = BrowserService(tmp_path)
    service.runs["one"] = run
    service.ensure = AsyncMock(return_value=run)
    replay = AsyncMock()
    monkeypatch.setattr(workflows, "read_workflow", lambda *args: doc)
    monkeypatch.setattr(workflows, "_replay", replay)
    monkeypatch.setattr("deepseek_tui.browser.observation.root_context", AsyncMock())
    monkeypatch.setattr("deepseek_tui.browser.observation.evaluate", AsyncMock(return_value=True))
    inputs = {"draft": "😀" * 7989 + "{{literal}}"}
    await workflows.start_replay(service, "one", "rec_snapshot", inputs)
    inputs["draft"] = "changed after launch"
    await run.demo_task
    compiled = replay.call_args.args[2]
    assert compiled.steps[0].value == "😀" * 7989 + "{{literal}}"
    assert doc.steps[0].value == "{{draft}}"
    assert replay.call_args.args[3] is None


@pytest.mark.parametrize("failure", ["exception_details", "disconnect", "missing_recorder"])
async def test_stop_flush_failure_is_saved_as_incomplete_and_blocks_reuse(tmp_path, failure):
    from octop_browser.record.models import RecordingManifest

    from deepseek_tui.browser.recording import WorkbenchRecordSession
    from deepseek_tui.browser.service import BrowserService
    from deepseek_tui.browser.workflows import assert_capture_complete, finish_recording, recording_store

    service = BrowserService(tmp_path)
    store = recording_store(service, "one")
    manifest = RecordingManifest(recordingId="rec_stop", createdAt="2026-10-13")
    store.create(manifest)

    async def send(method, params=None):
        if method == "Runtime.evaluate":
            if failure == "disconnect":
                raise ConnectionError("PRIVATE_PAYLOAD_MUST_NOT_BE_SAVED")
            if failure == "exception_details":
                return {"exceptionDetails": {"text": "PRIVATE_PAYLOAD_MUST_NOT_BE_SAVED"}}
            return {"result": {"value": False}}
        return {}

    client = SimpleNamespace(send=AsyncMock(side_effect=send), close=AsyncMock())
    recorder = WorkbenchRecordSession(client, store, manifest)
    recorder.active = True
    recorder.flush_wait = 0
    recorder.scripts[id(client)] = "installed-script"
    run = SimpleNamespace(recorder=recorder)
    with pytest.raises(ValueError, match="incomplete browser capture"):
        await finish_recording(run)
    assert run.recorder is None and store.read_manifest("rec_stop").status == "failed"
    assert "PRIVATE_PAYLOAD" not in str(store.read_events("rec_stop"))
    with pytest.raises(ValueError, match="incomplete browser capture"):
        assert_capture_complete(service, "one", "rec_stop")
    client.close.assert_awaited_once()


@pytest.mark.parametrize("still_there", [False, True])
async def test_frame_sync_skips_a_frame_torn_down_mid_sync(tmp_path, monkeypatch, still_there):
    from octop_browser.record.models import RecordingManifest

    from deepseek_tui.browser import recording
    from deepseek_tui.browser.recording import WorkbenchRecordSession
    from deepseek_tui.browser.service import BrowserService
    from deepseek_tui.browser.workflows import recording_store

    store = recording_store(BrowserService(tmp_path), "one")
    manifest = RecordingManifest(recordingId="rec_frames", createdAt="2026-10-25")
    store.create(manifest)
    listings = [[{"id": "top"}, {"id": "ad", "parent_id": "top"}]]
    listings.append(listings[0] if still_there else [{"id": "top"}])

    async def discover(_client):
        return listings.pop(0) if len(listings) > 1 else listings[0]

    async def create(_parent, _frame_id):
        raise ValueError("Frame must be a current descendant of this page")

    monkeypatch.setattr(recording, "discover_frames", discover)
    monkeypatch.setattr(recording.FrameContext, "create", create)
    monkeypatch.setattr(recording, "evaluate", AsyncMock(return_value={"url": "https://a.example/"}))
    recorder = WorkbenchRecordSession(SimpleNamespace(send=AsyncMock()), store, manifest)
    recorder._clients["tab"] = SimpleNamespace()
    if still_there:
        with pytest.raises(ValueError, match="current descendant"):
            await recorder._sync_frames()
    else:
        await recorder._sync_frames()
        assert recorder.frames == {}


async def test_stop_waits_for_a_page_still_loading_from_the_last_click(tmp_path):
    from octop_browser.record.models import RecordingManifest

    from deepseek_tui.browser.recording import WorkbenchRecordSession
    from deepseek_tui.browser.service import BrowserService
    from deepseek_tui.browser.workflows import finish_recording, recording_store

    service = BrowserService(tmp_path)
    store = recording_store(service, "one")
    manifest = RecordingManifest(recordingId="rec_loading", createdAt="2026-10-25")
    store.create(manifest)
    checks = 0

    async def send(method, params=None):
        nonlocal checks
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "top"}}}
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 1}
        if method == "Runtime.evaluate":
            checks += 1
            # The new document has no recorder for the first few checks, as while it loads.
            return {"result": {"value": checks > 3}}
        return {}

    client = SimpleNamespace(send=AsyncMock(side_effect=send), close=AsyncMock())
    recorder = WorkbenchRecordSession(client, store, manifest)
    recorder.active = True
    recorder.flush_wait = 2
    recorder.scripts[id(client)] = "installed-script"
    result = await finish_recording(SimpleNamespace(recorder=recorder))
    assert result["recordingId"] == "rec_loading"
    assert store.read_manifest("rec_loading").status != "failed"
    assert not [e for e in store.read_events("rec_loading") if e.get("kind") == "capture_warning"]


def test_failed_manifest_without_warning_event_still_blocks_reuse(tmp_path):
    from octop_browser.record.models import RecordingManifest

    from deepseek_tui.browser.service import BrowserService
    from deepseek_tui.browser.workflows import assert_capture_complete, recording_store

    service = BrowserService(tmp_path)
    store = recording_store(service, "one")
    store.create(RecordingManifest(recordingId="rec_failed", createdAt="2026-10-13", status="failed"))
    with pytest.raises(ValueError, match="incomplete browser capture"):
        assert_capture_complete(service, "one", "rec_failed")


def _page_event(seq, kind, **extra):
    return {"seq": seq, "kind": kind, "targetId": "tab",
            "page": {"url": "https://shop.example/login"}, **extra}


def test_page_scroll_does_not_block_replay_or_skills():
    from deepseek_tui.browser.workflows import compile_workflow

    button = {"tag": "button", "role": "button", "name": "Login", "id": "go",
              "selectorCandidates": ['[id="go"]']}
    doc = ScopedSemanticProcessor("rec_scroll", [
        _page_event(1, "recorder_installed"),
        _page_event(2, "scroll", scroll={"x": 0, "y": 640}),
        _page_event(3, "click", target=button),
    ]).process()
    assert [step.kind for step in doc.steps] == ["open", "click"]
    compile_workflow(doc, {})


def test_masked_inputs_are_named_by_field_and_only_secrets_are_sensitive():
    account = {"tag": "input", "type": "text", "role": "textbox", "id": "fm-login-id",
               "nameAttr": "loginId", "selectorCandidates": ['[name="loginId"]']}
    password = {**account, "type": "password", "id": "fm-login-password",
                "nameAttr": "password", "selectorCandidates": ['[name="password"]']}
    doc = ScopedSemanticProcessor("rec_login", [
        _page_event(1, "recorder_installed"),
        _page_event(2, "input", target=account, value="{{sensitive_value}}", redacted=True),
        _page_event(3, "input", target=password, value="{{sensitive_value}}", redacted=True),
    ]).process()
    assert [(item["name"], item["sensitive"]) for item in doc.inputs] == [
        ("loginid", False), ("password", True)]
    assert [step.value for step in doc.steps if step.kind == "fill"] == [
        "{{loginid}}", "{{password}}"]
    assert all("example" not in item for item in doc.inputs)


@pytest.mark.parametrize(("kind", "inputs"), [("confirm", 0), ("prompt", 1)])
async def test_only_prompt_dialogs_require_a_replay_answer(tmp_path, kind, inputs):
    from unittest.mock import Mock

    from octop_browser.record.models import PrivacySettings
    from octop_browser.record.privacy import redact_event

    from deepseek_tui.browser.native import NativeBrowserEvents
    from deepseek_tui.browser.service import BrowserAction, BrowserService

    run = SimpleNamespace(thread_id="one", generation=0, tabs=[], recorder=Mock())
    native = NativeBrowserEvents(run, BrowserService(tmp_path))
    native.dialog = {"id": "d", "generation": 0, "type": kind,
                     "client": SimpleNamespace(send=AsyncMock())}
    await native.handle_dialog(
        BrowserAction(action="handle_dialog", dialog_id="d", accept=True, text="x"))
    event = redact_event({"seq": 2, **run.recorder._append.call_args.args[0]},
                         PrivacySettings(input_policy="mask-all"))
    doc = ScopedSemanticProcessor(
        "rec_dialog", [_page_event(1, "recorder_installed"), event]).process()
    assert [step.kind for step in doc.steps] == ["open", "handle_dialog"]
    assert len(doc.inputs) == inputs


@pytest.mark.parametrize("actor", ["agent", "user"])
async def test_turn_end_saves_only_explicit_agent_recordings(tmp_path, monkeypatch, actor):
    import asyncio
    from deepseek_tui.browser.service import BrowserService
    from deepseek_tui.browser import workflows

    service = BrowserService(tmp_path)
    run = SimpleNamespace(recorder=SimpleNamespace(actor=actor), lock=asyncio.Lock())
    service.runs["thread"] = run
    finish = AsyncMock()
    monkeypatch.setattr(workflows, "finish_recording", finish)

    await service.end_agent_capture("thread")

    if actor == "agent":
        finish.assert_awaited_once_with(run)
    else:
        finish.assert_not_awaited()


@pytest.mark.parametrize("opened,popup,expected", [
    ([], False, "new_tab"),
    (["fresh"], False, "switch_tab"),
    (["fresh"], True, "new_tab"),
    (["fresh", "another"], False, "ambiguous"),
])
async def test_replay_adopts_only_an_unambiguous_fresh_ordinary_tab(opened, popup, expected):
    from deepseek_tui.browser.workflows import _step

    url = "https://example.test/child"
    tabs = [{"tab_id": "user", "url": url, "active": True},
            {"tab_id": "fresh", "url": url, "popup": popup},
            {"tab_id": "another", "url": url}]
    run = SimpleNamespace(thread_id="t", generation=2, replay_tabs={}, tabs=tabs)
    service = SimpleNamespace(_refresh_tabs=AsyncMock(return_value=tabs),
                              action=AsyncMock(return_value={"success": True}))
    step = SimpleNamespace(kind="new_tab", url=url, target={"tabAlias": "child"})
    if expected == "ambiguous":
        with pytest.raises(ValueError, match="More than one"):
            await _step(service, run, step, {}, opened)
        service.action.assert_not_awaited()
    else:
        assert (await _step(service, run, step, {}, opened))["success"]
        action = service.action.await_args.args[1]
        assert action.action == expected
        if expected == "switch_tab":
            assert action.tab_id == "fresh" and run.replay_tabs["child"] == "fresh"


@pytest.mark.parametrize("driver", ["trace", "replay"])
async def test_replay_keeps_explicit_new_tabs_distinct_and_only_carries_click_results(tmp_path, monkeypatch, driver):
    from unittest.mock import Mock
    from octop_browser.record.models import SemanticStep, StepsDocument
    from deepseek_tui.browser import workflows
    from deepseek_tui.browser.service import BrowserRun

    run = BrowserRun("one", tmp_path, owner="agent")
    service = SimpleNamespace(ensure=AsyncMock(return_value=run), _capture=AsyncMock(return_value=b""),
                              _save=Mock(), stop_video=AsyncMock(), _finish_recording=Mock(), _persist=Mock())
    doc = StepsDocument(recordingId="rec_tabs", steps=[
        SemanticStep(id="1", kind="open", url="https://example.test/"),
        SemanticStep(id="2", kind="click", target={"selectorCandidates": ["#link"]}),
        SemanticStep(id="3", kind="new_tab", url="https://example.test/child", target={"tabAlias": "child"}),
        SemanticStep(id="4", kind="new_tab", url="https://example.test/child", target={"tabAlias": "other"}),
    ])
    received = []

    async def execute(service, run, step, inputs, opened):
        received.append(list(opened))
        return {"success": True, "tab_changes": {"opened": ["opened-by-" + step.id]}}

    monkeypatch.setattr(workflows, "_step", execute)
    monkeypatch.setattr(workflows.shutil, "which", lambda _: None)
    if driver == "trace":
        result = await workflows.run_trace(service, "one", doc, {}, secrets=set())
        assert result["completed"] == ["1", "2", "3", "4"]
    else:
        await workflows._replay(service, run, doc, None)
        assert run.demo_status == "passed", run.error
    assert received == [[], [], ["opened-by-2"], []]


async def test_concurrent_page_discovery_installs_one_recorder_per_tab(tmp_path, monkeypatch):
    import asyncio
    from octop_browser.record import recorder as upstream
    from octop_browser.record.models import RecordingManifest
    from deepseek_tui.browser.recording import WorkbenchRecordSession

    store = RecordingStore(RecordReplaySettings(base_dir=tmp_path))
    manifest = RecordingManifest(recordingId="rec_concurrent", createdAt="2026-10-26")
    store.create(manifest)
    recorder = WorkbenchRecordSession(SimpleNamespace(), store, manifest)
    recorder._target_infos = AsyncMock(return_value=[{
        "id": "new-tab", "webSocketDebuggerUrl": "ws://example.test/page", "url": "https://example.test/"
    }])
    installed = []

    async def install(client, target_id):
        await asyncio.sleep(0)
        installed.append(target_id)

    monkeypatch.setattr(upstream, "CDPClient", lambda **_: SimpleNamespace(connect=AsyncMock(), close=AsyncMock()))
    monkeypatch.setattr(recorder, "_install_on_client", install)
    await asyncio.gather(recorder._attach_known_targets(), recorder._attach_known_targets())
    assert installed == ["new-tab"]
    assert list(recorder._clients) == ["new-tab"]
