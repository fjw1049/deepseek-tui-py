"""Shell-mutation watch SSE contract: shell edits surface as file_change items."""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import deepseek_tui.workspace.shell_mutation_watch as shell_mutation_watch
from deepseek_tui.engine.events import (
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnRecord,
    _ActiveThreadState,
)
from deepseek_tui.tools.registry import ToolContext


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "tracked.py").write_text("v1\n", encoding="utf-8")
    _git(root, "add", "tracked.py")
    _git(root, "commit", "-m", "init")
    return root


@pytest.mark.asyncio
async def test_monitor_signals_ready_only_after_checkpoint_exists(
    runtime_app: object,
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    monkeypatch.setattr(
        manager, "_recover_missing_final_answer", AsyncMock(return_value=None)
    )
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="test",
            created_at=now,
            started_at=now,
        )
    )
    stub_engine = SimpleNamespace(
        tool_context=ToolContext(working_directory=git_repo)
    )
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)

    capture_started = asyncio.Event()
    release_capture = asyncio.Event()
    real_capture = shell_mutation_watch.capture_shell_snapshot

    async def _capture_gate(
        workspace: Path,
    ) -> shell_mutation_watch.ShellMutationSnapshot:
        capture_started.set()
        await release_capture.wait()
        return await real_capture(workspace)

    monkeypatch.setattr(
        shell_mutation_watch, "capture_shell_snapshot", _capture_gate
    )
    ready = asyncio.get_running_loop().create_future()
    monitor = asyncio.create_task(
        manager._monitor_turn(thread.id, turn_id, handle, "agent", ready)
    )
    try:
        await asyncio.wait_for(capture_started.wait(), timeout=5)
        assert not ready.done()
        assert manager.checkpoints.load(turn_id) is None

        release_capture.set()
        await asyncio.wait_for(asyncio.shield(ready), timeout=5)
        checkpoint = manager.checkpoints.load(turn_id)
        assert checkpoint is not None
        assert checkpoint.thread_id == thread.id

        await handle.emit(TurnCompleteEvent(assistant_message=None))
        await asyncio.wait_for(monitor, timeout=5)
    finally:
        if not monitor.done():
            monitor.cancel()
            with pytest.raises(asyncio.CancelledError):
                await monitor
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)


@pytest.mark.asyncio
async def test_shell_edit_emits_file_change_item(
    runtime_app: object,
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    # The turn completes with tool evidence but no final answer; skip the
    # LLM-based recovery so the test stays hermetic.
    monkeypatch.setattr(
        manager, "_recover_missing_final_answer", AsyncMock(return_value=None)
    )
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="test",
            created_at=now,
            started_at=now,
        )
    )

    stub_engine = SimpleNamespace(
        tool_context=ToolContext(working_directory=git_repo)
    )
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)

    tool = ToolCall(
        id="tc_shell",
        name="exec_shell",
        arguments={"command": "git apply /tmp/x.patch"},
    )

    # handle.emit only queues — without this gate the pump could write the
    # file before _monitor_turn takes its pre-exec snapshot, and there would
    # be no delta left to detect. The first capture is _monitor_turn's
    # turn-start snapshot (rewind file checkpoints); the pre-exec snapshot
    # for the shell command is the second one.
    captured = asyncio.Event()
    capture_calls = 0
    real_capture = shell_mutation_watch.capture_shell_snapshot

    async def _capture_spy(
        workspace: Path,
    ) -> shell_mutation_watch.ShellMutationSnapshot:
        nonlocal capture_calls
        try:
            return await real_capture(workspace)
        finally:
            capture_calls += 1
            if capture_calls >= 2:
                captured.set()

    monkeypatch.setattr(
        shell_mutation_watch, "capture_shell_snapshot", _capture_spy
    )

    async def pump() -> None:
        await handle.emit(ToolCallEvent(tool_call=tool))
        await asyncio.wait_for(captured.wait(), timeout=5)
        # The shell command edits the file behind the tool layer.
        (git_repo / "tracked.py").write_text("v2\n", encoding="utf-8")
        await handle.emit(
            ToolResultEvent(
                tool_call_id="tc_shell",
                tool_name="exec_shell",
                content="patch applied ok",
                success=True,
            )
        )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent")
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    events = manager.events_since(thread.id, 0)
    started = {
        e.item_id: e
        for e in events
        if e.event == "item.started" and e.payload["item"]["kind"] == "file_change"
    }
    completed = {
        e.item_id: e
        for e in events
        if e.event == "item.completed" and e.payload["item"]["kind"] == "file_change"
    }
    assert set(started) == set(completed)
    assert len(completed) == 1
    first_diff_seq = min(e.seq for e in events if e.event == "turn.diff.updated")
    assert first_diff_seq < next(iter(completed.values())).seq

    item = next(iter(completed.values())).payload["item"]
    mutation = item["metadata"]["mutation"]
    assert mutation["source"] == "shell_detected"
    assert mutation["path"] == "tracked.py"
    assert mutation["op"] == "update"
    assert mutation["line_start"] == 1
    assert "+v2" in mutation["unified_diff"]
    assert item["detail"] == mutation["unified_diff"]
    # The synthetic row is attributed to the originating shell call.
    start_payload = next(iter(started.values())).payload
    assert start_payload["tool"] == {
        "id": "tc_shell",
        "name": "exec_shell",
        "input": {"command": "git apply /tmp/x.patch"},
    }

    # The mutation entered the turn ledger; turn-end git reconcile must not
    # count the covered path a second time.
    final_diffs = [
        e.payload for e in events
        if e.event == "turn.diff.updated" and e.payload.get("complete")
    ]
    assert len(final_diffs) == 1
    assert [f["path"] for f in final_diffs[0]["files"]] == ["tracked.py"]
    assert final_diffs[0]["totals"]["files"] == 1
    persisted = manager.store.load_turn(turn_id).diff_snapshot
    assert persisted == final_diffs[0]
