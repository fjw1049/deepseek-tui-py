"""Persistent Workbench usage ledger tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from deepseek_tui.server import workbench_usage_ledger as ledger


def test_record_turn_usage_deduplicates_turn_id(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "ledger-v1.json"
    monkeypatch.setattr(ledger, "workbench_usage_ledger_path", lambda: path)
    ended_at = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)
    usage = {
        "models": {
            "deepseek-chat": {
                "input_tokens": 10,
                "output_tokens": 4,
                "total_tokens": 14,
                "turns": 1,
            }
        }
    }
    ledger.record_turn_usage(
        turn_id="turn-1",
        ended_at=ended_at,
        thread_id="thread-1",
        turn_usage=usage,
        fallback_model="deepseek-chat",
    )
    ledger.record_turn_usage(
        turn_id="turn-1",
        ended_at=ended_at,
        thread_id="thread-1",
        turn_usage=usage,
        fallback_model="deepseek-chat",
    )
    saved = ledger._read_ledger(path)
    assert saved["days"]
    day_key = next(iter(saved["days"]))
    assert saved["days"][day_key]["models"]["deepseek-chat"]["total_tokens"] == 14
    assert saved["processedTurnIds"]["turn-1"] == day_key
