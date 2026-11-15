import json
from zipfile import ZipFile

import pytest

from deepseek_tui.browser.service import BrowserAction
from deepseek_tui.browser.snapshots import read, remember
from tests.test_browser_observation import browser


def test_cache_is_bounded_and_does_not_expose_field_values():
    cache = {}
    for i in range(5):
        remember(cache, {"observation_id": str(i), "text": "a" * 65000,
                         "elements": [{"name": "Name", "value": "PRIVATE"}]})
    assert list(cache) == ["1", "2", "3", "4"]
    assert cache["4"]["cache_truncated"]
    assert len(cache["4"]["text"]) == 64000
    assert "PRIVATE" not in json.dumps(cache)
    with pytest.raises(ValueError, match="not cached"):
        read(cache, "0")


def test_search_pages_and_offsets_preserve_unicode():
    cache = {}
    remember(cache, {"observation_id": "o", "text": "中文🧪abc " * 10})
    first = read(cache, "o", "🧪")
    second = read(cache, "o", "🧪", first["next_text_offset"])
    assert len(first["matches"]) == 8 and len(second["matches"]) == 2
    assert second["next_text_offset"] is None
    assert not read(cache, "o", "ABC")["matches"]
    assert first["actionable"] is False


async def test_cache_read_never_contacts_page_or_reconciles_unknown(tmp_path):
    service, run, _, page = browser(tmp_path)
    observation = (await service.action("t", BrowserAction(action="observe")))["observation"]
    run.unresolved["pending"] = {"execution": "unknown"}
    run.owner = "user"
    run.session._internal.client.send.reset_mock()
    result = await service.action("t", BrowserAction(
        action="read_observation", observation_id=observation["observation_id"], text="川沙"))
    assert result["content"]["matches"]
    run.session._internal.client.send.assert_not_awaited()
    assert run.owner == "user" and "pending" in run.unresolved
    assert run.latest_observation is observation
    with pytest.raises(ValueError):
        await service.action("other", BrowserAction(
            action="read_observation", observation_id=observation["observation_id"]))


@pytest.mark.parametrize("state,expected", [
    ({"unresolved": {"u": {"execution": "unknown"}}}, "inconclusive"),
    ({"demo_status": "failed"}, "inconclusive"),
    ({}, "passed"),
])
def test_export_separates_checks_from_execution(tmp_path, state, expected):
    service, run, _, _ = browser(tmp_path)
    run.log = [{"action": "wait", "success": True,
                "verification": {"kind": "text_contains"}}]
    for key, value in state.items():
        setattr(run, key, value)
    with ZipFile(service.export_evidence("t")) as archive:
        report = json.loads(archive.read("report.json"))
    assert report["assertion_status"] == "passed"
    assert report["verification"] == expected
    assert report["coverage"]["complete_task"] is False
    assert report["unresolved"] == list(run.unresolved.values())


def test_read_requires_explicit_snapshot():
    with pytest.raises(ValueError, match="explicit observation_id"):
        BrowserAction(action="read_observation")


def test_model_budget_keeps_cache_cursors_and_historical_boundary():
    from deepseek_tui.browser.context import project_result

    cache = {}
    remember(cache, {"observation_id": "o", "text": "中文 article " * 1000})
    for query in ("", "article"):
        response = {"success": True, "content": read(cache, "o", query)}
        projected = json.loads(project_result(response, 1400))["content"]
        assert projected["observation_id"] == "o"
        assert projected["historical"] and not projected["actionable"]
        assert projected["next_text_offset"] is not None
        continuation = read(cache, "o", query, projected["next_text_offset"])
        if query:
            assert continuation["matches"][0]["offset"] > projected["matches"][-1]["offset"]
        else:
            assert projected["text"] + continuation["text"] == cache["o"]["text"][:
                len(projected["text"]) + len(continuation["text"])]
