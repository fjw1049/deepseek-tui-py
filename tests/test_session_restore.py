"""Regression tests for shared TUI session restore helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.protocol.messages import Message, TextBlock
from deepseek_tui.tui.session_restore import (
    parse_session_messages,
    session_metadata,
    session_started_at_iso,
)


def test_parse_session_messages_accepts_metadata_less_current_json(tmp_path: Path) -> None:
    path = tmp_path / "current.json"
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hello"}],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = parse_session_messages(data, path=path)
    assert len(messages) == 1
    assert messages[0].role == "user"


def test_session_metadata_synthesizes_id_from_path(tmp_path: Path) -> None:
    path = tmp_path / "current.json"
    data = {"messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}]}
    metadata = session_metadata(data, path=path)
    assert metadata["id"] == "current"


def test_session_started_at_iso_from_path_mtime(tmp_path: Path) -> None:
    path = tmp_path / "saved.json"
    path.write_text("{}", encoding="utf-8")
    iso = session_started_at_iso({}, path=path)
    assert iso is not None


def test_message_round_trip_via_model_dump() -> None:
    msg = Message(role="assistant", content=[TextBlock(type="text", text="hi")])
    raw = msg.model_dump()
    restored = parse_session_messages({"messages": [raw]})
    assert restored[0].content[0].text == "hi"  # type: ignore[attr-defined]
