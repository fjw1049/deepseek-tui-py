"""Rewind-in-place: ``before_item_id`` truncation contract.

Backs the Workbench "edit & resend" flow: rewinding a thread deletes the
target item and everything after it from the durable store (unlike fork,
which clones into a new thread), so a later reload cannot resurrect the
dropped turns. A warm engine session is re-synced to the truncated history.

The second half covers file restore: per-turn checkpoints recorded during a
turn can roll the workspace back on rewind (``restore_files=True``) or via
the conversation-preserving ``restore-code`` endpoint.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
    reconstruct_messages_from_turns,
)
from deepseek_tui.tools.file import WriteFileTool
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.workspace.git_reconcile import capture_baseline
from deepseek_tui.workspace.shell_mutation_watch import capture_shell_snapshot
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpoint


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _add_turn(
    manager,
    *,
    thread_id: str,
    turn_id: str,
    offset: int,
    user_id: str,
    user_text: str,
    asst_id: str,
    asst_text: str,
) -> None:
    ts = datetime(2020, 1, 1, offset, tzinfo=timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary=user_text,
            created_at=ts,
            started_at=ts,
            ended_at=ts,
            item_ids=[user_id, asst_id],
        )
    )
    for item_id, kind, text in (
        (user_id, TurnItemKind.USER_MESSAGE, user_text),
        (asst_id, TurnItemKind.AGENT_MESSAGE, asst_text),
    ):
        manager.store.save_item(
            TurnItemRecord(
                id=item_id,
                turn_id=turn_id,
                kind=kind,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=text,
                detail=text,
                started_at=ts,
                ended_at=ts,
            )
        )


async def _seed(manager, workspace: str | None = None) -> str:
    thread = await manager.create_thread(
        CreateThreadRequest(
            title="rewind-test", workspace=workspace or str(manager.workspace)
        )
    )
    thread_id = thread.id
    _add_turn(
        manager,
        thread_id=thread_id,
        turn_id="turn_a",
        offset=1,
        user_id="item_u1",
        user_text="Q1",
        asst_id="item_a1",
        asst_text="A1",
    )
    _add_turn(
        manager,
        thread_id=thread_id,
        turn_id="turn_b",
        offset=2,
        user_id="item_u2",
        user_text="Q2",
        asst_id="item_a2",
        asst_text="A2",
    )
    return thread_id


@pytest.mark.asyncio
async def test_rewind_at_user_message_deletes_turn_and_after(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    thread = await manager.rewind_thread(thread_id, before_item_id="item_u2")

    turns = manager.store.list_turns_for_thread(thread_id)
    assert [t.id for t in turns] == ["turn_a"]
    assert thread.latest_turn_id == "turn_a"
    messages = reconstruct_messages_from_turns(manager.store, thread_id)
    assert [m.content[0].text for m in messages] == ["Q1", "A1"]
    # Item files for the dropped turn are gone, not just unreferenced.
    with pytest.raises(FileNotFoundError):
        manager.store.load_item("item_u2")
    with pytest.raises(FileNotFoundError):
        manager.store.load_item("item_a2")
    with pytest.raises(FileNotFoundError):
        manager.store.load_turn("turn_b")


@pytest.mark.asyncio
async def test_rewind_mid_turn_keeps_earlier_items(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    await manager.rewind_thread(thread_id, before_item_id="item_a1")

    turns = manager.store.list_turns_for_thread(thread_id)
    assert [t.id for t in turns] == ["turn_a"]
    items = manager.store.list_items_for_turn("turn_a")
    assert [i.detail for i in items] == ["Q1"]
    messages = reconstruct_messages_from_turns(manager.store, thread_id)
    assert [m.content[0].text for m in messages] == ["Q1"]


@pytest.mark.asyncio
async def test_rewind_at_first_item_empties_thread(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    thread = await manager.rewind_thread(thread_id, before_item_id="item_u1")

    assert manager.store.list_turns_for_thread(thread_id) == []
    assert thread.latest_turn_id is None
    assert reconstruct_messages_from_turns(manager.store, thread_id) == []


@pytest.mark.asyncio
async def test_rewind_resyncs_warm_engine_session(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    synced: list[list] = []

    class FakeEngine:
        def sync_session(self, messages, *, model=None):
            synced.append(list(messages))

    manager._active[thread_id] = SimpleNamespace(
        engine=FakeEngine(), active_turn=None
    )
    try:
        await manager.rewind_thread(thread_id, before_item_id="item_u2")
    finally:
        manager._active.pop(thread_id, None)

    assert len(synced) == 1
    assert [m.content[0].text for m in synced[0]] == ["Q1", "A1"]


@pytest.mark.asyncio
async def test_rewind_rejected_while_turn_active(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    manager._active[thread_id] = SimpleNamespace(
        engine=None, active_turn=object()
    )
    try:
        with pytest.raises(ValueError):
            await manager.rewind_thread(thread_id, before_item_id="item_u2")
    finally:
        manager._active.pop(thread_id, None)

    # Nothing was deleted.
    turns = manager.store.list_turns_for_thread(thread_id)
    assert [t.id for t in turns] == ["turn_a", "turn_b"]


@pytest.mark.asyncio
async def test_rewind_unknown_item_raises_value_error(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    with pytest.raises(ValueError):
        await manager.rewind_thread(thread_id, before_item_id="item_nope")


@pytest.mark.asyncio
async def test_rewind_http_truncates_in_place(
    runtime_app, client: AsyncClient
) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    r = await client.post(
        f"/v1/threads/{thread_id}/rewind",
        json={"before_item_id": "item_u2"},
    )
    assert r.status_code == 200
    assert r.json()["id"] == thread_id

    detail = await client.get(f"/v1/threads/{thread_id}")
    assert detail.status_code == 200
    items = detail.json().get("items", [])
    assert [i["detail"] for i in items] == ["Q1", "A1"]


@pytest.mark.asyncio
async def test_rewind_http_unknown_item_returns_400(
    runtime_app, client: AsyncClient
) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    r = await client.post(
        f"/v1/threads/{thread_id}/rewind",
        json={"before_item_id": "item_nope"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_request"


# --- file restore (turn checkpoints) -----------------------------------------


def _ws(runtime_data_dir: Path) -> Path:
    """A dedicated workspace dir — never the runtime's own cwd."""
    ws = runtime_data_dir / "ws"
    ws.mkdir(exist_ok=True)
    return ws


