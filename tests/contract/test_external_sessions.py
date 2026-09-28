"""External history must stay faithful, idempotent, and inert on resume."""

import json

import pytest

from deepseek_tui.server.external_sessions import import_session, read_history, scan_sessions
from deepseek_tui.server.threads import reconstruct_messages_from_turns
from deepseek_tui.server.threads.store import RuntimeThreadStore

STAMP = "2026-09-01T12:00:00Z"


def write_log(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def codex_rows(sid="session-1", workspace="/missing/project"):
    def response(payload):
        return {"type": "response_item", "timestamp": STAMP, "payload": payload}

    return [
        {"type": "session_meta", "payload": {"id": sid, "cwd": workspace}},
        response(
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "old privileged instructions"}],
            }
        ),
        response(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Fix the bug"}],
            }
        ),
        response(
            {
                "type": "function_call",
                "name": "Bash",
                "call_id": "call-1",
                "arguments": '{"command":"echo done"}',
            }
        ),
        response({"type": "function_call_output", "call_id": "call-1", "output": "done"}),
        response(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Fixed"}],
            }
        ),
    ]


def import_log(store, path, **kwargs):
    return import_session(
        store,
        source="codex",
        root=str(path.parent),
        path=str(path),
        session_id="session-1",
        workspace=None,
        model="current-model",
        provider="deepseek",
        **kwargs,
    )


def test_codex_projection_avoids_duplicates_and_keeps_uppercase_text(tmp_path):
    rows = codex_rows()
    for item in [
        {"type": "UserMessage", "id": "u", "content": [{"type": "text", "text": "Fix the bug"}]},
        {
            "type": "CommandExecution",
            "id": "tool",
            "command": "echo done",
            "aggregated_output": "done",
            "status": "completed",
        },
        {"type": "AgentMessage", "id": "a", "content": [{"type": "Text", "text": "Fixed"}]},
    ]:
        rows.append(
            {
                "timestamp": STAMP,
                "type": "event_msg",
                "payload": {"type": "item_completed", "item": item},
            }
        )
    path = write_log(tmp_path / "source/session.jsonl", rows)
    history = read_history("codex", path)
    assert [e.kind for e in history.entries] == ["user_message", "tool_call", "agent_message"]
    assert history.entries[-1].text == "Fixed"
    assert not any("privileged" in e.text for e in history.entries)


def test_claude_ancestry_block_ids_and_tool_results(tmp_path):
    def row(uid, parent, role, content, **extra):
        return {
            "uuid": uid,
            "parentUuid": parent,
            "type": role,
            "sessionId": "claude-1",
            "timestamp": STAMP,
            "message": {"id": "same-api-message", "role": role, "content": content},
            **extra,
        }

    rows = [
        row("u", None, "user", "Question"),
        row("a", "u", "assistant", [{"type": "text", "text": "Checking"}]),
        row(
            "b",
            "a",
            "assistant",
            [{"type": "tool_use", "id": "t", "name": "Read", "input": {"file_path": "a.py"}}],
            apiBlockIndex=1,
        ),
        row(
            "result",
            "b",
            "user",
            [{"type": "tool_result", "tool_use_id": "t", "content": "file contents"}],
        ),
        row("old", "u", "assistant", [{"type": "text", "text": "Discarded branch"}]),
        row("final", "result", "assistant", [{"type": "text", "text": "Answer"}]),
        row("side", "u", "assistant", [{"type": "text", "text": "Subagent"}], isSidechain=True),
    ]
    history = read_history("claude", write_log(tmp_path / "s.jsonl", rows))
    assert [e.kind for e in history.entries] == [
        "user_message",
        "agent_message",
        "tool_call",
        "agent_message",
    ]
    assert "file contents" in history.entries[2].text
    assert "Checking" == history.entries[1].text
    assert "other_branches_skipped" in history.warnings
    assert not any("Discarded" in e.text or "Subagent" in e.text for e in history.entries)


