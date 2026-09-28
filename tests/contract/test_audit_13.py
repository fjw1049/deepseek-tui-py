"""Fault and concurrency regressions for audit 13."""

import asyncio
import json
import os
import zipfile
from pathlib import Path

import pytest

from deepseek_tui.server.threads.store import RuntimeThreadStore


async def test_sequence_survives_restart_and_multiple_stores(tmp_path):
    first = RuntimeThreadStore(tmp_path)
    a = await first.append_event("thread", None, None, "text.delta", {"delta": "a"})
    second = RuntimeThreadStore(tmp_path)
    records = await asyncio.gather(
        *[
            (first if i % 2 else second).append_event(
                "thread", None, None, "text.delta", {"delta": str(i)}
            )
            for i in range(30)
        ]
    )
    assert min(r.seq for r in records) > a.seq
    assert len({r.seq for r in records}) == 30
    persisted = first.events_since("thread")
    assert [r.seq for r in persisted] == sorted(r.seq for r in persisted)
    await first.flush_event_checkpoint()
    assert await second.current_seq() == max(r.seq for r in records)


async def test_legacy_highwater_and_full_delta(tmp_path):
    store = RuntimeThreadStore(tmp_path)
    payload = {"delta": "中文" * 3000}
    record = await store.append_event("thread", None, None, "text.delta", payload)
    (tmp_path / "state.json").write_text('{"next_seq":1}')
    reopened = RuntimeThreadStore(tmp_path)
    assert (
        await reopened.append_event("thread", None, None, "text.delta", payload)
    ).seq > record.seq
    assert store.events_since("thread")[0].payload == payload


@pytest.mark.parametrize(
    "bad", ["../outside", "/absolute", "a/b", "a\\b", ".", "..", "", "C:drive", "a\0b"]
)
def test_record_path_rejects_escape(tmp_path, bad):
    store = RuntimeThreadStore(tmp_path)
    for helper in (
        store._thread_path,
        store._turn_path,
        store._item_path,
        store._events_path,
        store._worktree_baseline_path,
        store._rewind_audit_path,
    ):
        with pytest.raises(ValueError):
            helper(bad)


async def test_batch_failure_preserves_unsent_and_concurrent_text():
    from deepseek_tui.server.metrics import TurnDeltaBatcher

    sent = []
    fail = True

    async def emit(thread, turn, item, kind, payload):
        nonlocal fail
        if item == "b" and fail:
            fail = False
            await batch.append("b", kind, "new")
            raise OSError("disk full")
        sent.append((item, payload["delta"]))

    batch = TurnDeltaBatcher("thread", "turn", emit)
    for key in ("a", "b", "c"):
        await batch.append(key, "text.delta", key)
    with pytest.raises(OSError):
        await batch.flush()
    await batch.flush()
    assert sent == [("a", "a"), ("b", "bnew"), ("c", "c")]


def test_usage_lock_does_not_steal_live_holder(tmp_path):
    from deepseek_tui.server.workbench_usage_ledger import _ledger_file_lock, _lock_path

    path = tmp_path / "ledger.json"
    with _ledger_file_lock(path):
        os.utime(_lock_path(path), (1, 1))
        with pytest.raises(TimeoutError):
            with _ledger_file_lock(path, timeout=0.01):
                pytest.fail("stole live lock")
    with _ledger_file_lock(path, timeout=0.01):
        pass


async def test_broadcast_filter_and_overflow_replay(tmp_path):
    from types import SimpleNamespace

    from deepseek_tui.server.routes import stream_thread_events
    from deepseek_tui.server.threads.broadcast import AsyncBroadcast

    store = RuntimeThreadStore(tmp_path)
    bus = AsyncBroadcast(capacity=1)
    manager = SimpleNamespace(
        store=store, subscribe_events=bus.subscribe, events_since=store.events_since, event_bus=bus
    )
    stream = stream_thread_events(manager, "a", heartbeat_seconds=0.001)
    assert await anext(stream) == ": keepalive\n\n"
    for thread, delta in [("a", "first"), ("b", "other"), ("a", "second")]:
        bus.send(await store.append_event(thread, None, None, "text.delta", {"delta": delta}))
    assert "first" in await anext(stream)
    assert "second" in await anext(stream)
    await stream.aclose()
    assert bus.receiver_count == 0


