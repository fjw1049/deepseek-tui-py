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


@pytest.mark.parametrize("patch", [
    {"version": []}, {"version": True}, {"version": "1"},
    {"includes": []}, {"includes": {"threads": "false"}},
])
@pytest.mark.asyncio
async def test_import_rejects_malformed_manifest(client, tmp_path, patch):
    archive = tmp_path / "malformed.zip"
    manifest = {"format": "deepseek-data-export", "version": 1, "includes": {}, **patch}
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
    for endpoint in ("/v1/data/import/inspect", "/v1/data/import"):
        result = await client.post(endpoint, json={"path": str(archive)})
        assert result.status_code == 400, result.text


@pytest.mark.asyncio
async def test_inspect_rejects_oversized_manifest(client, tmp_path):
    archive = tmp_path / "oversized.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", b" " * 1_048_577)
    result = await client.post("/v1/data/import/inspect", json={"path": str(archive)})
    assert result.status_code == 400


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
    backup = Path(body["path"])
    assert backup.suffix == ".zip" and backup.parent == backup_root.resolve()
    # A backup is an ordinary export, so Import can restore it.
    r = await client.post("/v1/data/import/inspect", json={"path": str(backup)})
    assert r.status_code == 200, r.text
    assert (r.json()["has_conversations"], r.json()["threads"]) == (True, 1)
    assert r.json()["settings"] == []

    r = await client.get("/v1/data/backup")
    assert r.status_code == 200
    status = r.json()
    assert status["last_backup_at"]
    assert status["directory"]


@pytest.mark.asyncio
async def test_inspect_then_restore_settings_only_bundle(
    runtime_app, client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deepseek_tui.config.paths import settings_path, user_config_path

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    user_config_path().parent.mkdir(parents=True, exist_ok=True)
    user_config_path().write_text('model = "exported"\n', encoding="utf-8")
    settings_path().write_text('{"locale": "zh"}', encoding="utf-8")
    export_path = tmp_path / "settings.zip"
    r = await client.post("/v1/data/export", json={"path": str(export_path), "scope": "settings"})
    assert r.status_code == 200, r.text

    user_config_path().write_text('model = "local"\n', encoding="utf-8")
    r = await client.post("/v1/data/import/inspect", json={"path": str(export_path)})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "scope": "settings",
        "has_conversations": False,
        "threads": 0,
        "settings": ["config.toml", "settings.json"],
    }

    r = await client.post("/v1/data/import", json={"path": str(export_path), "mode": "replace"})
    assert r.status_code == 200, r.text
    assert "config.toml" in r.json()["settings_restored"]
    assert user_config_path().read_text(encoding="utf-8") == 'model = "exported"\n'


@pytest.mark.asyncio
async def test_inspect_counts_conversations_and_rejects_foreign_zip(
    runtime_app, client: AsyncClient, runtime_data_dir: Path, tmp_path: Path
) -> None:
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(
        CreateThreadRequest(title="count", workspace=str(runtime_data_dir / "ws"))
    )
    _seed_turn(mgr, thread_id=thread.id, turn_id="turn_c1", user_id="item_cu", asst_id="item_ca")
    export_path = tmp_path / "conv.zip"
    r = await client.post(
        "/v1/data/export", json={"path": str(export_path), "scope": "conversations"}
    )
    assert r.status_code == 200, r.text
    r = await client.post("/v1/data/import/inspect", json={"path": str(export_path)})
    assert r.status_code == 200, r.text
    assert (r.json()["has_conversations"], r.json()["threads"]) == (True, 1)

    foreign = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as zf:
        zf.writestr("readme.txt", "hi")
    r = await client.post("/v1/data/import/inspect", json={"path": str(foreign)})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_bundle"
