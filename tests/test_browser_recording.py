"""Recording compilation must preserve scopes and distinct masked edits."""

import json
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
    run = SimpleNamespace(thread_id="t", generation=2, replay_tabs={}, tabs=tabs,
                          upload_root=None)
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


FIELD = {"tag": "input", "type": "text", "role": "textbox", "id": "q", "nameAttr": "q",
         "selectorCandidates": ['[id="q"]']}
ROW = {"tag": "div", "name": "First row", "clickable": True,
       "selectorCandidates": ["div#root > div:nth-of-type(2)"]}


def _edit(seq, revision, target=FIELD):
    return _page_event(seq, "input", target=target, value="{{sensitive_value}}", redacted=True,
                       inputRevision=revision)


def _compile(*events):
    return ScopedSemanticProcessor(
        "rec_test", [_page_event(1, "recorder_installed"), *events]).process()


def test_typing_one_value_is_one_step_with_one_parameter():
    doc = _compile(_edit(2, 1), _edit(3, 2), _edit(4, 3))
    assert [step.kind for step in doc.steps] == ["open", "fill"]
    assert [item["name"] for item in doc.inputs] == ["q"]


def test_a_recreated_field_or_an_action_between_edits_keeps_both():
    assert len(_compile(_edit(2, 1), _edit(3, 1)).inputs) == 2
    button = {"tag": "button", "role": "button", "id": "go", "selectorCandidates": ['[id="go"]']}
    doc = _compile(_edit(2, 1), _page_event(3, "click", target=button, detail=1), _edit(4, 2))
    assert [step.kind for step in doc.steps] == ["open", "fill", "click", "fill"]


def test_live_search_urls_are_the_fill_not_steps_of_their_own():
    doc = _compile(
        _edit(2, 1),
        _page_event(3, "navigation", urlAfter="https://shop.example/login?q=a",
                    withinDocument=True),
        _edit(4, 2),
        _page_event(5, "navigation", urlAfter="https://shop.example/login?q=ab",
                    withinDocument=True),
    )
    assert [step.kind for step in doc.steps] == ["open", "fill"]


def test_enter_and_the_click_it_causes_are_one_step():
    button = {"tag": "button", "role": "button", "id": "go", "selectorCandidates": ['[id="go"]']}
    doc = _compile(
        _page_event(2, "keydown", key="Enter", target=FIELD),
        _page_event(3, "click", target=button, detail=0),
    )
    assert [step.kind for step in doc.steps] == ["open", "press"]


def test_a_real_click_after_enter_is_kept():
    button = {"tag": "button", "role": "button", "id": "go", "selectorCandidates": ['[id="go"]']}
    doc = _compile(
        _page_event(2, "keydown", key="Enter", target=FIELD),
        _page_event(3, "click", target=button, detail=1),
    )
    assert [step.kind for step in doc.steps] == ["open", "press", "click"]


def test_clickable_rows_stay_and_stray_page_clicks_do_not():
    doc = _compile(
        _page_event(2, "click", target=ROW, detail=1),
        _page_event(3, "click", target={**ROW, "clickable": False}, detail=1),
    )
    assert [step.kind for step in doc.steps] == ["open", "click"]
    assert doc.steps[1].target["selectorCandidates"] == ROW["selectorCandidates"]
    assert doc.steps[1].target["tabAlias"] == "main" and doc.steps[1].id == "step_002"


def test_going_back_to_the_start_page_is_a_step_and_not_the_end_check():
    from deepseek_tui.browser.workflows import compile_workflow

    start, other = "https://shop.example/login", "https://shop.example/account"
    link = {"tag": "a", "role": "link", "id": "a", "selectorCandidates": ['[id="a"]']}
    doc = _compile(
        _page_event(2, "click", target=link, detail=1),
        _page_event(3, "navigation", urlAfter=other),
        _page_event(4, "navigation", urlAfter=start),
    )
    assert [(step.kind, step.url) for step in doc.steps[1:]] == [("click", None), ("open", start)]
    assert doc.steps[1].expect["urlContains"] == "/account" and not doc.verification
    compile_workflow(doc, {})