async def _seed_tool_write(
    manager, thread_id: str, ws: Path, *, filename: str = "note.txt"
) -> Path:
    """Simulate a turn_b tool write with the pre-write checkpoint hook live."""
    target = ws / filename
    target.write_text("old\n", encoding="utf-8")
    manager.checkpoints.begin_turn("turn_b", None, head=None, is_git=False, thread_id=thread_id)
    ctx = ToolContext(working_directory=ws)
    ctx.pre_write_capture = lambda p, old: manager.checkpoints.record_pre_write("turn_b", p, old)
    result = await WriteFileTool().execute({"path": filename, "content": "new\n"}, ctx)
    assert result.success
    assert target.read_text(encoding="utf-8") == "new\n"
    return target


@pytest.mark.asyncio
async def test_rewind_restore_files_restores_tool_writes(
    runtime_app, runtime_data_dir: Path
) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))
    target = await _seed_tool_write(manager, thread_id, ws)

    await manager.rewind_thread(thread_id, before_item_id="item_u2", restore_files=True)

    assert target.read_text(encoding="utf-8") == "old\n"
    # The dropped turn's checkpoint was consumed.
    assert manager.checkpoints.load("turn_b") is None


@pytest.mark.asyncio
async def test_rewind_restore_files_restores_shell_changes(
    runtime_app, runtime_data_dir: Path
) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))
    _git(ws, "init")
    _git(ws, "config", "user.email", "test@example.com")
    _git(ws, "config", "user.name", "Test")
    (ws / "tracked.py").write_text("v1\n", encoding="utf-8")
    _git(ws, "add", "tracked.py")
    _git(ws, "commit", "-m", "init")

    # Mirrors what _monitor_turn does at turn start.
    baseline = await capture_baseline(ws)
    snapshot = await capture_shell_snapshot(ws)
    manager.checkpoints.begin_turn(
        "turn_b",
        snapshot,
        head=baseline.head,
        is_git=baseline.is_git,
        thread_id=thread_id,
    )
    (ws / "tracked.py").write_text("v2\n", encoding="utf-8")
    manager.checkpoints.record_out_of_band("turn_b", "tracked.py")

    await manager.rewind_thread(thread_id, before_item_id="item_u2", restore_files=True)

    assert (ws / "tracked.py").read_text(encoding="utf-8") == "v1\n"