def test_invalid_replace_bundle_preserves_existing(tmp_path):
    from deepseek_tui.server.data_bundle import BUNDLE_FORMAT, import_bundle

    root = tmp_path / "store"
    root.mkdir()
    sentinel = root / "keep.txt"
    sentinel.write_text("original")
    bundle = tmp_path / "bad.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"format": BUNDLE_FORMAT, "version": 1, "includes": {"threads": True}}),
        )
    with pytest.raises(ValueError, match="missing threads"):
        import_bundle(
            bundle,
            mode="replace",
            threads_dir=root,
            sessions_dir=tmp_path / "sessions",
            import_settings=False,
        )
    assert sentinel.read_text() == "original"


def test_import_publish_failure_rolls_back_all_roots(tmp_path, monkeypatch):
    from deepseek_tui.server.data_bundle import _staged_import

    first, second = tmp_path / "first", tmp_path / "second"
    for path in (first, second):
        path.mkdir()
        (path / "value").write_text("old")
    rename = Path.rename

    def fail_second_publish(self, target):
        if (
            target == second
            and self.parent.name.startswith(".deepseek-import-")
            and self.name == "second"
        ):
            raise OSError("publish failed")
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_second_publish)
    with pytest.raises(OSError, match="publish failed"):
        with _staged_import([first, second]) as staged:
            for path in staged.values():
                (path / "value").write_text("new")
    assert [(p / "value").read_text() for p in (first, second)] == ["old", "old"]


def test_export_rejects_symlink_and_cleans_temp(tmp_path):
    from deepseek_tui.server.data_bundle import export_bundle

    root = tmp_path / "store"
    root.mkdir()
    secret = tmp_path / "secret"
    secret.write_text("private")
    (root / "escape").symlink_to(secret)
    with pytest.raises(ValueError, match="symlink"):
        export_bundle(tmp_path / "out.zip", threads_dir=root, sessions_dir=tmp_path / "sessions")
    assert not (tmp_path / "out.zip").exists()
    assert not list(tmp_path.glob(".out.zip.*"))


@pytest.mark.parametrize("name", ["../escape", "a\\b", "C:drive"])
def test_archive_rejects_unsafe_paths(tmp_path, name):
    from deepseek_tui.server.data_bundle import _safe_extract

    bundle = tmp_path / "bad.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(name, "bad")
    with zipfile.ZipFile(bundle) as archive, pytest.raises(ValueError):
        _safe_extract(archive, tmp_path / "unpacked")


def test_archive_size_limit(tmp_path, monkeypatch):
    from deepseek_tui.server import data_bundle

    monkeypatch.setattr(data_bundle, "MAX_ARCHIVE_MEMBER_BYTES", 5)
    bundle = tmp_path / "big.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large", "x" * 1000)
    with zipfile.ZipFile(bundle) as archive, pytest.raises(ValueError, match="size limit"):
        data_bundle._safe_extract(archive, tmp_path / "unpacked")


async def test_mutation_finishes_before_repeated_cancellation_returns():
    from deepseek_tui.server.lifecycle import complete_before_cancel

    started, finish = asyncio.Event(), asyncio.Event()
    completed = []

    async def mutation():
        started.set()
        await finish.wait()
        completed.append(True)

    caller = asyncio.create_task(complete_before_cancel(mutation()))
    await started.wait()
    caller.cancel()
    await asyncio.sleep(0)
    caller.cancel()
    await asyncio.sleep(0)
    assert not caller.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert completed == [True]


async def test_shutdown_waits_for_mutation_and_client_close(runtime_app):
    mgr = runtime_app.state.thread_manager
    started, finish = asyncio.Event(), asyncio.Event()
    actions = []

    async def mutation():
        started.set()
        await finish.wait()
        actions.append("mutation")

    class Client:
        async def close(self):
            await asyncio.sleep(0)
            actions.append("close")

    mgr._provider_clients["test"] = Client()
    pending = asyncio.create_task(mgr._complete_mutation(mutation()))
    await started.wait()
    closing = asyncio.create_task(mgr.aclose())
    await asyncio.sleep(0)
    assert not closing.done()
    finish.set()
    await pending
    await closing
    await mgr.aclose()
    assert actions == ["mutation", "close"]
    assert not mgr._mutation_tasks
    assert not mgr._thread_leases


async def test_shutdown_rejects_load_waiting_for_active_lock(runtime_app):
    from types import SimpleNamespace

    mgr = runtime_app.state.thread_manager
    async with mgr._active_lock:
        pending = asyncio.create_task(mgr._ensure_engine_loaded(SimpleNamespace(id="late")))
        await asyncio.sleep(0)
        mgr.shutdown()
    with pytest.raises(RuntimeError, match="shutting down"):
        await pending
    await mgr.aclose()
    assert "late" not in mgr._engine_load_tasks
    assert "late" not in mgr._active