def test_return_navigation_is_preserved_even_after_a_click():
    start, other = "https://shop.example/login", "https://shop.example/account"
    link = {"tag": "a", "role": "link", "id": "a", "selectorCandidates": ['[id="a"]']}
    doc = _compile(
        _page_event(2, "navigation", urlAfter=other),
        _page_event(3, "click", target=link, detail=1),
        _page_event(4, "navigation", urlAfter=start),
    )
    assert [step.kind for step in doc.steps] == ["open", "navigate", "click", "open"]


def test_recorded_navigation_expectations_compile():
    from deepseek_tui.browser.workflows import compile_workflow

    link = {"tag": "a", "role": "link", "id": "a", "selectorCandidates": ['[id="a"]']}
    for url in ("https://shop.example/account", "https://shop.example/"):
        doc = _compile(_page_event(2, "click", target=link, detail=1),
                       _page_event(3, "navigation", urlAfter=url))
        assert doc.steps[1].expect["urlAfter"] == url
        compile_workflow(doc, {})


def test_unknown_step_expectations_are_still_refused():
    from deepseek_tui.browser.workflows import compile_workflow

    link = {"tag": "a", "role": "link", "id": "a", "selectorCandidates": ['[id="a"]']}
    doc = _compile(_page_event(2, "click", target=link, detail=1))
    doc.steps[1].expect = {"status": "200"}
    with pytest.raises(ValueError, match="Unsupported recorded step expectation"):
        compile_workflow(doc, {})


def test_workspace_pages_compile_only_inside_the_given_workspace(tmp_path):
    from deepseek_tui.browser.workflows import compile_workflow

    page = tmp_path / "page.html"
    doc = ScopedSemanticProcessor("rec_local", [
        {"seq": 1, "kind": "recorder_installed", "targetId": "tab",
         "page": {"url": page.as_uri()}},
        {"seq": 2, "kind": "click", "targetId": "tab", "page": {"url": page.as_uri()}, "detail": 1,
         "target": {"tag": "button", "role": "button", "id": "go",
                    "selectorCandidates": ['[id="go"]']}},
    ]).process()
    assert compile_workflow(doc, {}, tmp_path).steps[0].url == page.as_uri()
    with pytest.raises(ValueError, match="inside the workspace"):
        compile_workflow(doc, {})
    with pytest.raises(ValueError, match="inside the workspace"):
        compile_workflow(doc, {}, tmp_path / "elsewhere")


@pytest.mark.parametrize(("recording", "disabled"), [(True, []), (False, ["Runtime", "Log"])])
async def test_a_navigation_keeps_the_runtime_a_recording_shares(tmp_path, recording, disabled):
    from unittest.mock import Mock

    from deepseek_tui.browser.native import NativeBrowserEvents

    run = SimpleNamespace(thread_id="t", recorder=object() if recording else None)
    events = NativeBrowserEvents(run, SimpleNamespace(
        artifact_root=tmp_path, _saved_state=lambda _thread: {}))
    client = Mock(send=AsyncMock())
    events.console_clients.add(client)
    events.console.append({"seq": 1, "client": client})
    await events._reset_console(client)
    assert [call.args[0].split(".")[0] for call in client.send.await_args_list] == disabled
    assert (client in events.console_clients) is recording and events.console == []


PANEL = {"tag": "div", "id": "list", "selectorCandidates": ['[id="list"]', "div#list"]}
PAGE = {"tag": "html", "id": "", "selectorCandidates": ["html:nth-of-type(1)"]}


def _scroll(seq, y, target=PANEL):
    return _page_event(seq, "scroll", target=target, scroll={"x": 0, "y": y})


def test_separately_reported_scrolls_keep_each_position_and_container():
    from deepseek_tui.browser.workflows import compile_workflow

    doc = _compile(_scroll(2, 300), _scroll(3, 900))
    assert [(step.kind, step.value) for step in doc.steps] == [
        ("open", None), ("scroll_to", "0.000,300.000"), ("scroll_to", "0.000,900.000")]
    assert doc.steps[1].target["selectorCandidates"] == PANEL["selectorCandidates"]
    compile_workflow(doc, {})


