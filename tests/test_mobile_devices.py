from __future__ import annotations

import asyncio
import concurrent.futures
import json
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from deepseek_tui.mobile import devices as devices
from deepseek_tui.server.auth import RuntimeAuthMiddleware

ADMIN = {"Authorization": "Bearer admin-test"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    app = FastAPI()
    app.state.runtime_auth_token = "admin-test"
    app.include_router(devices.router)
    app.add_middleware(RuntimeAuthMiddleware, auth_token="admin-test")

    @app.get("/v1/test")
    async def test():
        return {"okay": True}

    @app.get("/legacy/test")
    async def legacy():
        return {"okay": True}

    @app.get("/v1/events/{device_id}")
    async def events(device_id: str):
        async def stream():
            yield "data: first\n\n"
            await asyncio.sleep(0.03)
            await asyncio.to_thread(devices.revoke_device, device_id)
            yield "data: should-not-arrive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/v1/idle-events/{device_id}")
    async def idle_events(device_id: str):
        async def stream():
            yield "data: connected\n\n"
            await asyncio.sleep(0.03)
            await asyncio.to_thread(devices.revoke_device, device_id)
            await asyncio.sleep(30)
            yield "data: should-not-arrive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    with TestClient(app) as test_client:
        yield test_client


def pair(client):
    code = client.post("/v1/mobile/devices/pair-codes", headers=ADMIN).json()["code"]
    result = client.post(devices.PAIR_PATH, json={"code": code, "name": "Test phone"})
    assert result.status_code == 200
    return result.json(), code


def test_admin_compatibility_pair_and_revoke(client):
    assert client.get("/v1/test").status_code == 401
    assert client.get("/legacy/test").status_code == 401
    assert client.get("/v1/test", headers=ADMIN).status_code == 200
    assert (
        client.get("/legacy/test", headers={"x-deepseek-runtime-token": "admin-test"}).status_code
        == 200
    )
    paired, code = pair(client)
    token = {"Authorization": "Bearer " + paired["token"]}
    assert client.get("/v1/test", headers=token).status_code == 200
    assert client.get("/v1/mobile/devices/session", headers=token).json()["role"] == "device"
    assert client.get("/v1/mobile/devices", headers=token).status_code == 403
    assert client.post("/v1/mobile/devices/pair-codes", headers=token).status_code == 403
    assert (
        client.delete("/v1/mobile/devices/" + paired["device"]["id"], headers=token).status_code
        == 403
    )
    listing = client.get("/v1/mobile/devices", headers=ADMIN)
    assert "token" not in listing.text and "hash" not in listing.text
    stored = devices._path().read_text()
    assert (
        paired["token"] not in stored
        and code.replace("-", "") not in stored
        and "admin-test" not in stored
    )
    assert devices._path().stat().st_mode & 0o777 == 0o600
    assert client.post(devices.PAIR_PATH, json={"code": code, "name": "again"}).status_code == 400
    assert (
        client.delete("/v1/mobile/devices/" + paired["device"]["id"], headers=ADMIN).status_code
        == 200
    )
    assert client.get("/v1/test", headers=token).status_code == 401
    assert client.get("/v1/test", headers=ADMIN).status_code == 200


def test_exact_pair_route_and_expiry_rate_limit(client, monkeypatch):
    assert client.get(devices.PAIR_PATH).status_code == 401
    assert client.post(devices.PAIR_PATH + "/anything").status_code == 401
    code = devices.create_code()["code"]
    data = json.loads(devices._path().read_text())
    data["codes"][0]["expires_at"] = 0
    devices._save(data)
    assert client.post(devices.PAIR_PATH, json={"code": code, "name": "expired"}).status_code == 400
    for _ in range(9):
        assert (
            client.post(devices.PAIR_PATH, json={"code": "wrong", "name": "phone"}).status_code
            == 400
        )
    assert (
        client.post(devices.PAIR_PATH, json={"code": "wrong", "name": "phone"}).status_code == 429
    )


def test_concurrent_code_consumption_has_exactly_one_winner(client):
    code = devices.create_code()["code"]

    def attempt(index):
        try:
            return devices.consume_code(code, f"phone{index}", f"address{index}")
        except HTTPException as error:
            return error.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(isinstance(item, dict) for item in results) == 1
    assert sum(item == 400 for item in results if isinstance(item, int)) == 7


def test_revoked_device_stream_stops(client):
    paired, _ = pair(client)
    response = client.get(
        "/v1/events/" + paired["device"]["id"],
        headers={"Authorization": "Bearer " + paired["token"]},
    )
    assert "first" in response.text
    assert "should-not-arrive" not in response.text


def test_revocation_disconnects_idle_sse_within_poll_interval(client):
    paired, _ = pair(client)
    started = time.monotonic()
    response = client.get(
        "/v1/idle-events/" + paired["device"]["id"],
        headers={"Authorization": "Bearer " + paired["token"]},
    )
    assert "connected" in response.text
    assert "should-not-arrive" not in response.text
    assert time.monotonic() - started < 8
