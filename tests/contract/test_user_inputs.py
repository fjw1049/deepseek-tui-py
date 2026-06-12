from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from deepseek_tui.server.threads import (
    _ActiveThreadState,
    _PendingUserInputRecord,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.tools.registry import ToolContext


@pytest.mark.asyncio
async def test_user_inputs_not_found(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/user-inputs/nonexistent",
        json={"answers": [{"question_id": "q1", "value": "yes"}]},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "user_input_not_found"


@pytest.mark.asyncio
async def test_user_input_alias_route_not_found(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/user-input/nonexistent",
        json={"cancelled": True},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "user_input_not_found"


@pytest.mark.asyncio
async def test_user_inputs_pending_list(client: AsyncClient, runtime_app: object) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    handle = EngineHandle()
    request_id = "uinp_pending_list"
    loop = asyncio.get_running_loop()
    handle.pending_user_inputs[request_id] = loop.create_future()
    manager._pending_user_inputs[request_id] = _PendingUserInputRecord(
        thread_id="thr_user_input_test",
        turn_id="turn_test",
        questions=[
            {
                "header": "Pick",
                "id": "q1",
                "question": "Choose one",
                "options": [{"label": "A", "description": "Option A"}],
            }
        ],
    )

    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    stub_engine = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    async with manager._active_lock:
        manager._active["thr_user_input_test"] = _ActiveThreadState(
            handle, stub_engine, engine_task
        )

    try:
        r = await client.get(
            "/v1/user-inputs/pending",
            params={"thread_id": "thr_user_input_test"},
        )
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["request_id"] == request_id
        assert rows[0]["questions"][0]["id"] == "q1"
    finally:
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
        async with manager._active_lock:
            manager._active.pop("thr_user_input_test", None)
        manager._pending_user_inputs.pop(request_id, None)


@pytest.mark.asyncio
async def test_user_input_resolve_pending(client: AsyncClient, runtime_app: object) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    handle = EngineHandle()
    request_id = "uinp_contract_pending"
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    handle.pending_user_inputs[request_id] = future

    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    stub_engine = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    async with manager._active_lock:
        manager._active["thr_user_input_test"] = _ActiveThreadState(
            handle, stub_engine, engine_task
        )

    try:
        r = await client.post(
            f"/v1/user-inputs/{request_id}",
            json={"answers": [{"question_id": "q1", "value": "yes"}]},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        result = await asyncio.wait_for(future, timeout=1.0)
        assert result == {"answers": [{"question_id": "q1", "value": "yes"}]}
    finally:
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
        async with manager._active_lock:
            manager._active.pop("thr_user_input_test", None)
