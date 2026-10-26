def observation_cdp(session, text, url="https://example.test"):
    async def send(method, params=None):
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 1}
        if method == "Runtime.evaluate":
            return {"result": {"value": {"text": text, "elements": [], "url": url,
                "title": "Test", "viewport": {}, "warnings": [], "truncated": False}}}
        return {"frameTree": {"frame": {"id": "tab", "loaderId": "doc", "url": url}}}
    session._internal.client.send.side_effect = send


async def test_cookie_sync_consent_auth_and_private_results(authed_client, monkeypatch):
    from unittest.mock import AsyncMock

    source = AsyncMock(return_value={"cookies": [{
        "name": "synthetic", "value": "PRIVATE_SENTINEL", "domain": ".example.test",
        "path": "/", "secure": True, "httpOnly": True,
    }], "skipped": 0})
    monkeypatch.setattr("deepseek_tui.browser.cookies.CookieStore.read_source", source)
    monkeypatch.setattr("deepseek_tui.browser.chrome_cookies.profiles", lambda: [{"id": "Default", "name": "Personal"}])
    monkeypatch.setattr("deepseek_tui.browser.cookies.profiles", lambda: [{"id": "Default", "name": "Personal"}])
    client, _ = authed_client
    thread_id = (await client.post("/v1/threads", json={"title": "Cookies"})).json()["id"]
    path = f"/v1/threads/{thread_id}/browser/cookie-sync"
    assert (await client.get(path, headers={"Authorization": ""})).status_code == 401
    assert (await client.post(path, json={"action": "enable", "profile": "Default"}, headers={"Authorization": ""})).status_code == 401
    state = (await client.get(path)).json()
    assert state["consent"] == "pending" and state["profiles"][0]["id"] == "Default"
    assert (await client.post(path, json={"action": "enable", "profile": "../../other"})).status_code == 409
    listing = AsyncMock(return_value={"sites": [
        {"site": "example.test", "count": 1, "sensitive": False}]})
    monkeypatch.setattr("deepseek_tui.browser.cookies.CookieStore.list_source", listing)
    sites = await client.get(path + "/sites", params={"profile": "Default"})
    assert sites.json()["sites"][0]["site"] == "example.test"
    assert (await client.get(path + "/sites", params={"profile": "../x"})).status_code == 409
    listing.return_value = {"error": "permission"}
    refused = (await client.get(path + "/sites", params={"profile": "Default"})).json()
    assert refused == {"sites": [], "error": "permission"}
    listing.return_value = {"sites": [{"site": "example.test", "count": 1, "sensitive": False}]}
    state = (await client.post(path, json={
        "action": "enable", "profile": "Default", "sites": ["example.test"],
    })).json()
    assert state["consent"] == "enabled"
    assert (state["status"], state["count"], state["domains"]) == ("synced", 1, 1)
    source.assert_awaited_once_with("Default", ["example.test"])
    assert (await client.get(path)).json()["selected_sites"] == ["example.test"]
    assert "PRIVATE_SENTINEL" not in str(state)
    assert not {"cookies", "values", "path"} & state.keys()
    assert (await client.post(path, json={"action": "disable"})).json()["consent"] == "disabled"
    assert (await client.post(path, json={"action": "clear"})).json()["status"] == "cleared"


