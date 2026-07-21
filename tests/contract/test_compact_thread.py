"""POST /v1/threads/{id}/compact — manual context compaction."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from deepseek_tui.server.threads import (
    CreateThreadRequest,
    TurnItemKind,
)
from deepseek_tui.protocol.messages import Message


@pytest.mark.asyncio
async def test_compact_thread_emits_context_compaction_item(
    client: AsyncClient,
    runtime_app: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]

    async def fake_create(**kwargs: object) -> SimpleNamespace:
        from deepseek_tui.tools.registry import ToolContext

        engine = SimpleNamespace(
            tool_context=ToolContext(working_directory=kwargs["working_directory"]),
            session_messages=[
                Message.user("a"),
                Message.assistant("b"),
                Message.user("c"),
            ],
            mode=kwargs.get("mode", "agent"),
            turn_usage_ledger=SimpleNamespace(
                reset=lambda: None,
                totals=lambda: {},
                items=[],
            ),
            session_cache_hit_total=0,
            session_cache_miss_total=0,
            session_cost_usd=0.0,
            session_cost_cny=0.0,
            _run_compaction=AsyncMock(
                return_value=SimpleNamespace(
                    messages=[Message.user("summary"), Message.assistant("ok")],
                    success=True,
                    retries_used=0,
                    summary_prompt=None,
                )
            ),
            run=lambda: asyncio.sleep(3600),
        )
        return engine

    monkeypatch.setattr("deepseek_tui.engine.orchestrator.Engine.create", fake_create)

    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(manager.workspace))
    )
    await manager._ensure_engine_loaded(thread)

    r = await client.post(f"/v1/threads/{thread.id}/compact", json={})
    assert r.status_code == 200, r.text

    detail = await manager.get_thread_detail(thread.id)
    compaction_items = [i for i in detail.items if i.kind == TurnItemKind.CONTEXT_COMPACTION]
    assert len(compaction_items) == 1
    assert "compacted" in (compaction_items[0].detail or "").lower()
    meta = compaction_items[0].metadata if isinstance(compaction_items[0].metadata, dict) else {}
    snap = meta.get("session_messages")
    assert isinstance(snap, list) and len(snap) == 2

    async with manager._active_lock:
        state = manager._active.get(thread.id)
        assert state is not None
        assert len(state.engine.session_messages) == 2
        state.engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await state.engine_task
        manager._active.pop(thread.id, None)
