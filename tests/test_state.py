from __future__ import annotations

import json

from deepseek_tui.state.checkpoints import CheckpointRecord, CheckpointsStore
from deepseek_tui.state.database import Database
from deepseek_tui.state.jobs import JobRecord, JobsStore
from deepseek_tui.state.messages import MessagesStore, encode_content
from deepseek_tui.state.offline_queue import OfflineQueueRecord, OfflineQueueStore
from deepseek_tui.state.sessions import SessionRecord, SessionsStore
from deepseek_tui.state.threads import ThreadRecord, ThreadsStore


async def test_sessions_and_checkpoints_roundtrip(tmp_path) -> None:
    database = Database(tmp_path / "state.db")
    await database.initialize()

    sessions = SessionsStore(database)
    checkpoints = CheckpointsStore(database)
    offline_queue = OfflineQueueStore(database)
    threads = ThreadsStore(database)

    session = SessionRecord(
        id="session-1",
        title="Test Session",
        created_at="2026-05-04T00:00:00Z",
        updated_at="2026-05-04T00:00:00Z",
        transcript_json=json.dumps([{"role": "user", "content": "hello"}]),
    )
    await sessions.upsert(session)

    loaded_session = await sessions.get("session-1")
    assert loaded_session is not None
    assert loaded_session.transcript[0]["content"] == "hello"

    # Checkpoints now reference threads via FK, so create a thread first
    await threads.upsert(
        ThreadRecord(
            id="thread-cp",
            preview="cp-test",
            model_provider="m",
            cwd="/tmp",
            status="idle",
            created_at=1714780800,
            updated_at=1714780800,
        )
    )

    await checkpoints.save(
        CheckpointRecord(
            thread_id="thread-cp",
            checkpoint_id="cp-1",
            state_json=json.dumps({"messages": 1}),
            created_at=1714780860,
        )
    )

    latest_checkpoint = await checkpoints.load("thread-cp")
    assert latest_checkpoint is not None
    assert latest_checkpoint.checkpoint_id == "cp-1"

    loaded_checkpoints = await checkpoints.list_for_thread("thread-cp")
    assert len(loaded_checkpoints) == 1

    queue_id = await offline_queue.enqueue(
        OfflineQueueRecord(
            id=None,
            created_at="2026-05-04T00:02:00Z",
            payload_json=json.dumps({"kind": "request"}),
        )
    )
    pending_items = await offline_queue.list_pending()
    assert queue_id > 0
    assert len(pending_items) == 1
    assert pending_items[0].status == "pending"

    await offline_queue.mark_done(queue_id)
    assert await offline_queue.list_pending() == []

    await sessions.delete("session-1")
    assert await sessions.get("session-1") is None

    await database.close()


async def test_threads_messages_and_jobs_roundtrip(tmp_path) -> None:
    database = Database(tmp_path / "state.db")
    await database.initialize()

    threads = ThreadsStore(database)
    messages = MessagesStore(database)
    jobs = JobsStore(database)

    await threads.upsert(
        ThreadRecord(
            id="thread-1",
            preview="hello",
            model_provider="deepseek-v4-pro",
            cwd=str(tmp_path),
            status="idle",
            created_at=1714780800,
            updated_at=1714780800,
        )
    )
    loaded_thread = await threads.get("thread-1")
    assert loaded_thread is not None
    assert loaded_thread.preview == "hello"

    message_id = await messages.append(
        thread_id="thread-1",
        role="user",
        content=encode_content({"text": "hello"}),
        created_at=1714780860,
    )
    assert message_id > 0
    loaded_messages = await messages.list_for_thread("thread-1")
    assert json.loads(loaded_messages[0].content) == {"text": "hello"}

    await jobs.upsert(
        JobRecord(
            id="job-1",
            name="lint",
            status="running",
            progress=50,
            detail="ruff",
            created_at="2026-05-04T00:02:00Z",
            updated_at="2026-05-04T00:02:00Z",
        )
    )
    loaded_job = await jobs.get("job-1")
    assert loaded_job is not None
    assert loaded_job.progress == 50

    await threads.delete("thread-1")
    assert await messages.list_for_thread("thread-1") == []

    await database.close()