async def test_cookie_sync_never_pauses_a_running_task(
    authed_client, authed_runtime_app, tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.browser.service import BrowserRun
    from deepseek_tui.engine.handle import EngineHandle

    monkeypatch.setattr("deepseek_tui.browser.cookies.CookieStore.read_source", AsyncMock(
        return_value={"cookies": [{"name": "synthetic", "value": "v", "domain": ".example.test",
                                   "path": "/", "secure": True}], "skipped": 0}))
    monkeypatch.setattr("deepseek_tui.browser.cookies.profiles", lambda: [{"id": "Default"}])
    client, _ = authed_client
    app, _ = authed_runtime_app
    manager = app.state.thread_manager
    thread_id = (await client.post("/v1/threads", json={"title": "Cookies"})).json()["id"]
    path = f"/v1/threads/{thread_id}/browser/cookie-sync"
    manager.browser_service.cookies.configure("enabled", "Default")
    handle = EngineHandle()
    handle._mark_turn_active()
    turn = SimpleNamespace(turn_id="t")
    manager._active[thread_id] = SimpleNamespace(handle=handle, active_turn=turn)
    run = BrowserRun(thread_id, tmp_path / "page", agent_task=True, session=SimpleNamespace(
        _internal=SimpleNamespace(client=SimpleNamespace(send=AsyncMock(return_value={})))))
    manager.browser_service.runs[thread_id] = run
    try:
        response = await client.post(
            path, json={"action": "sync", "generation": 0, "sites": ["example.test"]},
        )
        assert response.status_code == 409 and "agent is using" in response.text
        assert not handle.pause.paused and run.owner == "agent"
        # Without a running task, sync borrows control briefly and hands it back.
        manager._active.pop(thread_id)
        response = await client.post(path, json={
            "action": "sync", "generation": run.generation, "sites": ["example.test"],
        })
        assert response.status_code == 200 and response.json()["status"] == "synced"
        assert run.owner == "agent"
    finally:
        manager._active.pop(thread_id, None)
        manager.browser_service.runs.pop(thread_id, None)


async def test_browser_routes_require_auth_and_existing_thread(authed_client):
    client, token = authed_client
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        await client.get("/v1/threads/missing/browser", headers={"Authorization": ""})
    ).status_code == 401
    assert (await client.get("/v1/threads/missing/browser", headers=headers)).status_code == 404
    created = await client.post("/v1/threads", json={"title": "Browser test"}, headers=headers)
    thread_id = created.json()["id"]
    base = f"/v1/threads/{thread_id}/browser"
    response = await client.get(base, headers=headers)
    assert response.status_code == 200
    assert response.json()["active"] is False
    assert (await client.post(base + "/export", json={}, headers=headers)).status_code == 409
    unauthenticated = await client.post(base + "/export", json={}, headers={"Authorization": ""})
    assert unauthenticated.status_code == 401
    invalid = await client.post(
        base + "/action", json={"action": "open", "url": "file:///etc/passwd"}, headers=headers
    )
    assert invalid.status_code == 422
    no_session = await client.post(base + "/control", json={"owner": "user"}, headers=headers)
    assert no_session.status_code == 409
    assert (await client.get(base + "/preferences")).json() == {"persistent": True}
    assert (await client.post(base + "/preferences", json={"persistent": True})).json() == {
        "persistent": True
    }
    assert (await client.get(base + "/environment")).status_code == 200
    invalid_flow = await client.post(
        base + "/workflows", json={"action": "preview", "recording_id": "../escape"}
    )
    assert invalid_flow.status_code == 409
    assert (await client.post(base + "/clear-profile", json={})).status_code == 200
    assert (await client.get(base + "/installation")).json()["status"] == "idle"
    assert (await client.post(base + "/installation", json={"action": "stop"})).status_code == 200
    assert (
        await client.post(
            base + "/skills",
            json={
                "action": "preview",
                "recording_id": "rec_test",
                "name": "../escape",
                "description": "test",
            },
        )
    ).status_code == 409


async def test_shared_viewport_routes_validate_auth_and_input(authed_client):
    client, token = authed_client
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post("/v1/threads", json={"title": "Shared browser"}, headers=headers)
    base = f"/v1/threads/{created.json()['id']}/browser"
    assert (await client.get(base + "/view", headers={"Authorization": ""})).status_code == 401
    view = await client.get(base + "/view", headers=headers)
    assert view.json()["active"] is False and view.json()["image"] is None
    body = {"kind": "text", "text": "private", "generation": 0}
    assert (
        await client.post(base + "/input", json=body, headers={"Authorization": ""})
    ).status_code == 401
    assert (await client.post(base + "/input", json=body, headers=headers)).status_code == 409
    body["generation"] = -1
    assert (await client.post(base + "/input", json=body, headers=headers)).status_code == 422


