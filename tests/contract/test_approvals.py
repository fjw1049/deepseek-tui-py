from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_approval_resolve_pending(client: AsyncClient, runtime_app: object) -> None:
    bridge = runtime_app.state.approval_bridge  # type: ignore[attr-defined]
    approval_id = "appr_contract_pending"
    fut = bridge.register(approval_id)

    r = await client.post(
        f"/v1/approvals/{approval_id}",
        json={"decision": "allow", "remember": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["decision"] == "allow"
    assert await fut is True


@pytest.mark.asyncio
async def test_approval_not_found(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/approvals/nonexistent",
        json={"decision": "allow"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "approval_not_found"


@pytest.mark.asyncio
async def test_approval_invalid_decision(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/approvals/some-id",
        json={"decision": "maybe"},
    )
    assert r.status_code == 400
