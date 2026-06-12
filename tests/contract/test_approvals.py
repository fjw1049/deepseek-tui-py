from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_approval_remember_returns_session_decision(
    client: AsyncClient, runtime_app: object
) -> None:
    from deepseek_tui.server.approval import HttpApprovalHandler
    from deepseek_tui.policy.approval import ApprovalDecision, ApprovalRequest, RiskLevel, ToolCategory

    bridge = runtime_app.state.approval_bridge  # type: ignore[attr-defined]
    approval_id = "appr_contract_remember"
    handler = HttpApprovalHandler(bridge, thread_id="thr_test")

    async def resolve_later() -> ApprovalDecision:
        return await handler.request_approval(
            approval_id,
            ApprovalRequest(
                tool_name="write_file",
                risk_level=RiskLevel.MEDIUM,
                category=ToolCategory.FILE_WRITE,
                reason="write test.txt",
            ),
        )

    decision_task = asyncio.create_task(resolve_later())
    await asyncio.sleep(0.01)

    r = await client.post(
        f"/v1/approvals/{approval_id}",
        json={"decision": "allow", "remember": True},
    )
    assert r.status_code == 200
    decision = await asyncio.wait_for(decision_task, timeout=1.0)
    assert decision is ApprovalDecision.APPROVED_SESSION


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


@pytest.mark.asyncio
async def test_approval_list_pending(client: AsyncClient, runtime_app: object) -> None:
    from deepseek_tui.server.approval import PendingApprovalRecord

    bridge = runtime_app.state.approval_bridge  # type: ignore[attr-defined]
    bridge.register(
        "appr_pending_list",
        meta=PendingApprovalRecord(
            thread_id="thr_test01",
            tool_name="write_file",
            description="write smoke.txt",
        ),
    )
    bridge.register(
        "appr_other_thread",
        meta=PendingApprovalRecord(
            thread_id="thr_other",
            tool_name="bash",
            description="run ls",
        ),
    )

    r = await client.get("/v1/approvals/pending", params={"thread_id": "thr_test01"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["approval_id"] == "appr_pending_list"
    assert rows[0]["tool_name"] == "write_file"
