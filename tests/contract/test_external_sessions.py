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