def test_import_repeat_resume_and_original_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    path = write_log(tmp_path / "source/session.jsonl", codex_rows(workspace=str(tmp_path)))
    original = path.read_bytes()
    store = RuntimeThreadStore(tmp_path / "store")
    result = import_log(store, path)
    assert result["status"] == "imported"
    assert import_log(store, path)["status"] == "skipped"
    assert len(store.list_threads()) == 1
    thread = store.load_thread(result["thread_id"])
    assert thread.model == "current-model" and thread.provider == "deepseek"
    assert thread.created_at.isoformat() == "2026-09-01T12:00:00+00:00"
    assert not thread.auto_approve and not thread.trust_mode
    messages = reconstruct_messages_from_turns(store, thread.id)
    assert len(messages) == 3
    assert all(block.type == "text" for m in messages for block in m.content)
    assert "Historical tool record" in messages[1].text_content()
    assert "done" in messages[1].text_content()
    assert path.read_bytes() == original


def test_failure_rolls_back_and_retry_succeeds(tmp_path, monkeypatch):
    path = write_log(tmp_path / "source/session.jsonl", codex_rows())
    store = RuntimeThreadStore(tmp_path / "store")
    save = store.save_turn

    def fail(_):
        raise OSError("disk full")

    monkeypatch.setattr(store, "save_turn", fail)
    with pytest.raises(OSError, match="disk full"):
        import_log(store, path)
    assert not store.list_threads() and not store.iter_turns() and not store.iter_items()
    monkeypatch.setattr(store, "save_turn", save)
    assert import_log(store, path)["status"] == "imported"


def test_incomplete_tail_is_snapshot_but_corrupt_middle_is_error(tmp_path):
    path = write_log(tmp_path / "session.jsonl", codex_rows())
    with path.open("a") as f:
        f.write('{"type":')
    assert "unfinished_tail" in read_history("codex", path).warnings
    with path.open("a") as f:
        f.write('\n{"type":"next"}\n')
    with pytest.raises(ValueError, match="invalid JSON"):
        read_history("codex", path)


def test_scan_archive_dedup_and_subagents(tmp_path):
    root = tmp_path / "codex"
    write_log(root / "sessions/one.jsonl", codex_rows())
    write_log(root / "sessions/copy.jsonl", codex_rows())
    write_log(root / "archived_sessions/two.jsonl", codex_rows("session-2"))
    child = codex_rows("child")
    child[0]["payload"]["source"] = {"subagent": {"other": "guardian"}}
    write_log(root / "sessions/child.jsonl", child)
    result = scan_sessions(RuntimeThreadStore(tmp_path / "store"), "codex", str(root))
    assert len(result["sessions"]) == 2
    assert sum(row["archived"] for row in result["sessions"]) == 1
    assert result["skipped"] == 1
    assert not result["errors"]


async def test_api_history_only_requires_link_then_idempotent(client, runtime_app, tmp_path):
    path = write_log(tmp_path / "source/session.jsonl", codex_rows())
    body = {
        "source": "codex",
        "root": str(path.parent),
        "path": str(path),
        "session_id": "session-1",
    }
    response = await client.post("/v1/external-sessions/import", json=body)
    assert response.status_code == 200, response.text
    tid = response.json()["thread_id"]
    assert response.json()["history_only"]
    mgr = runtime_app.state.thread_manager
    from deepseek_tui.server.threads.models import StartTurnRequest

    with pytest.raises(ValueError, match="imported history"):
        await mgr.start_turn(tid, StartTurnRequest(prompt="continue"))
    response = await client.post(
        "/v1/external-sessions/import", json={**body, "workspace": str(tmp_path)}
    )
    assert response.json()["status"] == "linked"
    assert not mgr.store.load_thread(tid).import_history_only
    response = await client.post("/v1/external-sessions/import", json=body)
    assert response.json()["status"] == "skipped"
    response = await client.post(
        "/v1/external-sessions/import",
        json={**body, "root": str(tmp_path / "elsewhere"), "session_id": "not-imported"},
    )
    assert response.status_code == 400
    response = await client.post("/v1/external-sessions/scan", json={"source": "unsupported"})
    assert response.status_code == 422


def test_relink_remains_available_without_source_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    path = write_log(tmp_path / "source/session.jsonl", codex_rows())
    store = RuntimeThreadStore(tmp_path / "store")
    result = import_log(store, path)
    path.unlink()
    rows = scan_sessions(store, "codex", str(path.parent))["sessions"]
    assert len(rows) == 1 and rows[0]["history_only"]
    linked = import_session(
        store,
        source="codex",
        root=str(path.parent),
        path=str(path),
        session_id="session-1",
        workspace=str(tmp_path),
        model="current-model",
        provider="deepseek",
    )
    assert linked["status"] == "linked" and linked["thread_id"] == result["thread_id"]


