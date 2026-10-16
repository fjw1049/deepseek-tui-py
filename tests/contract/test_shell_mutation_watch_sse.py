"""Turn receipts and restore include only this turn's tool and shell writes."""

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
from deepseek_tui.tools.file import ReadFileTool, WriteFileTool
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


@pytest.mark.parametrize("interference", ["none", "after", "between"])
# Shell writes are covered by test_shell_edit_emits_file_change_item: detection
# needs the pump gated on the pre-exec snapshot.
@pytest.mark.parametrize("writer", ["file_tool", "subagent", "external"])
@pytest.mark.asyncio
async def test_only_reported_writes_enter_turn_receipt_and_restore(
    runtime_app: object,
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
    interference: str,
) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    # The turn completes with tool evidence but no final answer; skip the
    # LLM-based recovery so the test stays hermetic.
    monkeypatch.setattr(
        manager, "_recover_missing_final_answer", AsyncMock(return_value=None)
    )
    handle = EngineHandle()
    (git_repo / "other.py").write_text("original\n", encoding="utf-8")
    _git(git_repo, "add", "other.py")
    _git(git_repo, "commit", "-m", "other editor's file")
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

    reported = writer in {"file_tool", "subagent"}
    tool = ToolCall(
        id="tc_write",
        name="write_file" if reported else "exec_shell",
        arguments=(
            {"path": "tracked.py", "content": "v2\n"}
            if reported else {"command": "git apply /tmp/x.patch"}
        ),
    )
    ready = asyncio.get_running_loop().create_future()

    async def pump() -> None:
        await asyncio.wait_for(asyncio.shield(ready), timeout=5)
        if writer != "external":
            await handle.emit(ToolCallEvent(tool_call=tool))
        metadata = {}
        if reported:
            context = stub_engine.tool_context
            if writer == "subagent":
                context = ToolContext(
                    working_directory=git_repo,
                    on_file_mutation=context.on_file_mutation,
                    mutation_agent_id="agent_child",
                )
            result = await WriteFileTool().execute(tool.arguments, context)
            metadata = result.metadata
        else:
            (git_repo / "tracked.py").write_text("v2\n", encoding="utf-8")
        if reported and interference != "none":
            (git_repo / "tracked.py").write_text("v2\nCODEX edit\n", encoding="utf-8")
            if interference == "between":
                await ReadFileTool().execute({"path": "tracked.py"}, context)
                result = await WriteFileTool().execute(
                    {"path": "tracked.py", "content": "v3\nCODEX edit\n"}, context
                )
                metadata = result.metadata
        # Another editor changes tracked and untracked files during this turn.
        (git_repo / "other.py").write_text("external edit\n", encoding="utf-8")
        (git_repo / "external.py").write_text("external creation\n", encoding="utf-8")
        if writer != "external":
            await handle.emit(
                ToolResultEvent(
                    tool_call_id=tool.id,
                    tool_name=tool.name,
                    content="ok",
                    success=True,
                    metadata=metadata,
                )
            )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent", ready)
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    events = manager.events_since(thread.id, 0)
    final_diffs = [
        e.payload for e in events
        if e.event == "turn.diff.updated" and e.payload.get("complete")
    ]
    assert len(final_diffs) == 1
    expected = ["tracked.py"] if reported else []
    assert [f["path"] for f in final_diffs[0]["files"]] == expected
    assert final_diffs[0]["totals"]["files"] == len(expected)
    persisted = manager.store.load_turn(turn_id).diff_snapshot
    assert persisted == final_diffs[0]
    assert manager.checkpoints.load(turn_id).mutated == expected
    restored = await manager.checkpoints.restore([turn_id], git_repo)
    if reported and interference != "none":
        assert restored.conflicted == ["tracked.py"]
        assert restored.restored == []
        assert "+CODEX edit" not in final_diffs[0]["merged_unified_diff"]
        assert (git_repo / "tracked.py").read_text() == (
            "v3\nCODEX edit\n" if interference == "between" else "v2\nCODEX edit\n"
        )
    else:
        assert restored.restored == expected
        assert (git_repo / "tracked.py").read_text() == ("v1\n" if reported else "v2\n")
    assert (git_repo / "other.py").read_text() == "external edit\n"
    assert (git_repo / "external.py").read_text() == "external creation\n"


