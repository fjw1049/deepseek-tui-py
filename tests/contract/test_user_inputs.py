from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from deepseek_tui.app_server.thread_manager import _ActiveThreadState
from deepseek_tui.engine.handle import EngineHandle


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
async def test_user_input_resolve_pending(client: AsyncClient, runtime_app: object) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    handle = EngineHandle()
    request_id = "uinp_contract_pending"
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    handle.pending_user_inputs[request_id] = future

    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active["thr_user_input_test"] = _ActiveThreadState(handle, engine_task)

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