def test_claude_final_leaf_pointer_selects_branch(tmp_path):
    rows = [
        {
            "uuid": "u",
            "sessionId": "c",
            "type": "user",
            "message": {"role": "user", "content": "Question"},
        },
        {
            "uuid": "a",
            "parentUuid": "u",
            "type": "assistant",
            "message": {"role": "assistant", "content": "Selected answer"},
        },
        {
            "uuid": "b",
            "parentUuid": "u",
            "type": "assistant",
            "message": {"role": "assistant", "content": "Other answer"},
        },
        {"type": "last-prompt", "leafUuid": "a", "sessionId": "c"},
    ]
    history = read_history("claude", write_log(tmp_path / "c.jsonl", rows))
    assert [e.text for e in history.entries] == ["Question", "Selected answer"]


def test_same_timestamp_turns_keep_source_order(tmp_path):
    rows = codex_rows(workspace=str(tmp_path))
    for index in range(12):
        rows.append(
            {
                "type": "response_item",
                "timestamp": STAMP,
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": f"question {index}"}],
                },
            }
        )
    path = write_log(tmp_path / "source/session.jsonl", rows)
    store = RuntimeThreadStore(tmp_path / "store")
    result = import_log(store, path)
    messages = reconstruct_messages_from_turns(store, result["thread_id"])
    assert [m.text_content() for m in messages if m.role == "user"] == ["Fix the bug"] + [
        f"question {i}" for i in range(12)
    ]


def test_unfinished_tools_stay_interrupted_and_do_not_seed_resume(tmp_path):
    path = write_log(tmp_path / "source/session.jsonl", codex_rows()[:4])
    store = RuntimeThreadStore(tmp_path / "store")
    result = import_log(store, path)
    turns = store.list_turns_for_thread(result["thread_id"])
    items = store.list_items_for_turn(turns[0].id)
    assert items[-1].status == "interrupted"
    messages = reconstruct_messages_from_turns(store, result["thread_id"])
    assert [message.text_content() for message in messages] == ["Fix the bug"]
    assert "unfinished_tools" in result["warnings"]


def test_native_forks_do_not_duplicate_import_scan(tmp_path):
    path = write_log(tmp_path / "source/session.jsonl", codex_rows())
    store = RuntimeThreadStore(tmp_path / "store")
    result = import_log(store, path)
    native = store.load_thread(result["thread_id"]).model_copy(update={"id": "thr_native_fork"})
    store.save_thread(native)
    assert len(scan_sessions(store, "codex", str(path.parent))["sessions"]) == 1


def test_codex_explicit_inheritance_updates_import_preserving_native_turns(tmp_path):
    from deepseek_tui.server.threads.models import RuntimeTurnStatus, TurnRecord

    root = tmp_path / "source"
    first = codex_rows()
    for index, row in enumerate(first):
        row["ordinal"] = index
        row["timestamp"] = STAMP
    parent_id = "11111111-1111-1111-1111-111111111111"
    path = write_log(root / f"rollout-{parent_id}.jsonl", first)
    store = RuntimeThreadStore(tmp_path / "store")
    result = import_log(store, path)
    thread = store.load_thread(result["thread_id"])
    # Preserve a conversation that was continued in this application.
    native = TurnRecord(
        id="native-follow-up",
        created_at="2026-09-03T12:00:00Z",
        thread_id=thread.id,
        status=RuntimeTurnStatus.COMPLETED,
        input_summary="local",
    )
    store.save_turn(native)
    thread.latest_turn_id = native.id
    store.save_thread(thread)
    later = codex_rows()
    for index, row in enumerate(later):
        row["ordinal"] = index + len(first)
        row["timestamp"] = "2026-09-02T12:00:00Z"
    later[2]["payload"]["content"][0]["text"] = "Next question"
    later[-1]["payload"]["content"][0]["text"] = "Next answer"
    later[0]["payload"]["history_base"] = {
        "thread_id": parent_id,
        "end_ordinal_exclusive": len(first),
        "end_byte_offset": path.stat().st_size,
    }
    write_log(root / "rollout-22222222-2222-2222-2222-222222222222.jsonl", later)
    scan = scan_sessions(store, "codex", str(root))
    assert not scan["errors"]
    assert len(scan["sessions"]) == 1
    assert scan["sessions"][0]["message_count"] == 4
    assert scan["sessions"][0]["update_available"]
    assert import_log(store, path)["status"] == "updated"
    turns = store.list_turns_for_thread(thread.id)
    items = [i for t in turns for i in store.list_items_for_turn(t.id)]
    assert [i.detail for i in items if i.kind.value == "user_message"] == [
        "Fix the bug",
        "Next question",
    ]
    assert len(items) == 6
    assert store.load_thread(thread.id).latest_turn_id == native.id
    assert import_log(store, path)["status"] == "skipped"
    assert not scan_sessions(store, "codex", str(root))["sessions"][0]["update_available"]


