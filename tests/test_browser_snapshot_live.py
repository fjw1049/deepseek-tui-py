"""Real Chromium and local business-shaped pages; no model calls or external accounts.

DEEPSEEK_BROWSER_E2E=1 enables these cases. Cached reads must issue zero CDP calls.
"""
import json
import os
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

from deepseek_tui.browser.observation import evaluate
from deepseek_tui.browser.service import BrowserAction, BrowserService
from scripts.browser_benchmark import serve_fixture


@pytest.fixture
async def live(tmp_path):
    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Requires local Chromium")
    body = ("""<!doctype html><meta charset=utf-8><title>Task records</title>
    <main><h1>采购记录 Purchase records</h1>
    <table><tr><th>订单</th><th>状态</th></tr><tr><td>PO-42</td><td>待收货</td></tr></table>
    <p id=status>Pending approval</p><button aria-label="Export ledger">⇩</button>
    <label>Account<input value="PRIVATE_ACCOUNT"></label><input type=password value="SECRET_123">
    <div id=shadow></div><iframe id=frame srcdoc="<p>Invoice INV-731 paid</p>
    <div id='frame-editor' contenteditable='true'>Frame draft</div>"></iframe>
    <div id=editor contenteditable=true><h2>会议安排</h2><p>周三下午</p></div>
    <button id=save onclick="setTimeout(()=>
    document.querySelector('#status').textContent='Approved',100)">Approve</button>
    <article>""" + "\n".join(f"Record {i}: 仓库 Shanghai item" for i in range(250)) + """</article>
    <script>document.querySelector('#shadow').attachShadow({mode:'open'}).innerHTML=
    '<p>Shipment SH-93 delivered</p>';</script>
    </main>""").encode()
    server, url = await serve_fixture(body)
    service = BrowserService(tmp_path / "evidence")
    service.configure("t", persistent=False)
    try:
        opened = await service.action("t", BrowserAction(action="open", url=url))
        assert opened["success"], opened
        yield service, service.runs["t"]
    finally:
        await service.close_all()
        server.close()
        await server.wait_closed()


async def observe(service, **args):
    return (await service.action("t", BrowserAction(action="observe", **args)))["observation"]


async def cached(service, run, snapshot, **args):
    client = run.session._internal.client
    send = client.send
    client.send = AsyncMock(side_effect=AssertionError("Cached reading contacted the browser"))
    try:
        result = await service.action("t", BrowserAction(
            action="read_observation", observation_id=snapshot["observation_id"], **args))
        client.send.assert_not_awaited()
        assert result["content"]["historical"] and not result["content"]["actionable"]
        assert run.latest_observation["observation_id"] == snapshot["observation_id"]
        return result["content"]
    finally:
        client.send = send


@pytest.mark.parametrize("scope,query", [
    ({"selector": "article"}, "Record 170"),
    ({"selector": "table"}, "PO-42"),
    ({"selector": "h1"}, "采购记录"),
    ({}, "Export ledger"),
    ({"shadow_path": ["#shadow"]}, "SH-93"),
    ({"frame_selector": "#frame"}, "INV-731"),
], ids=["long-document", "order-table", "chinese", "accessible-label", "shadow-dom", "iframe"])
async def test_search_business_content(live, scope, query, record_property):
    service, run = live
    snapshot = await observe(service, **scope)
    result = await cached(service, run, snapshot, text=query)
    assert result["matches"]
    record_property("cached_read_cdp_calls", 0)
    record_property("full_observation_chars", len(json.dumps(snapshot, ensure_ascii=False)))
    record_property("cached_search_chars", len(json.dumps(result, ensure_ascii=False)))


async def test_read_long_document_in_fragments(live):
    service, run = live
    snapshot = await observe(service, selector="article")
    first = await cached(service, run, snapshot)
    assert first["next_text_offset"] == 3000
    second = await cached(service, run, snapshot, text_offset=3000)
    assert second["text"] == run.observation_cache[snapshot["observation_id"]]["text"][3000:6000]


async def test_search_repeated_rows_with_cursor(live):
    service, run = live
    snapshot = await observe(service, selector="article")
    first = await cached(service, run, snapshot, text="仓库")
    second = await cached(service, run, snapshot, text="仓库",
                          text_offset=first["next_text_offset"])
    assert len(first["matches"]) == len(second["matches"]) == 8
    assert first["matches"][-1]["offset"] < second["matches"][0]["offset"]


