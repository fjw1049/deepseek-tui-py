"""Contract tests for /v1/data inventory + maintenance ops."""

from __future__ import annotations

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
    browser_data = mgr.browser_service.artifact_root / thread.id / "profile"
    browser_data.mkdir(parents=True)

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
    assert not (mgr.browser_service.artifact_root / thread.id).exists()


@pytest.mark.asyncio
async def test_append_event_preserves_noisy_delta_payload(
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
    assert record.payload == {"text": "z" * 10_000}
    assert mgr.store.events_since(thread.id)[-1].payload == record.payload


@pytest.mark.asyncio
async def test_optimize_spares_freshly_written_unreferenced_item(
    runtime_app, client: AsyncClient, runtime_data_dir: Path
) -> None:
    import os
    import time

    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(
        CreateThreadRequest(title="race", workspace=str(runtime_data_dir / "ws"))
    )
    now = datetime.now(timezone.utc)
    _seed_turn(
        mgr, thread_id=thread.id, turn_id="turn_race", user_id="item_ru", asst_id="item_ra",
        when=now,
    )
    # A writer saved this item but has not yet appended it to the turn.
    mgr.store.save_item(
        TurnItemRecord(
            id="item_pending",
            turn_id="turn_race",
            kind=TurnItemKind.AGENT_MESSAGE,
            status=TurnItemLifecycleStatus.IN_PROGRESS,
            summary="",
            detail="",
            started_at=now,
        )
    )
    r = await client.post("/v1/data/optimize")
    assert r.status_code == 200, r.text
    assert mgr.store.load_item("item_pending").id == "item_pending"

    stale = time.time() - 3600
    os.utime(mgr.manager_cfg.data_dir / "items" / "item_pending.json", (stale, stale))
    r = await client.post("/v1/data/optimize")
    assert r.status_code == 200, r.text
    assert r.json()["orphan_items_removed"] == 1
    with pytest.raises(FileNotFoundError):
        mgr.store.load_item("item_pending")


@pytest.mark.asyncio
async def test_clean_by_age_previews_and_skips_blocked_threads(
    runtime_app, client: AsyncClient, runtime_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mgr = runtime_app.state.thread_manager
    ws = str(runtime_data_dir / "ws")
    old_ts = datetime.now(timezone.utc) - timedelta(days=120)
    blocked = await mgr.create_thread(CreateThreadRequest(title="blocked", workspace=ws))
    free = await mgr.create_thread(CreateThreadRequest(title="free", workspace=ws))
    for thread in (blocked, free):
        thread.updated_at = old_ts
        mgr.store.save_thread(thread)

    r = await client.get("/v1/data/clean/preview", params={"older_than_days": 90})
    assert r.status_code == 200, r.text
    assert r.json() == {"threads_matched": 2}
    assert len(mgr.store.list_threads()) == 2

    original = mgr.delete_thread

    async def delete_thread(thread_id: str, **kwargs):
        if thread_id == blocked.id:
            raise ValueError("cannot delete thread while its worktree contains unpublished code")
        return await original(thread_id, **kwargs)

    monkeypatch.setattr(mgr, "delete_thread", delete_thread)
    r = await client.post("/v1/data/clean", json={"older_than_days": 90})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["threads_deleted"], body["threads_skipped"]) == (1, 1)
    assert [t.id for t in mgr.store.list_threads()] == [blocked.id]


@pytest.mark.asyncio
async def test_clear_history_refuses_before_stopping_running_work(
    runtime_app, client: AsyncClient, runtime_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(
        CreateThreadRequest(title="wip", workspace=str(runtime_data_dir / "ws"))
    )
    evicted: list[str] = []

    async def evict(thread_id: str) -> None:
        evicted.append(thread_id)

    monkeypatch.setattr(mgr, "_evict_active_thread", evict)
    monkeypatch.setattr(mgr, "_worktree_keeps_unpublished", lambda t: t.id == thread.id)
    mgr._active[thread.id] = object()  # type: ignore[assignment]
    try:
        r = await client.post("/v1/data/clear-history")
    finally:
        mgr._active.pop(thread.id, None)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "history_blocked"
    assert evicted == []
    assert mgr.store.load_thread(thread.id).id == thread.id


def test_storage_categories_cover_the_whole_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deepseek_tui.server.data_inventory import collect_inventory

    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    for rel, size in {
        "threads/threads/t.json": 10,
        "media/img": 5,
        "browser/profiles/p/Cookies": 300,
        "workspace/scratch/a.txt": 200,
        "logs/deepseek.log": 40,
        "worktrees/repo/file": 70,
        "skills/s/SKILL.md": 7,
        "config.toml": 3,
    }.items():
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)

    body = collect_inventory(
        home_dir=home,
        threads_dir=home / "threads",
        sessions_dir=home / "sessions",
        state_db_path=home / "state.db",
    )
    sizes = {c["key"]: c["bytes"] for c in body["categories"]}
    assert sizes["browser"] == 300 and sizes["workspace"] == 200
    assert sizes["logs"] == 40 and sizes["worktrees"] == 70
    # skills + config.toml, plus the thread store's own lock file beside threads/.
    assert sizes["other"] == 10 + (home / ".threads.events.lock").stat().st_size
    assert sizes["conversations"] >= 15
    assert sum(sizes.values()) == body["storage_total_bytes"]
    paths = {c["key"]: c["reveal_path"] for c in body["categories"]}
    assert paths["conversations"] == str(home / "threads")
    assert paths["browser"] == str(home / "browser")
    assert paths["workspace"] == str(home / "workspace")
    assert paths["logs"] == str(home / "logs")
    assert paths["worktrees"] == str(home / "worktrees")
    assert paths["other"] == str(home)


def test_storage_categories_partition_nested_and_external_roots(tmp_path, monkeypatch):
    from deepseek_tui.server.data_inventory import storage_categories

    home = tmp_path / "home"
    logs = tmp_path / "custom-logs"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    for path, size in {
        home / "workspace/custom-threads/t.json": 10,
        home / "workspace/notes.txt": 20,
        home / "config.toml": 5,
        logs / "deepseek.log": 30,
    }.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    total, categories = storage_categories(
        home=home, threads_root=home / "workspace/custom-threads",
        sessions_root=home / "sessions", state_db=home / "state.db", logs_dir=logs,
    )
    sizes = {c["key"]: c["bytes"] for c in categories}
    assert total == 65
    assert sizes == dict(conversations=10, browser=0, workspace=20, logs=30, worktrees=0, other=5)
    assert next(c for c in categories if c["key"] == "logs")["reveal_path"] == str(logs)