@pytest.mark.asyncio
async def test_rewind_without_restore_files_leaves_files(
    runtime_app, runtime_data_dir: Path
) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))
    target = await _seed_tool_write(manager, thread_id, ws)

    await manager.rewind_thread(thread_id, before_item_id="item_u2")

    # Regression: conversation truncated, files untouched — and the dropped
    # turn's checkpoint is kept so a later restore-code can still roll back.
    assert [t.id for t in manager.store.list_turns_for_thread(thread_id)] == ["turn_a"]
    assert target.read_text(encoding="utf-8") == "new\n"
    assert manager.checkpoints.load("turn_b") is not None


@pytest.mark.asyncio
async def test_restore_code_keeps_conversation_and_consumes_checkpoints(
    runtime_app, runtime_data_dir: Path
) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))
    (ws / "note.txt").write_text("old\n", encoding="utf-8")
    manager.checkpoints.begin_turn("turn_b", None, head=None, is_git=False, thread_id=thread_id)
    manager.checkpoints.record_pre_write("turn_b", "note.txt", "old\n")
    (ws / "note.txt").write_text("new\n", encoding="utf-8")

    result = await manager.restore_code(thread_id, before_item_id="item_u2")

    assert result["restored_files"] == ["note.txt"]
    assert result["skipped_files"] == []
    assert result["turns"] == 1
    assert (ws / "note.txt").read_text(encoding="utf-8") == "old\n"
    # Conversation untouched.
    turns = manager.store.list_turns_for_thread(thread_id)
    assert [t.id for t in turns] == ["turn_a", "turn_b"]
    messages = reconstruct_messages_from_turns(manager.store, thread_id)
    assert [m.content[0].text for m in messages] == ["Q1", "A1", "Q2", "A2"]
    # Checkpoint consumed: a second restore to the same point finds none.
    again = await manager.restore_code(thread_id, before_item_id="item_u2")
    assert again["restored_files"] == []
    assert again["turns_without_checkpoint"] == ["turn_b"]


@pytest.mark.asyncio
async def test_rewind_restore_files_multi_turn_returns_oldest_state(
    runtime_app, runtime_data_dir: Path
) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))
    _add_turn(
        manager,
        thread_id=thread_id,
        turn_id="turn_c",
        offset=3,
        user_id="item_u3",
        user_text="Q3",
        asst_id="item_a3",
        asst_text="A3",
    )
    target = ws / "f.txt"
    target.write_text("v1\n", encoding="utf-8")
    manager.checkpoints.begin_turn("turn_b", None, head=None, is_git=False, thread_id=thread_id)
    manager.checkpoints.record_pre_write("turn_b", "f.txt", "v1\n")
    manager.checkpoints.begin_turn("turn_c", None, head=None, is_git=False, thread_id=thread_id)
    manager.checkpoints.record_pre_write("turn_c", "f.txt", "v2\n")
    target.write_text("v3\n", encoding="utf-8")

    await manager.rewind_thread(thread_id, before_item_id="item_u2", restore_files=True)

    assert target.read_text(encoding="utf-8") == "v1\n"
    assert manager.checkpoints.load("turn_b") is None
    assert manager.checkpoints.load("turn_c") is None