async def test_takeover_resumes_existing_turn_only_after_fresh_observation(
    authed_client, authed_runtime_app, tmp_path,
):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pytest

    from deepseek_tui.browser.service import BrowserRun
    from deepseek_tui.engine.handle import EngineHandle

    client, _ = authed_client
    app, _ = authed_runtime_app
    manager = app.state.thread_manager
    created = await client.post("/v1/threads", json={"title": "Takeover"})
    thread_id = created.json()["id"]
    base = f"/v1/threads/{thread_id}/browser"
    handle = EngineHandle()
    handle._mark_turn_active()
    turn = SimpleNamespace(turn_id="original")
    manager._active[thread_id] = SimpleNamespace(handle=handle, active_turn=turn)
    session = SimpleNamespace(
        dom_tree=AsyncMock(return_value=SimpleNamespace(
            success=True, content="Current region: US", error=None,
        )),
        _internal=SimpleNamespace(client=SimpleNamespace(send=AsyncMock(return_value={
            "frameTree": {"frame": {"url": "https://example.test/us"}},
        }))),
    )
    run = BrowserRun(thread_id, tmp_path / "page", session=session, agent_task=True)
    manager.browser_service.runs[thread_id] = run
    observation_cdp(run.session, run.session.dom_tree.return_value.content)
    try:
        response = await client.post(base + "/control", json={"owner": "user", "generation": 0})
        assert response.status_code == 200
        assert response.json()["task_paused"]
        assert handle.pause.paused
        await handle.steer("Keep the original task")
        assert handle.pause.paused
        generation = run.generation
        # Failed observation returns a recovery requirement, never stale refs.
        original_cdp = session._internal.client.send.side_effect
        session._internal.client.send.side_effect = ConnectionError("Page disconnected")
        response = await client.post(
            base + "/control", json={"owner": "agent", "generation": generation},
        )
        assert response.status_code == 200
        assert not handle.pause.paused and run.owner == "agent"
        assert run.latest_observation is None
        assert "unavailable" in handle.resume_context
        await client.post(base + "/control", json={"owner": "user", "generation": run.generation})
        generation = run.generation
        session._internal.client.send.side_effect = original_cdp
        response = await client.post(
            base + "/control", json={"owner": "agent", "generation": generation},
        )
        assert response.status_code == 200
        assert not handle.pause.paused
        assert run.owner == "agent"
        assert "Current region: US" in handle.resume_context
        assert "unknown" in handle.resume_context
        assert handle._op_queue.empty()
        assert manager._active[thread_id].active_turn is turn
        before = session._internal.client.send.await_count
        # A retry of the same response-lost request is idempotent.
        response = await client.post(
            base + "/control", json={"owner": "agent", "generation": generation},
        )
        assert response.status_code == 200
        assert session._internal.client.send.await_count == before
        # A stale takeover cannot revoke control after a later handoff.
        response = await client.post(base + "/control", json={"owner": "user", "generation": 0})
        assert response.status_code == 409
        assert not handle.pause.paused
        # Ending from a paused state wakes/cancels the original task.
        await client.post(base + "/control", json={"owner": "user", "generation": run.generation})
        session.close = AsyncMock()
        response = await client.post(
            base + "/control", json={"owner": "stopped", "generation": run.generation},
        )
        assert response.status_code == 200
        assert handle.cancel_event.is_set()
        with pytest.raises(asyncio.CancelledError):
            await handle.pause.wait(handle.cancel_event)
    finally:
        manager._active.pop(thread_id, None)
        manager.browser_service.runs.pop(thread_id, None)


async def test_returning_browser_without_active_turn_does_not_start_task(
    authed_client, authed_runtime_app, tmp_path,
):
    from types import SimpleNamespace

    from deepseek_tui.browser.service import BrowserRun

    client, _ = authed_client
    app, _ = authed_runtime_app
    manager = app.state.thread_manager
    thread_id = (await client.post("/v1/threads", json={"title": "Preview"})).json()["id"]
    manager.browser_service.runs[thread_id] = BrowserRun(
        thread_id, tmp_path, session=SimpleNamespace(), owner="user",
    )
    try:
        response = await client.post(
            f"/v1/threads/{thread_id}/browser/control", json={"owner": "agent", "generation": 0},
        )
        assert response.status_code == 200
        assert response.json()["task_running"] is False
        assert thread_id not in manager._active
        assert manager.store.load_thread(thread_id).latest_turn_id is None
    finally:
        manager.browser_service.runs.pop(thread_id, None)


