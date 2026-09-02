"""Canonical thread persistence and legacy crash-checkpoint coverage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from deepseek_tui.cli.app import app
from deepseek_tui.protocol.messages import Message
from deepseek_tui.server.sessions import persist_tui_thread
from deepseek_tui.server.threads import reconstruct_messages_from_turns
from deepseek_tui.server.threads.models import ThreadRecord
from deepseek_tui.server.threads.store import RuntimeThreadStore
from deepseek_tui.state.session import clear_checkpoint, load_checkpoint, save_checkpoint
from deepseek_tui.tui.app import DeepSeekTUI


def _thread(thread_id: str, workspace: Path) -> ThreadRecord:
    now = datetime.now(timezone.utc)
    return ThreadRecord(
        id=thread_id,
        created_at=now,
        updated_at=now,
        model="deepseek-v4-pro",
        workspace=str(workspace),
        title="Original title",
    )


def test_cli_thread_commands_use_runtime_store(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    store = RuntimeThreadStore(home / "threads")
    store.save_thread(_thread("thread-1", tmp_path))
    runner = CliRunner()

    listed = runner.invoke(app, ["thread", "list"])
    assert listed.exit_code == 0
    assert "thread-1  Original title" in listed.stdout

    renamed = runner.invoke(app, ["thread", "set-name", "thread-1", "New title"])
    assert renamed.exit_code == 0
    assert store.load_thread("thread-1").title == "New title"

    archived = runner.invoke(app, ["thread", "archive", "thread-1"])
    assert archived.exit_code == 0
    assert store.load_thread("thread-1").archived is True
    assert "thread-1" not in runner.invoke(app, ["thread", "list"]).stdout
    assert "thread-1" in runner.invoke(app, ["thread", "list", "--all"]).stdout

    unarchived = runner.invoke(app, ["thread", "unarchive", "thread-1"])
    assert unarchived.exit_code == 0
    assert "thread-1" in runner.invoke(app, ["sessions"]).stdout

    metrics = runner.invoke(app, ["metrics", "--json"])
    assert metrics.exit_code == 0
    assert json.loads(metrics.stdout)["total_sessions"] == 1

    read = runner.invoke(app, ["thread", "read", "thread-1"])
    assert read.exit_code == 0
    assert json.loads(read.stdout)["title"] == "New title"


def test_checkpoint_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    save_checkpoint({"session_id": "legacy-crash"})
    assert load_checkpoint() == {
        "schema_version": 1,
        "session_id": "legacy-crash",
    }
    clear_checkpoint()
    assert load_checkpoint() is None


def test_tui_persistence_appends_to_canonical_thread_without_duplicates(
    tmp_path: Path,
) -> None:
    store = RuntimeThreadStore(tmp_path / "threads")
    first_turn = [Message.user("first"), Message.assistant("one")]

    persist_tui_thread(
        store,
        thread_id="tui-thread",
        messages=first_turn,
        model="deepseek-chat",
        provider="deepseek",
        workspace=str(tmp_path),
        mode="agent",
    )
    first_turn_ids = [turn.id for turn in store.list_turns_for_thread("tui-thread")]

    persist_tui_thread(
        store,
        thread_id="tui-thread",
        messages=first_turn,
        model="deepseek-chat",
        provider="deepseek",
        workspace=str(tmp_path),
        mode="agent",
    )
    assert [turn.id for turn in store.list_turns_for_thread("tui-thread")] == first_turn_ids

    all_messages = [*first_turn, Message.user("second"), Message.assistant("two")]
    thread = persist_tui_thread(
        store,
        thread_id="tui-thread",
        messages=all_messages,
        model="deepseek-chat",
        provider="deepseek",
        workspace=str(tmp_path),
        mode="agent",
    )

    turns = store.list_turns_for_thread("tui-thread")
    assert thread is not None
    assert thread.latest_turn_id == turns[-1].id
    assert len(turns) == 2
    assert turns[0].id == first_turn_ids[0]
    assert [message.role for message in reconstruct_messages_from_turns(store, thread.id)] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_tui_picker_uses_threads_not_legacy_json(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "current.json").write_text("{}", encoding="utf-8")
    store = RuntimeThreadStore(home / "threads")
    store.save_thread(_thread("canonical-thread", tmp_path))

    assert DeepSeekTUI._discover_session_picks() == [
        ("canonical-thread", "Original title")
    ]