def test_repair_backs_up_replaced_source_history(tmp_path):
    path = write_log(tmp_path / "source/session.jsonl", codex_rows())
    store = RuntimeThreadStore(tmp_path / "store")
    result = import_log(store, path)
    before = {
        p: p.read_bytes()
        for d in ("threads", "turns", "items")
        for p in (tmp_path / "store" / d).glob("*.json")
    }
    rows = codex_rows()
    rows[2]["payload"]["content"][0]["text"] = "Changed old question"
    write_log(path, rows)
    updated = import_log(store, path)
    assert updated["status"] == "updated"
    from pathlib import Path

    backup = Path(updated["backup_path"])
    assert all(
        (backup / p.parent.name / p.name).read_bytes() == content for p, content in before.items()
    )
    assert store.load_thread(result["thread_id"])
    assert import_log(store, path)["status"] == "skipped"


def test_repair_failure_restores_existing_history(tmp_path, monkeypatch):
    path = write_log(tmp_path / "source/session.jsonl", codex_rows())
    store = RuntimeThreadStore(tmp_path / "store")
    result = import_log(store, path)
    before = {
        p: p.read_bytes()
        for d in ("threads", "turns", "items")
        for p in (tmp_path / "store" / d).glob("*.json")
    }
    more = codex_rows()[2:]
    more[0]["payload"]["content"][0]["text"] = "Next question"
    write_log(path, codex_rows() + more)
    original = store.save_thread
    failed = False

    def fail_once(thread):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("disk error")
        return original(thread)

    monkeypatch.setattr(store, "save_thread", fail_once)
    with pytest.raises(OSError, match="disk error"):
        import_log(store, path)
    after = {
        p: p.read_bytes()
        for d in ("threads", "turns", "items")
        for p in (tmp_path / "store" / d).glob("*.json")
    }
    assert before == after
    assert import_log(store, path)["status"] == "updated"
    assert store.load_thread(result["thread_id"])


def test_codex_mixed_old_and_new_turn_formats_keep_both(tmp_path):
    rows = codex_rows()
    rows.append({"type": "event_msg", "payload": {"type": "task_started"}, "timestamp": STAMP})
    for kind, text in [("UserMessage", "New question"), ("AgentMessage", "New answer")]:
        rows.append(
            {
                "type": "event_msg",
                "timestamp": STAMP,
                "payload": {
                    "type": "item_completed",
                    "item": {"type": kind, "content": [{"type": "text", "text": text}]},
                },
            }
        )
    history = read_history("codex", write_log(tmp_path / "s.jsonl", rows))
    assert [e.text for e in history.entries if e.kind in {"user_message", "agent_message"}] == [
        "Fix the bug",
        "Fixed",
        "New question",
        "New answer",
    ]


def test_corrupt_later_segment_never_imports_only_first_part(tmp_path):
    path = write_log(tmp_path / "source/first.jsonl", codex_rows())
    later = write_log(tmp_path / "source/second.jsonl", codex_rows())
    with later.open("a") as stream:
        stream.write("{broken}\n")
    store = RuntimeThreadStore(tmp_path / "store")
    scanned = scan_sessions(store, "codex", str(path.parent))
    assert not scanned["sessions"]
    assert len(scanned["errors"]) == 1
    with pytest.raises(ValueError):
        import_log(store, path)
    assert store.list_threads() == []


