"""GET /v1/sessions + POST /v1/threads/{id}/export-session."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from deepseek_tui.config.paths import user_sessions_dir
from deepseek_tui.protocol.messages import Message


@pytest.mark.asyncio
async def test_list_sessions_merges_tui_and_threads(
    client: AsyncClient,
    runtime_data_dir,
) -> None:
    sessions_dir = user_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = sessions_dir / "catalog-smoke.json"
    session_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "id": "catalog-smoke",
                    "title": "Catalog smoke",
                    "workspace": str(runtime_data_dir),
                },
                "messages": [Message.user("hello").model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )

    imported = await client.post(
        "/v1/threads/import-session",
        json={"path": str(session_path), "title": "Linked thread"},
    )
    assert imported.status_code == 201, imported.text
    thread_id = imported.json()["id"]

    r = await client.get("/v1/sessions?limit=20")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("dir"), str)
    sessions = body.get("sessions")
    assert isinstance(sessions, list)

    linked = next(
        (row for row in sessions if row.get("session_id") == "catalog-smoke"),
        None,
    )
    assert linked is not None
    assert linked.get("import_state") == "linked"
    assert linked.get("linked_thread_id") == thread_id

    native = next((row for row in sessions if row.get("thread_id") == thread_id), None)
    assert native is None or native.get("import_state") != "native"


@pytest.mark.asyncio
async def test_export_thread_to_tui_session(
    client: AsyncClient,
    runtime_app: object,
    runtime_data_dir,
) -> None:
    sessions_dir = user_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = sessions_dir / "export-source.json"
    session_path.write_text(
        json.dumps(
            {
                "metadata": {"id": "export-source", "workspace": str(runtime_data_dir)},
                "messages": [
                    Message.user("export me").model_dump(mode="json"),
                    Message.assistant("exported").model_dump(mode="json"),
                ],
            }
        ),
        encoding="utf-8",
    )

    imported = await client.post(
        "/v1/threads/import-session",
        json={"path": str(session_path), "title": "Export me"},
    )
    assert imported.status_code == 201, imported.text
    thread_id = imported.json()["id"]

    r = await client.post(f"/v1/threads/{thread_id}/export-session")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("thread_id") == thread_id
    path = body.get("path")
    assert isinstance(path, str)
    exported = json.loads(open(path, encoding="utf-8").read())
    assert exported["metadata"]["workbench_thread_id"] == thread_id
    assert len(exported["messages"]) >= 2

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    thread = manager.store.load_thread(thread_id)
    assert thread.source_session_id == body.get("session_id")
    assert thread.source_session_path == path