def test_scrolls_of_different_containers_or_around_a_click_stay_apart():
    button = {"tag": "button", "role": "button", "id": "go", "selectorCandidates": ['[id="go"]']}
    apart = _compile(_scroll(2, 300), _scroll(3, 40, PAGE))
    assert [step.description for step in apart.steps[1:]] == ["Scroll a panel", "Scroll the page"]
    doc = _compile(_scroll(2, 300), _page_event(3, "click", target=button, detail=1),
                   _scroll(4, 600))
    assert [step.kind for step in doc.steps] == ["open", "scroll_to", "click", "scroll_to"]


@pytest.mark.parametrize("value", ["", "0", "x,y", "1,2,3"])
def test_scroll_steps_need_a_position(value):
    from deepseek_tui.browser.workflows import compile_workflow

    doc = _compile(_scroll(2, 300))
    doc.steps[1].value = value
    with pytest.raises(ValueError, match="x,y position"):
        compile_workflow(doc, {})


def _scrolling_service(positions, *, confirmed=True, container=True):
    """Observations report the next position; each wheel returns its receipt."""
    actions = []

    async def action(_thread, browser_action, **_kwargs):
        actions.append(browser_action)
        if browser_action.action == "scroll":
            effect = "confirmed" if confirmed else "not_confirmed"
            return {"success": True, "receipt": {"effect": effect}}
        position = {"scroll_x": 0, "scroll_y": positions.pop(0)}
        return {"observation": {"observation_id": "o", "viewport": position, "scroll_containers":
                                [{"ref": "c0", "viewport": position}] if container else []}}

    return SimpleNamespace(action=action), actions


async def test_replay_scrolls_a_panel_past_the_wheel_limit_until_it_arrives():
    from deepseek_tui.browser.workflows import _scroll_to

    service, actions = _scrolling_service([0, 1200, 2000])
    step = SimpleNamespace(value="0,2000", target=PANEL)
    result = await _scroll_to(service, SimpleNamespace(thread_id="t"), step, 3, "", [])
    wheels = [item for item in actions if item.action == "scroll"]
    assert result["success"] and [(w.ref, w.amount) for w in wheels] == [("c0", 1200), ("c0", 800)]


async def test_replay_scrolls_the_page_up_without_a_container():
    from deepseek_tui.browser.workflows import _scroll_to

    service, actions = _scrolling_service([500, 0])
    step = SimpleNamespace(value="0,0", target=PAGE)
    await _scroll_to(service, SimpleNamespace(thread_id="t"), step, 3, "", [])
    wheel = next(item for item in actions if item.action == "scroll")
    assert (wheel.ref, wheel.direction, wheel.amount) == (None, "up", 500)


async def test_shorter_content_ends_the_scroll_without_failing_the_workflow():
    from deepseek_tui.browser.workflows import _scroll_to

    service, actions = _scrolling_service([100], confirmed=False)
    step = SimpleNamespace(value="0,5000", target=PANEL)
    result = await _scroll_to(service, SimpleNamespace(thread_id="t"), step, 3, "", [])
    assert result["success"] and len([a for a in actions if a.action == "scroll"]) == 1


async def test_a_missing_panel_is_a_mismatch_not_a_silent_skip():
    from deepseek_tui.browser.workflows import _scroll_to

    service, _ = _scrolling_service([0, 0], container=False)
    step = SimpleNamespace(value="0,300", target=PANEL)
    with pytest.raises(ValueError, match="Replay target must"):
        await _scroll_to(service, SimpleNamespace(thread_id="t"), step, 3, "", [])


def test_the_recorder_context_is_the_one_it_reports_from(tmp_path):
    from deepseek_tui.browser.recording import WorkbenchRecordSession

    session = WorkbenchRecordSession.__new__(WorkbenchRecordSession)
    session.active, session.nonce, session.worlds = True, "nonce", {}
    client = object()

    def report(kind, nonce="nonce"):
        session._note_world({"__client": client, "executionContextId": 7, "payload": json.dumps(
            {"nonce": nonce, "event": {"kind": kind}})})

    report("click")
    report("recorder_installed", nonce="forged")
    assert session.worlds == {}
    report("recorder_installed")
    assert session.worlds == {id(client): 7}


