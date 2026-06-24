"""Persistent Workbench usage ledger tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
    saved, readable = ledger._read_ledger(path)
    assert readable is True
    assert saved["days"]
    day_key = next(iter(saved["days"]))
    assert saved["days"][day_key]["models"]["deepseek-chat"]["total_tokens"] == 14
    assert saved["processedTurnIds"]["turn-1"] == day_key
    assert "lifetime" not in saved


def test_record_turn_usage_skips_write_on_schema_mismatch(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "ledger-v1.json"
    monkeypatch.setattr(ledger, "workbench_usage_ledger_path", lambda: path)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 99,
                "days": {
                    "2026-06-24": {
                        "models": {
                            "deepseek-chat": {
                                "model": "deepseek-chat",
                                "input_tokens": 99,
                                "output_tokens": 1,
                                "total_tokens": 100,
                                "cost_usd": 0.0,
                                "cost_cny": 0.0,
                                "turns": 1,
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    ended_at = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)
    ledger.record_turn_usage(
        turn_id="turn-new",
        ended_at=ended_at,
        thread_id="thread-1",
        turn_usage={"input_tokens": 1, "output_tokens": 1, "turns": 1},
        fallback_model="deepseek-chat",
    )
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schemaVersion"] == 99
    assert on_disk["days"]["2026-06-24"]["models"]["deepseek-chat"]["total_tokens"] == 100


def test_prune_old_days_removes_stale_entries(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "ledger-v1.json"
    monkeypatch.setattr(ledger, "workbench_usage_ledger_path", lambda: path)
    stale_day = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")
    fresh_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ledger._write_ledger(
        path,
        {
            "schemaVersion": ledger.LEDGER_SCHEMA_VERSION,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "retentionDays": ledger.RETENTION_DAYS,
            "processedTurnIds": {
                "old-turn": stale_day,
                "fresh-turn": fresh_day,
            },
            "days": {
                stale_day: {
                    "models": {
                        "deepseek-chat": {
                            "model": "deepseek-chat",
                            "input_tokens": 1,
                            "output_tokens": 0,
                            "total_tokens": 1,
                            "cost_usd": 0.0,
                            "cost_cny": 0.0,
                            "turns": 1,
                        }
                    },
                    "totals": {
                        "input_tokens": 1,
                        "output_tokens": 0,
                        "total_tokens": 1,
                        "cost_usd": 0.0,
                        "cost_cny": 0.0,
                        "turns": 1,
                    },
                }
            },
        },
    )
    ended_at = datetime.now(timezone.utc)
    ledger.record_turn_usage(
        turn_id="turn-fresh",
        ended_at=ended_at,
        thread_id="thread-1",
        turn_usage={"input_tokens": 2, "output_tokens": 1, "turns": 1},
        fallback_model="deepseek-chat",
    )
    saved, readable = ledger._read_ledger(path)
    assert readable is True
    assert stale_day not in saved["days"]
    assert "old-turn" not in saved["processedTurnIds"]
    assert "turn-fresh" in saved["processedTurnIds"]