def test_codex_history_base_excludes_old_tail_and_other_branch(tmp_path):
    import sqlite3
    from collections import Counter

    root = tmp_path / "codex"
    a, b, c = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    ]
    first = codex_rows()
    for n, row in enumerate(first):
        row["ordinal"] = n
    parent = write_log(root / "sessions" / f"rollout-{a}.jsonl", first)
    boundary = parent.stat().st_size
    with parent.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "response_item",
                    "ordinal": len(first),
                    "payload": {"type": "message", "role": "user", "content": "Excluded old tail"},
                }
            )
            + "\n"
        )
    second = codex_rows()
    second[0]["payload"]["history_base"] = {
        "thread_id": a,
        "end_ordinal_exclusive": len(first),
        "end_byte_offset": boundary,
    }
    for n, row in enumerate(second):
        row["ordinal"] = n + len(first)
    second[2]["payload"]["content"][0]["text"] = "Selected continuation"
    head = write_log(root / "sessions" / f"rollout-{b}.jsonl", second)
    other = codex_rows()
    other[2]["payload"]["content"][0]["text"] = "Unselected branch"
    write_log(root / "sessions" / f"rollout-{c}.jsonl", other)
    with sqlite3.connect(root / "state_5.sqlite") as db:
        db.execute(
            "CREATE TABLE threads (id TEXT, title TEXT, archived INTEGER, rollout_path TEXT)"
        )
        db.execute(
            "INSERT INTO threads VALUES (?, ?, 0, ?)", ("session-1", "Indexed title", str(head))
        )
    store = RuntimeThreadStore(tmp_path / "store")
    scanned = scan_sessions(store, "codex", str(root))
    assert not scanned["errors"] and len(scanned["sessions"]) == 1
    assert scanned["sessions"][0]["path"] == str(head)
    result = import_session(
        store,
        source="codex",
        root=str(root),
        path=str(head),
        session_id="session-1",
        workspace=None,
        model="m",
        provider="p",
    )
    items = [
        i
        for t in store.list_turns_for_thread(result["thread_id"])
        for i in store.list_items_for_turn(t.id)
    ]
    assert [i.detail for i in items if i.kind.value == "user_message"] == [
        "Fix the bug",
        "Selected continuation",
    ]
    assert Counter(i.kind.value for i in items)["agent_message"] == 2
    parent.unlink()
    scanned = scan_sessions(store, "codex", str(root))
    assert scanned["errors"]
    with pytest.raises(ValueError, match="missing"):
        import_session(
            store,
            source="codex",
            root=str(root),
            path=str(head),
            session_id="session-1",
            workspace=None,
            model="m",
            provider="p",
        )


def test_same_id_files_without_lineage_or_index_are_not_concatenated(tmp_path):
    path = write_log(tmp_path / "source/a.jsonl", codex_rows())
    other = codex_rows()
    other[2]["payload"]["content"][0]["text"] = "Different branch"
    write_log(path.parent / "b.jsonl", other)
    store = RuntimeThreadStore(tmp_path / "store")
    assert scan_sessions(store, "codex", str(path.parent))["errors"]
    with pytest.raises(ValueError, match="Ambiguous"):
        import_log(store, path)
    assert not store.list_threads()


def test_claude_block_order_and_broken_parent_are_not_silently_lost(tmp_path):
    rows = [
        {
            "uuid": "u",
            "sessionId": "c",
            "type": "user",
            "message": {"role": "user", "content": "Question"},
        },
        {
            "uuid": "a",
            "sessionId": "c",
            "parentUuid": "u",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Reason"},
                    {"type": "text", "text": "Before"},
                    {"type": "tool_use", "id": "tool", "name": "Read", "input": {}},
                    {"type": "text", "text": "After"},
                ],
            },
        },
    ]
    path = write_log(tmp_path / "c.jsonl", rows)
    assert [e.kind for e in read_history("claude", path).entries] == [
        "user_message",
        "agent_reasoning",
        "agent_message",
        "tool_call",
        "agent_message",
    ]
    rows[1]["parentUuid"] = "missing"
    write_log(path, rows)
    with pytest.raises(ValueError, match="missing ancestor"):
        read_history("claude", path)
    rows[1]["parentUuid"] = "a"
    write_log(path, rows)
    with pytest.raises(ValueError, match="cyclic"):
        read_history("claude", path)


