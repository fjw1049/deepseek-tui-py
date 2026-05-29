"""TUI session JSON persistence includes smart-memory metadata."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.engine.engine import Engine
from deepseek_tui.protocol.messages import Message, TextBlock


@pytest.mark.asyncio
async def test_auto_persist_writes_memory_metadata(tmp_path: Path, monkeypatch) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr(
        "deepseek_tui.config.paths.user_sessions_dir",
        lambda: sessions_dir,
    )

    handle = MagicMock()
    handle.cancel_event = MagicMock()
    client = AsyncMock()
    engine = Engine(
        handle=handle,
        client=client,
        default_model="deepseek-chat",
    )
    engine.memory_thread_id = "sess_persist_01"
    engine.memory_mode = "hybrid"
    engine.session_messages = [
        Message(role="user", content=[TextBlock(type="text", text="hi")]),
    ]

    await engine._auto_persist_session()

    session_file = sessions_dir / "current.json"
    assert session_file.is_file()
    data = json.loads(session_file.read_text(encoding="utf-8"))
    assert data["metadata"]["memory_thread_id"] == "sess_persist_01"
    assert data["metadata"]["memory_mode"] == "hybrid"
