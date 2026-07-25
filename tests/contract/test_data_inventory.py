"""Contract tests for /v1/data inventory + maintenance ops."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient

from deepseek_tui.config.paths import user_sessions_dir
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
)
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpoint


def _seed_turn(
    manager,
    *,
    thread_id: str,
    turn_id: str,
    user_id: str,
    asst_id: str,
    when: datetime,
) -> None:
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="hello",
            created_at=when,
            started_at=when,
            ended_at=when,
            item_ids=[user_id, asst_id],
        )
    )
    for item_id, kind, text in (
        (user_id, TurnItemKind.USER_MESSAGE, "hello"),
        (asst_id, TurnItemKind.AGENT_MESSAGE, "world"),
    ):
        manager.store.save_item(
            TurnItemRecord(
                id=item_id,
                turn_id=turn_id,
                kind=kind,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=text,
                detail=text,
                started_at=when,
                ended_at=when,
            )
        )


@pytest.mark.asyncio
async def test_data_inventory_reports_counts(
    runtime_app, client: AsyncClient, runtime_data_dir: Path
) -> None:
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(
        CreateThreadRequest(title="inv", workspace=str(runtime_data_dir / "ws"))
    )
    now = datetime.now(timezone.utc)
    _seed_turn(
        mgr,
        thread_id=thread.id,
        turn_id="turn_inv1",
        user_id="item_u1",
        asst_id="item_a1",
        when=now,
    )
    thread.updated_at = now
    mgr.store.save_thread(thread)

    r = await client.get("/v1/data/inventory")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["thread_count"] == 1
    assert body["message_count"] == 2
    assert body["threads_bytes"] >= 0
    assert Path(body["threads_dir"]).exists()
    assert body["home_dir"]


@pytest.mark.asyncio
async def test_optimize_strips_deltas_keeps_messages(
    runtime_app, client: AsyncClient, runtime_data_dir: Path
) -> None:
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(
        CreateThreadRequest(title="opt", workspace=str(runtime_data_dir / "ws"))
    )
    now = datetime.now(timezone.utc)
    _seed_turn(
        mgr,
        thread_id=thread.id,
        turn_id="turn_opt1",
        user_id="item_ou1",
        asst_id="item_oa1",
        when=now,
    )

    await mgr.store.append_event(
        thread.id, "turn_opt1", None, "response.delta", {"text": "x" * 5000}
    )
    await mgr.store.append_event(
        thread.id, "turn_opt1", "item_oa1", "item.completed", {"ok": True}
    )

    before_events = mgr.store.events_since(thread.id)
    assert any(e.event == "response.delta" for e in before_events)

    r = await client.post("/v1/data/optimize")
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["events_stripped"] >= 1

    after_events = mgr.store.events_since(thread.id)
    assert not any(e.event == "response.delta" for e in after_events)
    assert any(e.event == "item.completed" for e in after_events)

    # Conversation items untouched.
    item = mgr.store.load_item("item_oa1")
    assert item.detail == "world"
    detail = await client.get(f"/v1/threads/{thread.id}")
    assert detail.status_code == 200


@pytest.mark.asyncio
async def test_clean_by_age_deletes_only_old_threads(
    runtime_app, client: AsyncClient, runtime_data_dir: Path
) -> None:
    mgr = runtime_app.state.thread_manager
    ws = str(runtime_data_dir / "ws")
    old = await mgr.create_thread(CreateThreadRequest(title="old", workspace=ws))
    new = await mgr.create_thread(CreateThreadRequest(title="new", workspace=ws))
    old_ts = datetime.now(timezone.utc) - timedelta(days=120)
    new_ts = datetime.now(timezone.utc)
    _seed_turn(
        mgr,
        thread_id=old.id,
        turn_id="turn_old",
        user_id="item_old_u",
        asst_id="item_old_a",
        when=old_ts,
    )
    _seed_turn(
        mgr,
        thread_id=new.id,
        turn_id="turn_new",
        user_id="item_new_u",
        asst_id="item_new_a",
        when=new_ts,
    )
    old.updated_at = old_ts
    new.updated_at = new_ts
    mgr.store.save_thread(old)
    mgr.store.save_thread(new)

    r = await client.post("/v1/data/clean", json={"older_than_days": 90})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["threads_deleted"] == 1
    assert old.id in body["thread_ids"]

    with pytest.raises(FileNotFoundError):
        mgr.store.load_thread(old.id)
    assert mgr.store.load_thread(new.id).id == new.id
    assert mgr.store.load_item("item_new_a").detail == "world"


@pytest.mark.asyncio
async def test_clear_history_keeps_skills_and_config(
    runtime_app, client: AsyncClient, runtime_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = Path(runtime_data_dir / "home")
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    skills = home / "skills" / "keep-me"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# keep\n", encoding="utf-8")
    (home / "config.toml").write_text("[provider]\n", encoding="utf-8")
    (home / "mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")

    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(
        CreateThreadRequest(title="wipe", workspace=str(runtime_data_dir / "ws"))
    )
    now = datetime.now(timezone.utc)
    _seed_turn(
        mgr,
        thread_id=thread.id,
        turn_id="turn_wipe",
        user_id="item_wu",
        asst_id="item_wa",
        when=now,
    )
    # Stale checkpoint + session file should be cleared with history.
    mgr.checkpoints._save(
        TurnCheckpoint(
            turn_id="turn_wipe",
            is_git=False,
            thread_id=thread.id,
            created_at=now.timestamp(),
        )
    )
    sessions = user_sessions_dir()
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "current.json").write_text("{}", encoding="utf-8")

    r = await client.post("/v1/data/clear-history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["threads_deleted"] == 1
    assert "skills" in body["preserved"]

    assert mgr.store.list_threads() == []
    assert not (mgr.manager_cfg.data_dir / "items" / "item_wa.json").exists()
    assert (skills / "SKILL.md").is_file()
    assert (home / "config.toml").is_file()
    assert (home / "mcp.json").is_file()
    assert not (sessions / "current.json").exists()


@pytest.mark.asyncio
async def test_append_event_truncates_noisy_delta_payload(
    runtime_app, runtime_data_dir: Path
) -> None:
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(
        CreateThreadRequest(title="delta", workspace=str(runtime_data_dir / "ws"))
    )
    record = await mgr.store.append_event(
        thread.id,
        None,
        None,
        "response.delta",
        {"text": "z" * 10_000},
    )
    assert record.payload.get("_truncated") is True
    raw = json.dumps(record.payload)
    assert len(raw) < 10_000
