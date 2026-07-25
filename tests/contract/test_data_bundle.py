"""Contract tests for /v1/data export, import, and backup."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient

from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
)


def _seed_turn(manager, *, thread_id: str, turn_id: str, user_id: str, asst_id: str) -> None:
    when = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="hi",
            created_at=when,
            started_at=when,
            ended_at=when,
            item_ids=[user_id, asst_id],
        )
    )
    for item_id, kind, text in (
        (user_id, TurnItemKind.USER_MESSAGE, "hi"),
        (asst_id, TurnItemKind.AGENT_MESSAGE, "hello"),
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
async def test_export_import_merge_roundtrip(
    runtime_app, client: AsyncClient, runtime_data_dir: Path, tmp_path: Path
) -> None:
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(
        CreateThreadRequest(title="bundle", workspace=str(runtime_data_dir / "ws"))
    )
    _seed_turn(
        mgr,
        thread_id=thread.id,
        turn_id="turn_b1",
        user_id="item_bu",
        asst_id="item_ba",
    )

    export_path = tmp_path / "export.zip"
    r = await client.post(
        "/v1/data/export",
        json={"path": str(export_path), "scope": "conversations"},
    )
    assert r.status_code == 200, r.text
    assert export_path.is_file()
    with zipfile.ZipFile(export_path) as zf:
        assert "manifest.json" in zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"] == "deepseek-data-export"
        assert manifest["scope"] == "conversations"

    # Clear then import should restore.
    r = await client.post("/v1/data/clear-history")
    assert r.status_code == 200
    assert mgr.store.list_threads() == []

    r = await client.post(
        "/v1/data/import",
        json={"path": str(export_path), "mode": "merge"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["threads_imported"] == 1
    restored = mgr.store.load_thread(thread.id)
    assert restored.id == thread.id
    assert mgr.store.load_item("item_ba").detail == "hello"


@pytest.mark.asyncio
async def test_import_merge_skips_existing(
    runtime_app, client: AsyncClient, runtime_data_dir: Path, tmp_path: Path
) -> None:
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(
        CreateThreadRequest(title="keep", workspace=str(runtime_data_dir / "ws"))
    )
    _seed_turn(
        mgr,
        thread_id=thread.id,
        turn_id="turn_k1",
        user_id="item_ku",
        asst_id="item_ka",
    )
    export_path = tmp_path / "skip.zip"
    r = await client.post(
        "/v1/data/export",
        json={"path": str(export_path), "scope": "conversations"},
    )
    assert r.status_code == 200

    r = await client.post(
        "/v1/data/import",
        json={"path": str(export_path), "mode": "merge"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["threads_imported"] == 0
    assert body["threads_skipped"] == 1


@pytest.mark.asyncio
async def test_backup_requires_directory_then_succeeds(
    runtime_app, client: AsyncClient, runtime_data_dir: Path, tmp_path: Path
) -> None:
    mgr = runtime_app.state.thread_manager
    await mgr.create_thread(
        CreateThreadRequest(title="bak", workspace=str(runtime_data_dir / "ws"))
    )

    r = await client.post("/v1/data/backup", json={})
    assert r.status_code == 400

    backup_root = tmp_path / "backups"
    r = await client.post(
        "/v1/data/backup/directory",
        json={"directory": str(backup_root)},
    )
    assert r.status_code == 200, r.text
    assert Path(r.json()["directory"]) == backup_root.resolve()

    r = await client.post("/v1/data/backup", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert Path(body["path"]).is_dir()
    assert (Path(body["path"]) / "manifest.json").is_file()
    assert (Path(body["path"]) / "threads").is_dir()

    r = await client.get("/v1/data/backup")
    assert r.status_code == 200
    status = r.json()
    assert status["last_backup_at"]
    assert status["directory"]
