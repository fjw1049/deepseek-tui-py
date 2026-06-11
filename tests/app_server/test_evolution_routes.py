"""Characterization tests for evolution approval route response shapes."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from deepseek_tui.app_server.runtime_api.routes.evolution import (
    approve_evolution,
    list_pending_evolution,
    reject_evolution,
)
from deepseek_tui.capabilities.evolution import (
    evolution_action_response,
    evolution_record_to_dict,
)


@dataclass
class _Record:
    id: str
    thread_id: str
    workspace: str
    kind: str
    status: str
    asset_path: str | None
    reason: str
    source: str
    source_turn_id: str
    created_at: float


def _record(*, status: str = "proposed") -> _Record:
    return _Record(
        id="rec-1",
        thread_id="thread-1",
        workspace="/tmp/ws",
        kind="skill_create",
        status=status,
        asset_path=None,
        reason="",
        source="review",
        source_turn_id="turn-1",
        created_at=1.0,
    )


@pytest.mark.asyncio
async def test_list_pending_evolution_serializes_thread_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    ledger = AsyncMock()
    ledger.list_pending = AsyncMock(return_value=[record])
    monkeypatch.setattr(
        "deepseek_tui.app_server.runtime_api.routes.evolution.evolution_ledger_for_thread",
        AsyncMock(return_value=ledger),
    )
    request = MagicMock()
    request.query_params = {"thread_id": "thread-1"}

    result = await list_pending_evolution(request)

    assert result == [evolution_record_to_dict(record)]
    ledger.list_pending.assert_awaited_once_with(thread_id="thread-1")


@pytest.mark.asyncio
async def test_approve_evolution_returns_action_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(status="applied")
    ledger = AsyncMock()
    ledger.approve = AsyncMock(return_value=record)
    monkeypatch.setattr(
        "deepseek_tui.app_server.runtime_api.routes.evolution.evolution_ledger_for_thread",
        AsyncMock(return_value=ledger),
    )
    request = MagicMock()
    request.query_params = {"thread_id": "thread-1"}

    result = await approve_evolution(request, "rec-1")

    assert result == evolution_action_response(record)
    ledger.approve.assert_awaited_once_with("rec-1")


@pytest.mark.asyncio
async def test_approve_evolution_requires_thread_id() -> None:
    request = MagicMock()
    request.query_params = {}

    with pytest.raises(HTTPException) as exc_info:
        await approve_evolution(request, "rec-1")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "missing_thread_id"


@pytest.mark.asyncio
async def test_approve_evolution_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AsyncMock()
    ledger.approve = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "deepseek_tui.app_server.runtime_api.routes.evolution.evolution_ledger_for_thread",
        AsyncMock(return_value=ledger),
    )
    request = MagicMock()
    request.query_params = {"thread_id": "thread-1"}

    with pytest.raises(HTTPException) as exc_info:
        await approve_evolution(request, "missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"] == "not_found"


@pytest.mark.asyncio
async def test_reject_evolution_returns_action_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(status="rejected")
    ledger = AsyncMock()
    ledger.reject = AsyncMock(return_value=record)
    monkeypatch.setattr(
        "deepseek_tui.app_server.runtime_api.routes.evolution.evolution_ledger_for_thread",
        AsyncMock(return_value=ledger),
    )
    monkeypatch.setattr(
        "deepseek_tui.app_server.runtime_api.routes.evolution.body",
        AsyncMock(return_value={"reason": "not useful"}),
    )
    request = MagicMock()
    request.query_params = {"thread_id": "thread-1"}

    result = await reject_evolution(request, "rec-1")

    assert result == evolution_action_response(record)
    ledger.reject.assert_awaited_once_with("rec-1", reason="not useful")