@pytest.mark.parametrize(("alive", "context"), [
    ({"result": {"value": True}}, 7),  # A page with cross-origin frames: the name would miss.
    ({"result": {"value": False}}, 3),
    (RuntimeError("Cannot find context"), 3),  # Restored from the back/forward cache.
])
async def test_the_reported_world_is_used_while_the_recorder_is_there(alive, context):
    from deepseek_tui.browser.recording import WorkbenchRecordSession

    async def send(method, _params=None):
        if method == "Runtime.evaluate":
            if isinstance(alive, Exception):
                raise alive
            return alive
        return {"frameTree": {"frame": {"id": "main"}}, "executionContextId": 3}

    session = WorkbenchRecordSession.__new__(WorkbenchRecordSession)
    client = SimpleNamespace(send=send)
    session.worlds = {id(client): 7}
    assert (await session._world(client)).context_id == context


def test_a_click_inside_a_card_keeps_where_it_landed():
    card = {**ROW, "hit": {"x": .9, "y": .1}}
    doc = _compile(_page_event(2, "click", target=card, detail=1),
                   _page_event(3, "click", target={**ROW, "hit": {"x": .2, "y": .5}}, detail=1))
    assert [step.target["hit"]["x"] for step in doc.steps[1:]] == [.9, .2]


def test_a_named_card_clicked_at_a_point_is_one_step():
    card = {"tag": "div", "name": "Card", "id": "card", "clickable": True,
            "selectorCandidates": ['[id="card"]'], "hit": {"x": .9, "y": .1}}
    doc = _compile(_page_event(2, "click", target=card, detail=1))
    assert [step.kind for step in doc.steps] == ["open", "click"]



def test_scroll_round_trip_preserves_the_loading_step():
    doc = _compile(_scroll(2, 300), _scroll(3, 0))
    assert [step.value for step in doc.steps[1:]] == ['0.000,300.000', '0.000,0.000']


def test_scrolling_ends_a_continuous_edit():
    doc = _compile(_edit(2, 1), _scroll(3, 300), _edit(4, 2))
    assert [step.kind for step in doc.steps] == ['open', 'fill', 'scroll_to', 'fill']
    assert len(doc.inputs) == 2


def test_return_after_an_unrelated_click_preserves_navigation():
    start = 'https://shop.example/login'
    button = {'tag': 'button', 'role': 'button', 'selectorCandidates': ['#expand']}
    doc = _compile(
        _page_event(2, 'navigation', urlAfter='https://shop.example/account'),
        _page_event(3, 'click', target=button, detail=1),
        _page_event(4, 'navigation', urlAfter=start),
    )
    assert doc.steps[-1].kind == 'open' and doc.steps[-1].url == start


@pytest.mark.parametrize('already_there', [True, False])
async def test_return_navigation_observes_before_reopening(already_there):
    from octop_browser.record.models import SemanticStep
    from deepseek_tui.browser.workflows import _step

    url = 'https://shop.example/login'
    step = SemanticStep(id='return', kind='open', url=url, expect={'urlAfter': url})
    service = SimpleNamespace(action=AsyncMock(side_effect=[
        {'success': True, 'observation': {'url': url if already_there else url + '/other'}},
        {'success': True},
    ]))
    run = SimpleNamespace(generation=1, replay_tabs={}, thread_id='t', upload_root=None, tabs=[])
    result = await _step(service, run, step, None)
    assert result['success']
    assert [call.args[1].action for call in service.action.await_args_list] == (
        ['observe'] if already_there else ['observe', 'open'])


def test_same_document_return_after_an_edit_is_not_a_live_search_update():
    start = "https://shop.example/login"
    doc = _compile(
        _page_event(2, "navigation", urlAfter=start + "?page=2", withinDocument=True),
        _edit(3, 1),
        _page_event(4, "navigation", urlAfter=start, withinDocument=True),
    )
    assert doc.steps[-1].kind == "open" and doc.steps[-1].url == start