async def test_private_fields_are_not_cached(live):
    service, run = live
    snapshot = await observe(service)
    result = await cached(service, run, snapshot, text="SECRET_123")
    assert not result["matches"]
    assert "PRIVATE_ACCOUNT" not in json.dumps(run.observation_cache)
    assert result["coverage"] == "collected_observation_only"


async def test_dynamic_page_does_not_rewrite_historical_observation(live):
    service, run = live
    snapshot = await observe(service, selector="#status")
    await evaluate(run.session._internal.client,
                   "document.querySelector('#status').textContent='Approved'")
    assert (await cached(service, run, snapshot, text="Pending approval"))["matches"]
    assert not (await cached(service, run, snapshot, text="Approved"))["matches"]
    assert "Approved" in (await observe(service, selector="#status"))["text"]


def report(service):
    with ZipFile(service.export_evidence("t")) as archive:
        return json.loads(archive.read("report.json"))


async def test_conditional_wait_is_an_exported_assertion(live):
    service, run = live
    await observe(service)
    await service.action("t", BrowserAction(action="click", selector="#save"))
    result = await service.action("t", BrowserAction(
        action="wait", selector="#status", text="Approved", timeout_ms=2000))
    assert result["success"]
    exported = report(service)
    assert exported["assertion_status"] == exported["verification"] == "passed"
    assert exported["assertions"][-1]["action"] == "wait"
    assert exported["coverage"]["complete_task"] is False


async def test_plain_pause_does_not_claim_verification(live):
    service, _ = live
    await service.action("t", BrowserAction(action="wait", timeout_ms=20))
    assert report(service)["verification"] == "not_checked"


async def test_unresolved_autosave_is_not_hidden_by_a_passing_check(live):
    service, run = live
    await service.action("t", BrowserAction(action="check_text", text="Purchase records"))
    # Inject the lost acknowledgement boundary; the page/check above are real.
    service._remember_response(run, {"success": False, "content": "acknowledgement lost",
        "receipt": {"action_id": "lost", "action": "fill", "execution": "unknown"}})
    exported = report(service)
    assert exported["assertion_status"] == "passed"
    assert exported["verification"] == "inconclusive"
    assert exported["execution_status"] == "unknown"
    assert exported["unresolved"][0]["action_id"] == "lost"


async def test_failed_action_is_not_hidden_by_a_passing_check(live):
    service, _ = live
    await service.action("t", BrowserAction(action="check_text", text="Purchase records"))
    result = await service.action("t", BrowserAction(action="click", selector="#missing"),
                                  require_observation=True)
    assert not result["success"]
    exported = report(service)
    assert exported["assertion_status"] == "passed"
    assert exported["verification"] == "inconclusive"


@pytest.mark.parametrize("action", ["check_text", "wait"])
async def test_editor_check_returns_its_scoped_text_and_structure(live, action):
    service, _ = live
    result = await service.action("t", BrowserAction(
        action=action, selector="#editor", include_editable=True, text="周三下午"))
    assert result["success"]
    observation = result["observation"]
    assert observation["scope_selector"] == "#editor"
    assert "周三下午" in observation["text"]
    assert observation["editor"]["visible_blocks"]
    assert "Purchase records" not in observation["text"]


async def test_hidden_wait_still_returns_page_when_target_disappears(live):
    service, run = live
    await evaluate(run.session._internal.client,
                   "(document.querySelector('#editor').remove(), true)")
    result = await service.action("t", BrowserAction(
        action="wait", selector="#editor", wait_state="hidden", timeout_ms=100))
    assert result["success"] and result["observation"]
    assert "Purchase records" in result["observation"]["text"]


async def test_wait_for_multiple_matches_keeps_a_usable_page_observation(live):
    service, _ = live
    result = await service.action("t", BrowserAction(
        action="wait", selector="button", condition="selector_exists", timeout_ms=100))
    assert result["success"] and result["observation"]
    assert "Purchase records" in result["observation"]["text"]


@pytest.mark.parametrize("frame", [{"frame_selector": "#frame"}, {"frame_path": ["#frame"]}])
async def test_editor_check_preserves_resolved_frame(live, frame):
    service, _ = live
    result = await service.action("t", BrowserAction(
        action="check_text", selector="#frame-editor", include_editable=True,
        text="Frame draft", **frame))
    assert result["success"] and result["observation"]
    assert result["observation"]["frame_id"]
    assert "Frame draft" in result["observation"]["text"]