@pytest.mark.parametrize("real_shell", [False, True])
@pytest.mark.asyncio
async def test_shell_edit_emits_file_change_item(
    real_shell: bool,
    runtime_app: object,
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (git_repo / "scratch").mkdir()
    _git(git_repo, "mv", "tracked.py", "scratch/tracked.py")
    _git(git_repo, "commit", "-m", "move fixture to shell allowlist")
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

    tool = ToolCall(
        id="tc_shell",
        name="exec_shell",
        arguments={"command": "printf 'v2\n' > scratch/tracked.py"},
    )
    from deepseek_tui.tools.shell import ExecShellTool
    from deepseek_tui.tools.registry import ToolResult

    ready = asyncio.get_running_loop().create_future()

    async def fast_command(self, input_data, context):
        # No await: the edit can finish before the monitor consumes ToolCallEvent.
        (git_repo / "scratch/tracked.py").write_text("v2\n", encoding="utf-8")
        return ToolResult(success=True, content="patch applied ok")

    if not real_shell:
        monkeypatch.setattr(ExecShellTool, "_execute", fast_command)

    async def pump() -> None:
        await ready
        await handle.emit(ToolCallEvent(tool_call=tool))
        result = await ExecShellTool().execute(tool.arguments, stub_engine.tool_context)
        assert result.success, result.content
        await handle.emit(
            ToolResultEvent(
                tool_call_id="tc_shell",
                tool_name="exec_shell",
                content=result.content,
                success=result.success,
                metadata=result.metadata,
            )
        )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent", ready)
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    events = manager.events_since(thread.id, 0)
    completed = [
        e for e in events
        if e.event == "item.completed" and e.payload["item"]["kind"] == "file_change"
    ]
    assert len(completed) == 1
    mutation = completed[0].payload["item"]["metadata"]["mutation"]
    assert mutation["source"] == "shell_detected"
    assert mutation["path"] == "scratch/tracked.py"
    assert "+v2" in mutation["unified_diff"]
    final_diffs = [
        e.payload for e in events
        if e.event == "turn.diff.updated" and e.payload.get("complete")
    ]
    assert [f["path"] for f in final_diffs[0]["files"]] == ["scratch/tracked.py"]

    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint.mutated == ["scratch/tracked.py"]
    assert checkpoint.uncertain == ["scratch/tracked.py"]
    # An unchanged post-image does not prove that the command wrote it.
    # The same disk delta could be a user saving while a read-only command runs.
    report = await manager.checkpoints.restore([turn_id], git_repo)
    assert report.conflicted == ["scratch/tracked.py"]
    assert (git_repo / "scratch/tracked.py").read_text() == "v2\n"
    drifted, _ = await manager._checkpoint_post_state(git_repo, [checkpoint])
    assert drifted == ["scratch/tracked.py"]
    # A later edit is never merged into a shell-detected path...
    (git_repo / "scratch/tracked.py").write_text("v2\nlater edit\n", encoding="utf-8")
    report = await manager.checkpoints.restore([turn_id], git_repo)
    assert report.conflicted == ["scratch/tracked.py"]
    assert (git_repo / "scratch/tracked.py").read_text() == "v2\nlater edit\n"
    # ...but the user can confirm the overwrite.
    report = await manager.checkpoints.restore([turn_id], git_repo, force=True)
    assert report.restored == ["scratch/tracked.py"]
    assert (git_repo / "scratch/tracked.py").read_text() == "v1\n"


@pytest.mark.asyncio
async def test_publish_does_not_claim_interleaved_external_write(runtime_app, git_repo):
    manager = runtime_app.state.thread_manager
    store = manager.checkpoints
    store.begin_turn("turn_publish_ownership", None, head=None, is_git=True,
                     execution_root=str(git_repo), tool_writes_only=True)
    store.record_tool_write("turn_publish_ownership", "tracked.py", "v1\n", "v2\n")
    (git_repo / "tracked.py").write_text("v2\nCODEX edit\n")
    store.record_post_images("turn_publish_ownership", git_repo)
    checkpoint = store.load("turn_publish_ownership")
    drifted, _ = await manager._checkpoint_post_state(git_repo, [checkpoint])
    assert drifted == ["tracked.py"]


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_shell_captures_edits_before_failure_or_cancellation(git_repo, monkeypatch, failure):
    from deepseek_tui.tools.shell import ExecShellTool

    changes = []
    context = ToolContext(working_directory=git_repo, on_file_mutation=changes.append)
    async def command(self, input_data, ctx):
        (git_repo / "tracked.py").write_text("changed before failure\n")
        raise failure()
    monkeypatch.setattr(ExecShellTool, "_execute", command)
    with pytest.raises(failure):
        await ExecShellTool().execute({"command": "patch"}, context)
    assert len(changes) == 1
    assert changes[0]["_before_content"] == "v1\n"
    assert changes[0]["_after_content"] == "changed before failure\n"


async def test_shell_does_not_claim_another_active_turns_files(git_repo, monkeypatch):
    from deepseek_tui.tools.shell import ExecShellTool
    from deepseek_tui.tools.registry import ToolResult

    changes = []
    context = ToolContext(working_directory=git_repo, on_file_mutation=changes.append)
    context.metadata["shell_mutation_skip_paths"] = AsyncMock(return_value={"tracked.py"})
    async def command(self, input_data, ctx):
        (git_repo / "tracked.py").write_text("other turn's edit\n")
        return ToolResult(success=True, content="done")
    monkeypatch.setattr(ExecShellTool, "_execute", command)
    result = await ExecShellTool().execute({"command": "sleep 1"}, context)
    assert changes == []
    assert not result.metadata.get("shell_mutations")