async def test_shutdown_drains_shielded_engine_load(runtime_app, monkeypatch):
    from types import SimpleNamespace

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.server.threads.manager import _ActiveThreadState

    mgr = runtime_app.state.thread_manager
    started, finish = asyncio.Event(), asyncio.Event()
    closed = []
    handle = EngineHandle()

    async def engine_run():
        await asyncio.Event().wait()

    async def shutdown_session():
        closed.append(True)

    async def build(thread):
        started.set()
        await finish.wait()
        task = asyncio.create_task(engine_run())
        mgr._active[thread.id] = _ActiveThreadState(
            handle, SimpleNamespace(shutdown_session=shutdown_session), task
        )
        return handle, task

    monkeypatch.setattr(mgr, "_build_engine_for_thread", build)
    pending = asyncio.create_task(mgr._ensure_engine_loaded(SimpleNamespace(id="loading")))
    await started.wait()
    closing = asyncio.create_task(mgr.aclose())
    await asyncio.sleep(0)
    assert not closing.done()
    finish.set()
    await closing
    assert closed == [True]
    assert not mgr._active
    assert not mgr._engine_load_tasks
    assert pending.done()


async def test_restore_service_finishes_bookkeeping_on_cancel(runtime_app, monkeypatch):
    mgr = runtime_app.state.thread_manager
    restored, proceed = asyncio.Event(), asyncio.Event()
    actions = []

    async def restore(*args, **kwargs):
        actions.append("files")
        restored.set()
        await proceed.wait()
        actions.extend(["isolate_sync", "consume_checkpoint", "update_thread"])
        return {}

    monkeypatch.setattr(mgr, "_restore_code", restore)
    caller = asyncio.create_task(mgr.restore_code("thread", before_item_id="item"))
    await restored.wait()
    caller.cancel()
    await asyncio.sleep(0)
    assert not caller.done()
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert actions == ["files", "isolate_sync", "consume_checkpoint", "update_thread"]
    assert not mgr._mutation_tasks
    await mgr.aclose()


async def test_shutdown_drains_monitor_before_closing_engine(runtime_app):
    from types import SimpleNamespace

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.server.threads.manager import _ActiveThreadState

    mgr = runtime_app.state.thread_manager
    handle = EngineHandle()
    actions = []

    async def engine_run():
        await asyncio.Event().wait()

    async def session_close():
        actions.append("session_close")

    async def monitor():
        async for _event in handle.events():
            if mgr.is_shutdown:
                await asyncio.sleep(0)
                actions.append("turn_finalized")
                return

    state = _ActiveThreadState(
        handle, SimpleNamespace(shutdown_session=session_close), asyncio.create_task(engine_run())
    )
    mgr._active["thread"] = state
    task = asyncio.create_task(monitor())
    mgr._monitor_tasks.add(task)
    task.add_done_callback(mgr._monitor_tasks.discard)
    await mgr.aclose()
    assert actions == ["turn_finalized", "session_close"]
    assert state.engine_task.done()
    assert task.done()


async def test_batch_cancellation_does_not_duplicate_acknowledged_emit():
    from deepseek_tui.server.metrics import TurnDeltaBatcher

    started, finish = asyncio.Event(), asyncio.Event()
    sent = []

    async def emit(*args):
        started.set()
        await finish.wait()
        sent.append(args[-1]["delta"])

    batch = TurnDeltaBatcher("thread", "turn", emit)
    await batch.append("item", "text.delta", "once")
    caller = asyncio.create_task(batch.flush())
    await started.wait()
    caller.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert await batch.flush() == 0
    assert sent == ["once"]