async def test_real_browser_takeover_observes_manual_change_before_resuming(
    authed_client, authed_runtime_app, tmp_path,
):
    """Opt-in Chrome integration; local HTML and deterministic model, no network LLM."""
    import asyncio
    import os
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pytest

    from deepseek_tui.browser.service import BrowserAction
    from deepseek_tui.config.models import Config, FeatureConfig
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.engine.turn import TurnResult
    from deepseek_tui.protocol.messages import Message

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 for real Chrome")
    page = (b'<title>Takeover regression</title><p id="region">Region: Hong Kong</p>'
            b'<button id="us" onclick="document.getElementById(\'region\').textContent='
            b'\'Region: United States\'">Switch region</button>')

    async def serve(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                     + str(len(page)).encode() + b"\r\nConnection: close\r\n\r\n" + page)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    client, _ = authed_client
    app, _ = authed_runtime_app
    manager = app.state.thread_manager
    thread_id = (await client.post("/v1/threads", json={"title": "Takeover E2E"})).json()["id"]
    base = f"/v1/threads/{thread_id}/browser"
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle, client=AsyncMock(), working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False,
        )), start_mcp=False,
    )
    started, closed = asyncio.Event(), asyncio.Event()
    requests = []
    async def model(request, *args, **kwargs):
        requests.append(request.model_copy(deep=True))
        if len(requests) == 1:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        return TurnResult(assistant_message=Message.assistant("Read the selected region"))
    engine.turn_loop.run = model
    turn = SimpleNamespace(turn_id="same-turn")
    manager._active[thread_id] = SimpleNamespace(handle=handle, active_turn=turn)
    task = None
    try:
        await manager.browser_service.action(thread_id, BrowserAction(
            action="open", url=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}",
        ))
        task = asyncio.create_task(engine._run_conversation(
            [Message.user("Read US trends")], "deepseek-chat", "sys", None,
        ))
        await asyncio.wait_for(started.wait(), 2)
        state = (await client.get(base)).json()
        takeover = await client.post(base + "/control", json={
            "owner": "user", "generation": state["generation"],
        })
        assert takeover.status_code == 200, takeover.text
        await asyncio.wait_for(closed.wait(), 2)
        assert takeover.json()["task_paused"]
        clicked = await client.post(base + "/action", json={
            "action": "click", "selector": "#us", "generation": takeover.json()["generation"],
        })
        assert clicked.json()["success"]
        assert len(requests) == 1
        resumed = await client.post(base + "/control", json={
            "owner": "agent", "generation": takeover.json()["generation"],
        })
        assert resumed.status_code == 200, resumed.text
        await asyncio.wait_for(task, 3)
        assert len(requests) == 2
        assert "Region: United States" in requests[1].model_dump_json()
        assert manager._active[thread_id].active_turn is turn
        assert handle._op_queue.empty()
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        manager._active.pop(thread_id, None)
        await manager.browser_service.close_all()
        await engine.shutdown_session()
        server.close()
        await server.wait_closed()