def test_uncommitted_import_generation_is_invisible(tmp_path):
    from deepseek_tui.server.threads.models import RuntimeTurnStatus, TurnRecord

    store = RuntimeThreadStore(tmp_path / "store")
    path = write_log(tmp_path / "source/s.jsonl", codex_rows())
    imported = import_log(store, path)
    thread_id = imported["thread_id"]
    staged = TurnRecord(
        id="staged",
        thread_id=thread_id,
        import_generation="not-committed",
        status=RuntimeTurnStatus.COMPLETED,
        input_summary="not visible",
        created_at=STAMP,
    )
    store.save_turn(staged)
    assert len(store.list_turns_for_thread(thread_id)) == 1
    assert store.count_turns_by_thread()[thread_id] == 1
    assert "staged" not in {t.id for t in store.iter_turns()}


async def test_imported_generation_remains_visible_after_native_fork(runtime_app, tmp_path):
    manager = runtime_app.state.thread_manager
    path = write_log(tmp_path / "source/s.jsonl", codex_rows(workspace=str(tmp_path)))
    result = import_log(manager.store, path)
    fork = await manager.fork_thread(result["thread_id"])
    assert len(manager.store.list_turns_for_thread(fork.id)) == 1
    messages = reconstruct_messages_from_turns(manager.store, fork.id)
    assert len(messages) == 3
    assert messages[0].text_content() == "Fix the bug"


@pytest.mark.parametrize(
    "base", ["invalid", {}, {"thread_id": "x", "end_ordinal_exclusive": -1, "end_byte_offset": 0}]
)
def test_invalid_codex_lineage_reports_scan_error(tmp_path, base):
    rows = codex_rows()
    rows[0]["payload"]["history_base"] = base
    path = write_log(tmp_path / "source/s.jsonl", rows)
    store = RuntimeThreadStore(tmp_path / "store")
    result = scan_sessions(store, "codex", str(path.parent))
    assert len(result["errors"]) == 1 and not result["sessions"]


def test_import_preserves_source_reply_phases(tmp_path):
    rows = codex_rows()
    rows[-1]["payload"]["phase"] = "final_answer"
    progress = json.loads(json.dumps(rows[-1]))
    progress["payload"]["phase"] = "commentary"
    progress["payload"]["content"][0]["text"] = "Checking data"
    rows.insert(3, progress)
    path = write_log(tmp_path / "source/s.jsonl", rows)
    store = RuntimeThreadStore(tmp_path / "store")
    result = import_log(store, path)
    messages = [
        item
        for turn in store.list_turns_for_thread(result["thread_id"])
        for item in store.list_items_for_turn(turn.id)
        if item.kind.value == "agent_message"
    ]
    assert [(item.detail, item.metadata["agent_segment"]) for item in messages] == [
        ("Checking data", "mid_turn_preface"),
        ("Fixed", "final_answer"),
    ]


def test_native_codex_phase_is_not_lost_in_conversion(tmp_path):
    from types import SimpleNamespace

    from deepseek_tui.server.external_sessions import load_history

    path = write_log(tmp_path / "s.jsonl", codex_rows())
    client = SimpleNamespace(
        read=lambda sid: (
            {"cwd": str(tmp_path)},
            [
                {
                    "id": "native-turn",
                    "startedAt": 1,
                    "items": [
                        {
                            "id": "u",
                            "type": "userMessage",
                            "content": [{"type": "text", "text": "Question"}],
                        },
                        {
                            "id": "a",
                            "type": "agentMessage",
                            "phase": "commentary",
                            "text": "Working",
                        },
                        {
                            "id": "b",
                            "type": "agentMessage",
                            "phase": "final_answer",
                            "text": "Answer",
                        },
                        {
                            "id": "c",
                            "type": "agentMessage",
                            "phase": None,
                            "text": "Unclassified reply",
                        },
                    ],
                }
            ],
        )
    )
    history = load_history("codex", path, [path], client)
    assert [entry.agent_segment for entry in history.entries] == [
        None,
        "mid_turn_preface",
        "final_answer",
        "final_answer",
    ]