async def test_cross_process_sequence_allocation(tmp_path):
    import subprocess
    import sys

    script = """
import asyncio, sys
from pathlib import Path
from deepseek_tui.server.threads.store import RuntimeThreadStore
async def main():
    store = RuntimeThreadStore(Path(sys.argv[1]))
    for i in range(15):
        await store.append_event('thread', None, None, 'test', {'i':i})
asyncio.run(main())
"""

    def run():
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)],
            env={**os.environ, "PYTHONPATH": "src"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

    await asyncio.gather(asyncio.to_thread(run), asyncio.to_thread(run))
    store = RuntimeThreadStore(tmp_path)
    seqs = [event.seq for event in store.events_since("thread")]
    assert len(seqs) == len(set(seqs)) == 30
    assert seqs == sorted(seqs)


async def test_torn_log_does_not_swallow_next_event(tmp_path):
    store = RuntimeThreadStore(tmp_path)
    store._events_path("thread").write_text('{"broken":')
    record = await store.append_event("thread", None, None, "test", {})
    assert [e.seq for e in store.events_since("thread")] == [record.seq]


async def test_leaf_symlink_cannot_receive_event_append(tmp_path):
    store = RuntimeThreadStore(tmp_path / "store")
    outside = tmp_path / "outside"
    outside.write_text("original")
    store._events_path("thread").symlink_to(outside)
    with pytest.raises(ValueError, match="Symlink"):
        await store.append_event("thread", None, None, "test", {})
    assert outside.read_text() == "original"


async def test_overflow_with_compacted_history_requests_resync(tmp_path):
    from types import SimpleNamespace

    from deepseek_tui.server.routes import stream_thread_events
    from deepseek_tui.server.threads.broadcast import AsyncBroadcast

    store = RuntimeThreadStore(tmp_path)
    bus = AsyncBroadcast(capacity=1)
    mgr = SimpleNamespace(store=store, subscribe_events=bus.subscribe, event_bus=bus)
    stream = stream_thread_events(mgr, "thread", heartbeat_seconds=0.001)
    await anext(stream)
    lost = await store.append_event("thread", None, None, "text.delta", {"delta": "lost"})
    bus.send(lost)
    store.delete_events("thread")
    next_event = await store.append_event("thread", None, None, "test", {})
    bus.send(next_event)
    frame = await anext(stream)
    assert "stream.resync_required" in frame
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert bus.receiver_count == 0


async def test_runtime_cleanup_continues_after_one_resource_fails(runtime_app):
    from types import SimpleNamespace

    runtime = runtime_app.state.runtime
    actions = []

    async def hook_close():
        actions.append("hooks")
        raise OSError("hook close failed")

    async def tools_close():
        actions.append("tools")

    async def sink_close():
        actions.append("sink")

    runtime._direct_hook_executor = SimpleNamespace(close=hook_close)
    runtime._tool_runtime = SimpleNamespace(shutdown=tools_close)
    runtime.hooks = SimpleNamespace(sinks=[SimpleNamespace(close=sink_close)])
    with pytest.raises(OSError, match="hook close failed"):
        await runtime.shutdown()
    assert actions == ["hooks", "tools", "sink"]


def test_import_refuses_live_thread(tmp_path, runtime_app):
    from datetime import datetime, timezone

    from deepseek_tui.server.data_bundle import export_bundle, import_bundle
    from deepseek_tui.server.threads.models import ThreadRecord
    from deepseek_tui.workspace.project_lease import ThreadLease

    store = runtime_app.state.thread_manager.store
    now = datetime.now(timezone.utc)
    thread = ThreadRecord(
        id="busy",
        title="test",
        model="deepseek-chat",
        workspace=str(tmp_path),
        created_at=now,
        updated_at=now,
    )
    store.save_thread(thread)
    bundle = tmp_path / "bundle.zip"
    sessions = tmp_path / "sessions"
    export_bundle(bundle, threads_dir=store.root, sessions_dir=sessions)
    before = store._thread_path("busy").read_bytes()
    lease = ThreadLease("busy")
    lease.acquire_blocking()
    try:
        with pytest.raises(ValueError, match="active"):
            import_bundle(
                bundle,
                mode="replace",
                threads_dir=store.root,
                sessions_dir=sessions,
                import_settings=False,
            )
    finally:
        lease.release()
    assert store._thread_path("busy").read_bytes() == before


async def test_legacy_truncated_replay_requests_snapshot(tmp_path):
    from types import SimpleNamespace

    from deepseek_tui.server.routes import stream_thread_events
    from deepseek_tui.server.threads.broadcast import AsyncBroadcast

    store = RuntimeThreadStore(tmp_path)
    await store.append_event("thread", None, None, "response.delta", {"_truncated": True})
    bus = AsyncBroadcast()
    mgr = SimpleNamespace(store=store, subscribe_events=bus.subscribe, event_bus=bus)
    stream = stream_thread_events(mgr, "thread")
    assert "legacy_truncated_payload" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert bus.receiver_count == 0
