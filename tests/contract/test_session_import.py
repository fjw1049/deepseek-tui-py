"""POST /v1/threads/import-session — TUI session → Workbench thread."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from deepseek_tui.server.threads import (
    TurnItemKind,
    reconstruct_messages_from_turns,
)
from deepseek_tui.config.paths import user_sessions_dir
from deepseek_tui.protocol.messages import Message, ToolUseBlock


@pytest.mark.asyncio
async def test_import_tui_session_by_path(
    client: AsyncClient,
    runtime_app: object,
    runtime_data_dir,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions_dir = user_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = sessions_dir / "import-smoke.json"
    session_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "id": "session-import-smoke",
                    "model": "deepseek-chat",
                    "workspace": str(runtime_data_dir),
                },
                "messages": [
                    Message.user("Hello from TUI").model_dump(mode="json"),
                    Message.assistant("Hi from assistant").model_dump(mode="json"),
                ],
            }
        ),
        encoding="utf-8",
    )

    r = await client.post(
        "/v1/threads/import-session",
        json={"path": str(session_path), "title": "Imported chat"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Imported chat"

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    detail = await manager.get_thread_detail(body["id"])
    assert len(detail.turns) >= 1
    assert len(detail.items) >= 2

    thread = manager.store.load_thread(body["id"])
    assert thread.source_session_id == "session-import-smoke"
    assert thread.source_session_path == str(session_path.resolve())

    messages = reconstruct_messages_from_turns(manager.store, body["id"])
    assert len(messages) == 2
    assert messages[0].content[0].text == "Hello from TUI"
    assert messages[1].content[0].text == "Hi from assistant"


@pytest.mark.asyncio
async def test_import_tui_session_preserves_tool_history(
    client: AsyncClient,
    runtime_app: object,
    runtime_data_dir,
) -> None:
    sessions_dir = user_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = sessions_dir / "import-tools.json"
    tool_id = "toolu_import123"
    session_path.write_text(
        json.dumps(
            {
                "metadata": {"workspace": str(runtime_data_dir)},
                "messages": [
                    Message.user("run tool").model_dump(mode="json"),
                    Message.assistant_with_tools(
                        [ToolUseBlock(id=tool_id, name="read_file", input={"path": "a.txt"})]
                    ).model_dump(mode="json"),
                    Message.tool_result(tool_id, "file contents").model_dump(mode="json"),
                ],
            }
        ),
        encoding="utf-8",
    )

    r = await client.post(
        "/v1/threads/import-session",
        json={"path": str(session_path)},
    )
    assert r.status_code == 201, r.text
    thread_id = r.json()["id"]

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    detail = await manager.get_thread_detail(thread_id)
    tool_items = [item for item in detail.items if item.kind == TurnItemKind.TOOL_CALL]
    assert len(tool_items) >= 1
    assert any(item.summary == "read_file" for item in tool_items)

    messages = reconstruct_messages_from_turns(manager.store, thread_id)
    assert len(messages) == 3
    assert messages[1].content[0].name == "read_file"
    assert messages[2].content[0].content == "file contents"


@pytest.mark.asyncio
async def test_import_missing_session_returns_404(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/threads/import-session",
        json={"session_id": "does-not-exist-xyz"},
    )
    assert r.status_code == 404