@pytest.mark.asyncio
async def test_rewind_http_restore_files(
    runtime_app, client: AsyncClient, runtime_data_dir: Path
) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))
    target = await _seed_tool_write(manager, thread_id, ws)

    r = await client.post(
        f"/v1/threads/{thread_id}/rewind",
        json={"before_item_id": "item_u2", "restore_files": True},
    )
    assert r.status_code == 200
    assert target.read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_restore_code_http(runtime_app, client: AsyncClient, runtime_data_dir: Path) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))
    (ws / "note.txt").write_text("old\n", encoding="utf-8")
    manager.checkpoints.begin_turn("turn_b", None, head=None, is_git=False, thread_id=thread_id)
    manager.checkpoints.record_pre_write("turn_b", "note.txt", "old\n")
    (ws / "note.txt").write_text("new\n", encoding="utf-8")

    r = await client.post(
        f"/v1/threads/{thread_id}/restore-code",
        json={"before_item_id": "item_u2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["restored_files"] == ["note.txt"]
    assert body["skipped_files"] == []
    assert body["turns_without_checkpoint"] == []
    assert body["turns"] == 1
    assert (ws / "note.txt").read_text(encoding="utf-8") == "old\n"

    # Conversation items survive the file-only restore.
    detail = await client.get(f"/v1/threads/{thread_id}")
    assert detail.status_code == 200
    items = detail.json().get("items", [])
    assert [i["detail"] for i in items] == ["Q1", "A1", "Q2", "A2"]


@pytest.mark.asyncio
async def test_restore_code_http_unknown_item_returns_400(runtime_app, client: AsyncClient) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    r = await client.post(
        f"/v1/threads/{thread_id}/restore-code",
        json={"before_item_id": "item_nope"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_rewind_preview_http(
    runtime_app, client: AsyncClient, runtime_data_dir: Path
) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))
    manager.checkpoints.begin_turn("turn_b", None, head=None, is_git=False, thread_id=thread_id)
    manager.checkpoints.record_pre_write("turn_b", "note.txt", "old\n")

    r = await client.get(
        f"/v1/threads/{thread_id}/rewind-preview",
        params={"before_item_id": "item_u2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["files"] == ["note.txt"]
    assert body["skipped"] == []
    assert body["is_git"] is False
    assert body["turns"] == 1
    assert body["no_checkpoint"] == 0

    # After restore-code consumes turn_b's checkpoint the preview shows the
    # turn has nothing left to restore.
    await manager.restore_code(thread_id, before_item_id="item_u2")
    r = await client.get(
        f"/v1/threads/{thread_id}/rewind-preview",
        params={"before_item_id": "item_u2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["files"] == []
    assert body["turns"] == 1
    assert body["no_checkpoint"] == 1


@pytest.mark.asyncio
async def test_rewind_preview_http_unknown_item_returns_400(
    runtime_app, client: AsyncClient
) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    r = await client.get(
        f"/v1/threads/{thread_id}/rewind-preview",
        params={"before_item_id": "item_nope"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_conversation_rewind_then_restore_code_replays_orphan_checkpoint(
    runtime_app, runtime_data_dir: Path
) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))
    target = await _seed_tool_write(manager, thread_id, ws)

    # Conversation-only rewind: turn_b is dropped but its checkpoint stays.
    await manager.rewind_thread(thread_id, before_item_id="item_u2")
    assert [t.id for t in manager.store.list_turns_for_thread(thread_id)] == ["turn_a"]
    assert target.read_text(encoding="utf-8") == "new\n"
    assert manager.checkpoints.load("turn_b") is not None

    # restore-code on the remaining conversation still replays the orphan
    # checkpoint left by turn_b.
    result = await manager.restore_code(thread_id, before_item_id="item_u1")

    assert result["restored_files"] == ["note.txt"]
    assert target.read_text(encoding="utf-8") == "old\n"
    assert manager.checkpoints.load("turn_b") is None


@pytest.mark.asyncio
async def test_restore_code_rejected_while_turn_active(runtime_app, client: AsyncClient) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    manager._active[thread_id] = SimpleNamespace(engine=None, active_turn=object())
    try:
        with pytest.raises(ValueError):
            await manager.restore_code(thread_id, before_item_id="item_u2")
        r = await client.post(
            f"/v1/threads/{thread_id}/restore-code",
            json={"before_item_id": "item_u2"},
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_request"
    finally:
        manager._active.pop(thread_id, None)


def _write_checkpoint(
    manager,
    *,
    turn_id: str,
    thread_id: str,
    created_at: float,
    pre_contents: dict[str, str | None],
) -> None:
    """Persist a checkpoint with an explicit creation time (ordering tests)."""
    cp = TurnCheckpoint(
        turn_id=turn_id,
        is_git=False,
        thread_id=thread_id,
        created_at=created_at,
        pre_contents=pre_contents,
        mutated=list(pre_contents),
    )
    (manager.checkpoints._root / f"{turn_id}.json").write_text(
        json.dumps(cp.to_dict()), encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_restore_code_excludes_orphans_predating_cutoff_turn(
    runtime_app, runtime_data_dir: Path
) -> None:
    manager = runtime_app.state.thread_manager
    ws = _ws(runtime_data_dir)
    thread_id = await _seed(manager, workspace=str(ws))  # turns A(offset 1), B(2)
    (ws / "f1.txt").write_text("a1\n", encoding="utf-8")
    (ws / "f2.txt").write_text("b1\n", encoding="utf-8")
    _write_checkpoint(
        manager, turn_id="turn_a", thread_id=thread_id, created_at=100.0,
        pre_contents={"f1.txt": "a0\n"},
    )
    _write_checkpoint(
        manager, turn_id="turn_b", thread_id=thread_id, created_at=200.0,
        pre_contents={"f2.txt": "b0\n"},
    )

    # Conversation-only rewind at B's user message → B's checkpoint orphans,
    # the files keep B's state.
    await manager.rewind_thread(thread_id, before_item_id="item_u2")
    assert [t.id for t in manager.store.list_turns_for_thread(thread_id)] == ["turn_a"]
    assert manager.checkpoints.load("turn_b") is not None

    # Conversation continues on top of B's file state: C edits f2, D adds f3.
    _add_turn(
        manager, thread_id=thread_id, turn_id="turn_c", offset=3,
        user_id="item_u3", user_text="Q3", asst_id="item_a3", asst_text="A3",
    )
    _add_turn(
        manager, thread_id=thread_id, turn_id="turn_d", offset=4,
        user_id="item_u4", user_text="Q4", asst_id="item_a4", asst_text="A4",
    )
    (ws / "f2.txt").write_text("c1\n", encoding="utf-8")
    (ws / "f3.txt").write_text("d1\n", encoding="utf-8")
    _write_checkpoint(
        manager, turn_id="turn_c", thread_id=thread_id, created_at=300.0,
        pre_contents={"f2.txt": "b1\n"},
    )
    _write_checkpoint(
        manager, turn_id="turn_d", thread_id=thread_id, created_at=400.0,
        pre_contents={"f3.txt": None},
    )

    # The preview must not list files exclusive to the excluded orphan (f2).
    preview = await manager.rewind_preview(thread_id, before_item_id="item_u4")
    assert preview["files"] == ["f3.txt"]
    assert preview["no_checkpoint"] == 0

    result = await manager.restore_code(thread_id, before_item_id="item_u4")

    # Only D's change is rolled back (f3 did not exist before D).
    assert result["restored_files"] == ["f3.txt"]
    assert not (ws / "f3.txt").exists()
    # B's and C's edits to f2 survive; A's edit to f1 survives.
    assert (ws / "f2.txt").read_text(encoding="utf-8") == "c1\n"
    assert (ws / "f1.txt").read_text(encoding="utf-8") == "a1\n"
    # Neither the excluded orphan B nor in-conversation C is consumed.
    assert manager.checkpoints.load("turn_b") is not None
    assert manager.checkpoints.load("turn_c") is not None
