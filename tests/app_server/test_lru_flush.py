"""LRU eviction must flush via engine reference, not _active lookup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.app_server.thread_manager import RuntimeThreadManager


@pytest.mark.asyncio
async def test_flush_engine_memory_calls_post_turn_without_active_entry() -> None:
    mgr = RuntimeThreadManager.__new__(RuntimeThreadManager)
    post_turn = MagicMock()
    post_turn.flush_before_loss = AsyncMock()
    engine = MagicMock()
    engine.session_messages = [MagicMock()]
    engine.post_turn = post_turn
    engine._build_flush_evidence = MagicMock(return_value="evidence")

    await mgr._flush_engine_memory(engine, "evicted-thread")

    engine._build_flush_evidence.assert_called_once()
    post_turn.flush_before_loss.assert_awaited_once_with("evidence")
