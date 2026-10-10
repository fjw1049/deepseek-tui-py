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
    assert (await client.get(base + "/preferences")).json() == {"persistent": False}
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
    run = BrowserRun(thread_id, tmp_path / "page", session=session)
    manager.browser_service.runs[thread_id] = run
    try:
        response = await client.post(base + "/control", json={"owner": "user", "generation": 0})
        assert response.status_code == 200
        assert response.json()["task_paused"]
        assert handle.pause.paused
        await handle.steer("Keep the original task")
        assert handle.pause.paused
        generation = run.generation
        # Failed observation leaves the same task paused and the user in control.
        session.dom_tree.side_effect = ConnectionError("Page disconnected")
        response = await client.post(
            base + "/control", json={"owner": "agent", "generation": generation},
        )
        assert response.status_code == 409
        assert handle.pause.paused and run.owner == "user"
        session.dom_tree.side_effect = None
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
        before = session.dom_tree.await_count
        # A retry of the same response-lost request is idempotent.
        response = await client.post(
            base + "/control", json={"owner": "agent", "generation": generation},
        )
        assert response.status_code == 200
        assert session.dom_tree.await_count == before
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
        clicked = await client.post(base + "/action", json={"action": "click", "selector": "#us"})
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
        assert "Use the public manual" in handle.resume_context
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
