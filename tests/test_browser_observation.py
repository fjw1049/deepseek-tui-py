"""Observation identity and action feedback through the real BrowserService."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService


def browser(tmp_path):
    frame = {"id": "tab", "loaderId": "doc", "url": "https://example.test"}
    page = {
        "url": frame["url"],
        "title": "Results",
        "text": "川沙店 4.8分",
        "elements": [{"ref": "e0", "role": "button", "name": "川沙店"}],
        "viewport": {"width": 1200, "height": 760, "scroll_x": 0, "scroll_y": 0},
        "truncated": False,
        "warnings": [],
    }

    async def send(method, params=None):
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 1}
        if method == "Page.bringToFront":
            return {}
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": frame}}
        if method == "Runtime.evaluate":
            return {"result": {"value": page}}
        raise AssertionError(method)

    session = SimpleNamespace(
        _internal=SimpleNamespace(client=SimpleNamespace(send=AsyncMock(side_effect=send))),
        navigate=AsyncMock(return_value=SimpleNamespace(success=True, content="opened")),
        click=AsyncMock(return_value=SimpleNamespace(success=True, content="clicked")),
    )
    service = BrowserService(tmp_path)
    run = BrowserRun("t", tmp_path, session=session)
    service.runs["t"] = run
    return service, run, frame, page


async def test_observe_returns_text_and_new_identity(tmp_path):
    service, run, _, _ = browser(tmp_path)
    first = await service.action("t", BrowserAction(action="observe", level="full"))
    second = await service.action("t", BrowserAction(action="observe"))
    assert first["observation"]["text"] == "川沙店 4.8分"
    assert first["observation"]["observation_id"] != second["observation"]["observation_id"]
    assert run.latest_observation == second["observation"]


async def test_stale_target_is_not_dispatched(tmp_path):
    service, run, _, _ = browser(tmp_path)
    first = await service.action("t", BrowserAction(action="observe"))
    await service.action("t", BrowserAction(action="observe"))
    result = await service.action(
        "t",
        BrowserAction(
            action="click",
            ref="e0",
            observation_id=first["observation"]["observation_id"],
        ),
        require_observation=True,
    )
    assert result["receipt"]["execution"] == "not_executed"
    assert result["receipt"]["reason"] == "stale_observation"
    run.session.click.assert_not_called()


async def test_completed_navigation_survives_failed_observation(tmp_path):
    service, run, _, _ = browser(tmp_path)
    original = run.session._internal.client.send.side_effect

    async def fail_read(method, params=None):
        if method == "Runtime.evaluate":
            raise RuntimeError("observation disconnected")
        return await original(method, params)

    run.session._internal.client.send.side_effect = fail_read
    result = await service.action("t", BrowserAction(action="open", url="https://example.test"))
    assert result["success"]
    assert result["receipt"]["execution"] == "executed"
    assert result["receipt"]["effect"] == "unchecked"
    assert result["observation_error"]
    assert run.session.navigate.await_count == 1


async def test_trace_does_not_include_fill_values(tmp_path):
    service, run, _, _ = browser(tmp_path)
    await service.action("t", BrowserAction(action="open", url="https://example.test"))
    saved = json.loads((tmp_path / "t" / "result.json").read_text())
    assert saved["log"][-1]["action_id"]
    assert saved["log"][-1]["after_observation_id"]
    assert "川沙店" not in json.dumps(saved["log"], ensure_ascii=False)


async def test_nested_resolution_failure_is_logged_before_dispatch(tmp_path, monkeypatch):
    service, run, _, _ = browser(tmp_path)
    monkeypatch.setattr(
        "deepseek_tui.browser.service.target", AsyncMock(return_value={"nested": True, "ref": "e0"})
    )
    result = await service.action(
        "t",
        BrowserAction(action="click", ref="e0", observation_id="current"),
        require_observation=True,
    )
    assert result["receipt"]["execution"] == "not_executed"
    assert result["receipt"]["reason"] == "target_resolution_unavailable"
    run.session.click.assert_not_called()
    assert run.log[-1]["action_id"] == result["receipt"]["action_id"]


async def test_uncertain_action_reaches_model_as_receipt(tmp_path, monkeypatch):
    from deepseek_tui.tools.browser import BrowserUseTool

    service, run, _, _ = browser(tmp_path)
    monkeypatch.setattr(
        "deepseek_tui.browser.service.target",
        AsyncMock(return_value={"selector": "#exact", "x": 30, "y": 30}),
    )
    run.session.click.side_effect = ConnectionError("response lost after dispatch")
    result = await BrowserUseTool().execute(
        {"action": "click", "ref": "e0", "observation_id": "current"},
        SimpleNamespace(metadata={"browser_service": service, "runtime_thread_id": "t"}),
    )
    data = json.loads(result.content)
    assert not result.success and data["receipt"]["execution"] == "unknown"
    assert run.latest_observation is None
    assert run.session.click.await_count == 1


def test_browser_parameters_explain_observation_and_wait_contract():
    from deepseek_tui.tools.browser import BrowserUseTool

    properties = BrowserUseTool().input_schema()["properties"]
    assert all(p.get("description") for p in properties.values())
    assert "required" in properties["observation_id"]["description"]
    assert "disappearance" in properties["wait_state"]["description"]


async def test_duplicate_operation_returns_its_receipt_without_dispatch(tmp_path, monkeypatch):
    service, run, _, _ = browser(tmp_path)
    monkeypatch.setattr("deepseek_tui.browser.service.target", AsyncMock(
        return_value={"selector": "#exact", "x": 30, "y": 30}))
    action = BrowserAction(action="click", ref="e0", observation_id="current", operation_id="request-1")
    first = await service.action("t", action, require_observation=True)
    second = await service.action("t", action, require_observation=True)
    assert second["duplicate"] and first["receipt"]["action_id"] == second["receipt"]["action_id"]
    run.session.click.assert_awaited_once()
    assert service.operation("t", first["receipt"]["action_id"])["receipt"]["execution"] == "executed"


async def test_not_executed_operation_id_can_be_retried(tmp_path, monkeypatch):
    service, run, _, _ = browser(tmp_path)
    async def resolve(run, action):
        if action.observation_id == "old":
            return {"error": "stale_observation"}
        return {"selector": "#exact", "x": 30, "y": 30}

    monkeypatch.setattr("deepseek_tui.browser.service.target", resolve)
    stale = BrowserAction(action="click", ref="e0", observation_id="old", operation_id="retry-1")
    rejected = await service.action("t", stale, require_observation=True)
    assert rejected["receipt"]["execution"] == "not_executed"
    # The retry carries a fresh observation, so its arguments differ; it still runs once.
    retry = stale.model_copy(update={"observation_id": "current"})
    done = await service.action("t", retry, require_observation=True)
    assert done["receipt"]["execution"] == "executed" and not done.get("duplicate")
    again = await service.action("t", retry, require_observation=True)
    assert again["duplicate"]
    run.session.click.assert_awaited_once()


async def test_unknown_receipt_survives_log_clear_and_persistence_failure(tmp_path, monkeypatch):
    import pytest

    from deepseek_tui.browser.service import BrowserActionError

    service, run, _, _ = browser(tmp_path)
    async def lost_response(run, action):
        run.last_dispatch_id = action._action_id
        raise ConnectionError("response lost")
    monkeypatch.setattr(service, "_action", lost_response)
    monkeypatch.setattr(service, "_persist", lambda run: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(BrowserActionError) as error:
        await service.action("t", BrowserAction(action="reload"))
    receipt = error.value.response["receipt"]
    run.log.clear()
    assert receipt["action_id"] in run.unresolved
    assert service.operation("t", receipt["action_id"])["receipt"]["execution"] == "unknown"
    assert error.value.response["evidence_warning"]


async def test_http_error_preserves_the_same_unknown_receipt():
    import pytest
    from fastapi import HTTPException

    from deepseek_tui.browser.service import BrowserActionError
    from deepseek_tui.server.browser_routes import action

    response = {"success": False, "content": "Inspect before retrying", "receipt": {
        "action_id": "operation", "execution": "unknown", "effect": "unchecked"}}
    service = SimpleNamespace(runs={"one": object()}, action=AsyncMock(side_effect=BrowserActionError(response)))
    manager = SimpleNamespace(browser_service=service, store=SimpleNamespace(load_thread=lambda _: None))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_manager=manager)))
    with pytest.raises(HTTPException) as error:
        await action(request, "one", BrowserAction(action="reload", generation=1))
    assert error.value.detail == response