async def test_browser_assistance_routes_pause_and_resume_original_task(
    authed_client,
    authed_runtime_app,
    tmp_path,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.browser.service import BrowserRun
    from deepseek_tui.engine.handle import EngineHandle

    client, _ = authed_client
    app, _ = authed_runtime_app
    manager = app.state.thread_manager
    thread_id = (await client.post("/v1/threads", json={"title": "Assistance"})).json()["id"]
    handle = EngineHandle()
    handle._mark_turn_active()
    manager._active[thread_id] = SimpleNamespace(
        handle=handle, active_turn=SimpleNamespace(turn_id="original")
    )
    run = BrowserRun(
        thread_id,
        tmp_path / "page",
        session=SimpleNamespace(
            dom_tree=AsyncMock(
                return_value=SimpleNamespace(success=True, content="Public manual", error=None)
            ),
            _internal=SimpleNamespace(client=SimpleNamespace(send=AsyncMock(return_value={}))),
        ),
    )
    manager.browser_service.runs[thread_id] = run
    observation_cdp(run.session, run.session.dom_tree.return_value.content)
    base = f"/v1/threads/{thread_id}/browser/assistance"
    try:
        assert (
            await client.get("/v1/browser-assistance", headers={"Authorization": ""})
        ).status_code == 401
        await manager.request_browser_assistance(thread_id, "Login needed")
        pending = (await client.get("/v1/browser-assistance")).json()["items"]
        request_id = pending[0]["id"]
        assert pending[0]["thread_id"] == thread_id and handle.pause.paused
        body = {"request_id": request_id, "choice": "takeover"}
        assert (
            await client.post(base, json=body, headers={"Authorization": ""})
        ).status_code == 401
        response = await client.post(base, json=body)
        assert response.json()["assistance"]["status"] == "human"
        assert response.json()["owner"] == "user"
        body["choice"] = "information"
        body["text"] = "Use the public manual"
        response = await client.post(base, json=body)
        assert response.status_code == 200 and not response.json()["task_paused"]
        assert handle.drain_steers() == ["Use the public manual"]
        assert (await client.get("/v1/browser-assistance")).json()["items"] == []
        assert (await client.post(base, json=body)).status_code == 409
    finally:
        manager._active.pop(thread_id, None)
        manager.browser_service.runs.pop(thread_id, None)


async def test_model_assistance_call_reaches_ui_and_returns_evidence(
    authed_client, authed_runtime_app, tmp_path,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.browser.service import BrowserAction, BrowserRun
    from deepseek_tui.engine.handle import EngineHandle

    client, _ = authed_client
    app, _ = authed_runtime_app
    manager = app.state.thread_manager
    thread_id = (await client.post("/v1/threads", json={"title": "Automatic help"})).json()["id"]
    handle = EngineHandle()
    handle._mark_turn_active()
    manager._active[thread_id] = SimpleNamespace(
        handle=handle, active_turn=SimpleNamespace(turn_id="original"),
    )
    run = BrowserRun(thread_id, tmp_path / "page", session=SimpleNamespace(
        dom_tree=AsyncMock(return_value=SimpleNamespace(success=True, content="Verify", error=None)),
        _internal=SimpleNamespace(client=SimpleNamespace(send=AsyncMock())),
    ), url="https://www.google.com/sorry/index")
    run.session._internal.client.send.side_effect = lambda *args, **kwargs: {
        "frameTree": {"frame": {"url": run.url}},
    }
    manager.browser_service.runs[thread_id] = run
    observation_cdp(run.session, run.session.dom_tree.return_value.content)
    try:
        await manager.browser_service.action(thread_id, BrowserAction(action="status"))
        assert (await client.get("/v1/browser-assistance")).json()["items"] == []
        from deepseek_tui.tools.browser import BrowserUseTool

        result = await BrowserUseTool().execute(
            {"action": "request_assistance", "reason": "Google requires human verification"},
            SimpleNamespace(metadata={
                "browser_service": manager.browser_service,
                "runtime_thread_id": thread_id,
                "request_browser_assistance": manager.request_browser_assistance,
            }),
        )
        assert result.success
        items = (await client.get("/v1/browser-assistance")).json()["items"]
        assert len(items) == 1 and handle.pause.paused
        assert "Google" in items[0]["reason"]
        base = f"/v1/threads/{thread_id}/browser/assistance"
        body = {"request_id": items[0]["id"], "choice": "takeover"}
        assert (await client.post(base, json=body)).status_code == 200
        body["choice"] = "continue"
        assert (await client.post(base, json=body)).status_code == 200
        assert not handle.pause.paused
        assert "NOT guaranteed" in handle.resume_context
        assert "Verify" in handle.resume_context
        assert (await client.get("/v1/browser-assistance")).json()["items"] == []
    finally:
        manager._active.pop(thread_id, None)
        manager.browser_service.runs.pop(thread_id, None)


async def test_ui_actions_require_current_generation(authed_client, authed_runtime_app, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.browser.service import BrowserRun

    client, _ = authed_client
    app, _ = authed_runtime_app
    browser = app.state.thread_manager.browser_service
    thread_id = (await client.post("/v1/threads", json={"title": "Generation"})).json()["id"]
    run = BrowserRun(thread_id, tmp_path / "page", session=SimpleNamespace(),
                     owner="user", generation=3)
    browser.runs[thread_id] = run
    browser._action = AsyncMock(return_value={"success": True, "receipt": {
        "action_id": "test-operation", "execution": "executed", "effect": "unchecked"}})
    base = f"/v1/threads/{thread_id}/browser/action"
    try:
        for body in [{"action": "reload"}, {"action": "reload", "generation": 2}]:
            response = await client.post(base, json=body)
            assert response.status_code == 409
        browser._action.assert_not_awaited()
        response = await client.post(base, json={"action": "reload", "generation": 3})
        assert response.status_code == 200 and response.json()["success"]
        browser._action.assert_awaited_once()
    finally:
        browser.runs.pop(thread_id, None)


async def test_permanent_thread_deletion_closes_browser(authed_client, authed_runtime_app, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.browser.service import BrowserRun

    client, _ = authed_client
    app, _ = authed_runtime_app
    manager = app.state.thread_manager
    thread_id = (await client.post("/v1/threads", json={"title": "Delete"})).json()["id"]
    directory = tmp_path / "disposable-browser"
    directory.mkdir()
    session = SimpleNamespace(close=AsyncMock())
    manager.browser_service.runs[thread_id] = BrowserRun(thread_id, directory, session=session)
    saved = manager.browser_service.artifact_root / thread_id
    (saved / "profile").mkdir(parents=True)
    (saved / "profile" / "Cookies").write_text("session")
    (saved / "evidence.jpg").write_bytes(b"jpg")
    await manager.delete_thread(thread_id)
    session.close.assert_awaited_once_with(kill=True)
    assert thread_id not in manager.browser_service.runs
    assert not directory.exists()
    # Evidence, downloads and saved logins belong to the deleted conversation.
    assert not saved.exists()


async def test_recovery_keeps_original_task_paused_and_assistance_pending(
    authed_client, authed_runtime_app, tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.browser.service import BrowserRun
    from deepseek_tui.engine.handle import EngineHandle

    client, _ = authed_client
    app, _ = authed_runtime_app
    manager = app.state.thread_manager
    thread_id = (await client.post("/v1/threads", json={"title": "Recover"})).json()["id"]
    handle = EngineHandle()
    handle._mark_turn_active()
    turn = SimpleNamespace(turn_id="original")
    manager._active[thread_id] = SimpleNamespace(handle=handle, active_turn=turn)
    old = BrowserRun(thread_id, tmp_path / "old", session=SimpleNamespace(close=AsyncMock()),
                     generation=2, healthy=False, agent_task=True)
    old.assistance = {"id": "request", "status": "pending", "turn_id": "original"}
    manager.browser_service.runs[thread_id] = old
    replacement = BrowserRun(thread_id, tmp_path / "new", session=SimpleNamespace(), generation=5)

    async def ensure(thread):
        manager.browser_service.runs[thread] = replacement
        return replacement

    monkeypatch.setattr(manager.browser_service, "ensure", ensure)
    try:
        response = await client.post(f"/v1/threads/{thread_id}/browser/recover", json={})
        assert response.status_code == 200
        state = response.json()
        assert state["owner"] == "user" and state["generation"] == 5
        assert state["assistance"]["id"] == "request" and state["assistance"]["status"] == "human"
        assert handle.pause.paused and manager._active[thread_id].active_turn is turn
        assert replacement.agent_task  # The paused turn still owns its browser task.
    finally:
        manager._active.pop(thread_id, None)
        manager.browser_service.runs.pop(thread_id, None)


async def test_large_handoff_observation_remains_valid_json(
    authed_client, authed_runtime_app, tmp_path,
):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.browser.service import BrowserRun
    from deepseek_tui.engine.handle import EngineHandle

    client, _ = authed_client
    app, _ = authed_runtime_app
    manager = app.state.thread_manager
    thread_id = (await client.post("/v1/threads", json={"title": "Handoff"})).json()["id"]
    handle = EngineHandle()
    handle._mark_turn_active()
    handle.pause.pause()
    manager._active[thread_id] = SimpleNamespace(
        handle=handle, active_turn=SimpleNamespace(turn_id="original"))
    session = SimpleNamespace(_internal=SimpleNamespace(client=SimpleNamespace(send=AsyncMock())))
    observation_cdp(session, "Region details " * 3000)
    run = BrowserRun(thread_id, tmp_path / "page", session=session, owner="user", agent_task=True)
    manager.browser_service.runs[thread_id] = run
    try:
        response = await client.post(f"/v1/threads/{thread_id}/browser/control",
                                     json={"owner": "agent", "generation": 0})
        assert response.status_code == 200
        content = handle.resume_context.split("Fresh browser observation:\n", 1)[1]
        observed = json.loads(content)
        assert len(content) <= 12000
        assert observed["observation"]["observation_id"] == run.latest_observation["observation_id"]
        assert observed["observation"]["control_generation"] == run.generation
        assert observed["observation"]["next_text_offset"] > 0
    finally:
        manager._active.pop(thread_id, None)
        manager.browser_service.runs.pop(thread_id, None)


async def test_persisted_browser_result_is_the_bounded_projection(authed_runtime_app, monkeypatch):
    import asyncio
    import json
    import uuid
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.events import ToolCallEvent, ToolResultEvent, TurnCompleteEvent
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.protocol.responses import ToolCall
    from deepseek_tui.server.threads import (
        CreateThreadRequest,
        RuntimeTurnStatus,
        TurnRecord,
        _ActiveThreadState,
    )
    from deepseek_tui.tools.registry import ToolContext

    manager = authed_runtime_app[0].state.thread_manager
    monkeypatch.setattr(manager, "_recover_missing_final_answer", AsyncMock(return_value=None))
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(TurnRecord(id=turn_id, thread_id=thread.id,
        status=RuntimeTurnStatus.IN_PROGRESS, input_summary="test", created_at=now, started_at=now))
    engine = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    idle = asyncio.create_task(asyncio.sleep(3600))
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, engine, idle)
    result = {"success": True, "content": "Observation collected",
              "receipt": {"action_id": "a", "execution": "executed", "effect": "unchecked"},
              "observation": {"observation_id": "obs", "text": "page text " * 2000,
                              "elements": [{"ref": f"e{i}", "role": "button", "name": "Edit",
                                            "target_id": f"obs:n{i}", "box": {"x": 1, "y": 2}}
                                           for i in range(250)]}}
    tool = ToolCall(id="tc_browser", name="browser_use", arguments={"action": "observe"})

    async def pump():
        await handle.emit(ToolCallEvent(tool_call=tool))
        await handle.emit(ToolResultEvent(tool_call_id="tc_browser", tool_name="browser_use",
            content=json.dumps(result), success=True, metadata={"browser": result}))
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await asyncio.wait_for(manager._monitor_turn(thread.id, turn_id, handle, "agent"), 10)
    finally:
        await pump_task
        idle.cancel()
        async with manager._active_lock:
            manager._active.pop(thread.id, None)
    items = [manager.store.load_item(i) for i in manager.store.load_turn(turn_id).item_ids]
    detail = next(i.detail for i in items if (i.metadata or {}).get("tool_name") == "browser_use")
    assert len(json.dumps(result)) > 40_000 and len(detail) <= 12_000
    persisted = json.loads(detail)
    assert persisted["receipt"]["execution"] == "executed"
    assert persisted["observation"]["observation_id"] == "obs"


async def test_workflow_list_is_newest_first(authed_client, authed_runtime_app):
    from octop_browser.record.models import RecordingManifest

    from deepseek_tui.browser.workflows import recording_store

    client, _ = authed_client
    manager = authed_runtime_app[0].state.thread_manager
    thread_id = (await client.post("/v1/threads", json={"title": "Flows"})).json()["id"]
    store = recording_store(manager.browser_service, thread_id)
    # IDs are random, so their path order must not decide recency.
    for index, recording_id in enumerate(["rec_c", "rec_a", "rec_b"]):
        store.create(RecordingManifest(recordingId=recording_id,
                                       createdAt=f"2026-10-15T00:00:0{index}+00:00"))
    response = await client.get(f"/v1/threads/{thread_id}/browser/workflows")
    assert [item["id"] for item in response.json()["items"]] == ["rec_b", "rec_a", "rec_c"]


async def test_repeated_workflow_suggestions_are_removed(authed_client):
    client, _ = authed_client
    thread_id = (await client.post("/v1/threads", json={"title": "Browser"})).json()["id"]
    state = (await client.get(f"/v1/threads/{thread_id}/browser")).json()
    assert "skill_suggestion" not in state
    assert "skill_suggestions_enabled" not in state
    response = await client.post(
        f"/v1/threads/{thread_id}/browser/skill-suggestions", json={"action": "enable"}
    )
    assert response.status_code == 404


async def test_browser_settings_work_without_a_chat_and_require_auth(authed_client):
    client, token = authed_client
    headers = {"Authorization": f"Bearer {token}"}
    path = '/v1/threads/workbench-preview/browser/settings'
    assert (await client.get(path, headers={'Authorization': ''})).status_code == 401
    response = await client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.json() == {'agent_enabled': True, 'grants': []}
    response = await client.post(path, json={'agent_enabled': False}, headers=headers)
    assert response.status_code == 200
    assert not (await client.get(path, headers=headers)).json()['agent_enabled']
    assert (await client.post(path, json={'agent_enabled': {}}, headers=headers)).status_code == 422
    assert (await client.get('/v1/threads/missing/browser/settings', headers=headers)).status_code == 404
