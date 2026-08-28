from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.server.threads.manager import _ActiveThreadState
from deepseek_tui.server.threads.models import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    StartTurnRequest,
    TurnRecord,
    UpdateThreadRequest,
)
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.workspace.execution import execution_root, project_root
from deepseek_tui.workspace.managed_worktree import planned_worktree_path
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpoint


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "init")
    return repo


def _seed_turn(manager, thread_id: str, turn_id: str) -> None:
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="edit",
            created_at=now,
            started_at=now,
            ended_at=now,
        )
    )


@pytest.mark.asyncio
async def test_start_turn_never_dispatches_without_checkpoint(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    handle = EngineHandle()
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")

    async def fake_ensure(live_thread, *, trace=None):
        del trace
        engine = SimpleNamespace(
            mode="agent",
            tool_context=ToolContext(working_directory=execution_root(live_thread)),
        )
        async with manager._active_lock:
            manager._active[live_thread.id] = _ActiveThreadState(
                handle, engine, engine_task, provider=live_thread.provider
            )
        return handle, engine_task

    def fail_checkpoint(*args, **kwargs):
        del args, kwargs
        raise OSError("checkpoint disk unavailable")

    monkeypatch.setattr(manager, "_ensure_engine_loaded", fake_ensure)
    monkeypatch.setattr(manager.checkpoints, "begin_turn", fail_checkpoint)

    try:
        with pytest.raises(RuntimeError, match="checkpoint initialization failed"):
            await manager.start_turn(thread.id, StartTurnRequest(prompt="edit app.py"))

        assert handle._op_queue.empty()
        turns = manager.store.list_turns_for_thread(thread.id)
        assert len(turns) == 1
        assert turns[0].status == RuntimeTurnStatus.FAILED
        assert "initialization failed" in (turns[0].error or "")
        assert thread.id not in manager._thread_leases
    finally:
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)


@pytest.mark.asyncio
async def test_prepare_isolates_git_and_publish_writes_project(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    assert thread.env_mode == "local"
    prepared = await manager._prepare_isolated_workspace(thread)
    assert prepared.env_mode == "worktree"
    tree = execution_root(prepared)
    assert tree != project_root(prepared)
    assert (tree / "app.py").read_text(encoding="utf-8") == "one\n"
    (tree / "app.py").write_text("two\n", encoding="utf-8")
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"

    turn_id = "turn_pub1"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "two\n"},
        )
    )
    published = await manager._publish_isolated_thread(prepared)
    assert published.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "two\n"
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == repo.resolve()


@pytest.mark.asyncio
async def test_publish_conflict_leaves_project(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("from-agent\n", encoding="utf-8")
    (repo / "app.py").write_text("from-claude\n", encoding="utf-8")
    turn_id = "turn_pub2"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "from-agent\n"},
        )
    )
    published = await manager._publish_isolated_thread(prepared)
    assert published.publish_blocked is True
    assert "app.py" in published.publish_conflicts
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-claude\n"

    kept = await manager.resolve_publish_conflicts(
        prepared.id, action="keep_project", paths=["app.py"]
    )
    assert kept.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-claude\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == "from-claude\n"

    (tree / "app.py").write_text("from-agent-again\n", encoding="utf-8")
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "from-agent-again\n"},
        )
    )
    (repo / "app.py").write_text("from-claude-2\n", encoding="utf-8")
    forced = await manager.resolve_publish_conflicts(
        prepared.id, action="use_agent", paths=["app.py"]
    )
    assert forced.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-agent-again\n"


@pytest.mark.asyncio
async def test_opaque_change_blocks_instead_of_being_falsely_published(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    payload = b"\x00\x01agent-binary\xff"
    (tree / "asset.bin").write_bytes(payload)
    turn_id = "turn_binary"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["asset.bin"],
            pre_contents={},
            post_contents={},
        )
    )

    blocked = await manager._publish_isolated_thread(prepared)

    assert blocked.publish_blocked is True
    assert blocked.publish_conflicts == ["asset.bin"]
    assert not (repo / "asset.bin").exists()
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == tree.resolve()


@pytest.mark.asyncio
async def test_use_agent_explicitly_publishes_opaque_bytes(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    payload = b"\x00\x01agent-binary\xff"
    (tree / "asset.bin").write_bytes(payload)
    turn_id = "turn_binary_force"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["asset.bin"],
            post_contents={},
        )
    )

    blocked = await manager._publish_isolated_thread(prepared)
    assert blocked.publish_blocked is True
    resolved = await manager.resolve_publish_conflicts(
        prepared.id, action="use_agent", paths=["asset.bin"]
    )

    assert resolved.publish_blocked is False
    assert (repo / "asset.bin").read_bytes() == payload
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == repo.resolve()


@pytest.mark.asyncio
async def test_non_git_stays_on_project(runtime_app, tmp_path: Path) -> None:
    manager = runtime_app.state.thread_manager
    folder = tmp_path / "plain"
    folder.mkdir()
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(folder), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    assert prepared.env_mode == "local"
    assert execution_root(prepared) == folder.resolve()


@pytest.mark.asyncio
async def test_archiving_reclaims_clean_owned_worktree(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    assert tree.is_dir()

    archived = await manager.update_thread(
        prepared.id, UpdateThreadRequest(archived=True)
    )

    assert archived.archived is True
    assert not tree.exists()
    assert archived.env_mode == "local"
    assert archived.worktree_path is None
    assert archived.associated_worktree_path is None


@pytest.mark.asyncio
async def test_archiving_keeps_unpublished_worktree(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("unpublished\n", encoding="utf-8")
    prepared.publish_blocked = True
    manager.store.save_thread(prepared)

    archived = await manager.update_thread(
        prepared.id, UpdateThreadRequest(archived=True)
    )

    assert archived.archived is True
    assert tree.is_dir()
    assert archived.worktree_path == str(tree)


@pytest.mark.asyncio
async def test_delete_refuses_to_orphan_unpublished_worktree(
    runtime_app, client: AsyncClient, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("unpublished\n", encoding="utf-8")
    prepared.publish_blocked = True
    prepared.publish_conflicts = ["app.py"]
    manager.store.save_thread(prepared)

    refused = await client.delete(f"/v1/threads/{prepared.id}")

    assert refused.status_code == 409
    assert refused.json()["detail"]["error"] == "unpublished_worktree_code"
    assert tree.is_dir()
    assert manager.store.load_thread(prepared.id).worktree_path == str(tree)

    deleted = await client.delete(
        f"/v1/threads/{prepared.id}?discard_unpublished=true"
    )

    assert deleted.status_code == 204
    assert not tree.exists()
    with pytest.raises(FileNotFoundError):
        manager.store.load_thread(prepared.id)


@pytest.mark.asyncio
async def test_startup_reconciliation_clears_stale_path_and_merged_branch(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    stale_path = planned_worktree_path(repo, thread.id)
    branch = f"ds/{thread.id}"
    _git(repo, "branch", branch)
    thread.env_mode = "worktree"
    thread.worktree_path = str(stale_path)
    thread.associated_worktree_path = str(stale_path)
    thread.worktree_owned = True
    thread.worktree_branch = branch
    manager.store.save_thread(thread)

    manager._reconcile_missing_worktrees_on_boot()

    reconciled = manager.store.load_thread(thread.id)
    assert reconciled.env_mode == "local"
    assert reconciled.worktree_path is None
    assert reconciled.associated_worktree_path is None
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")


@pytest.mark.asyncio
async def test_prepare_syncs_current_project_into_isolate(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "app.py").write_text("from-claude\n", encoding="utf-8")
    synced = await manager._prepare_isolated_workspace(prepared)
    assert execution_root(synced) == tree
    assert (tree / "app.py").read_text(encoding="utf-8") == "from-claude\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-claude\n"


@pytest.mark.asyncio
async def test_prepare_preserves_uncheckpointed_isolate_labor(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("uncheckpointed-agent\n", encoding="utf-8")
    (repo / "app.py").write_text("from-editor\n", encoding="utf-8")

    async def fake_ensure_engine_loaded(_thread):
        return None

    monkeypatch.setattr(manager, "_ensure_engine_loaded", fake_ensure_engine_loaded)
    warmup = await manager.warmup_thread(thread.id)
    prepared = manager.store.load_thread(thread.id)

    assert warmup["status"] == "ready"
    assert execution_root(prepared) == tree
    assert (tree / "app.py").read_text(encoding="utf-8") == "uncheckpointed-agent\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-editor\n"
    persisted = manager.store.load_thread(thread.id)
    assert persisted.publish_blocked is True
    assert "<unpublished-worktree-labor>" in persisted.publish_conflicts
    assert any(
        event.event == "thread.updated"
        and event.payload.get("changes", {}).get("publish_blocked") is True
        for event in manager.events_since(thread.id)
    )

    resolved = await manager.resolve_publish_conflicts(
        thread.id, action="use_agent"
    )
    assert resolved.publish_blocked is False
    assert resolved.publish_conflicts == []
    assert (repo / "app.py").read_text(encoding="utf-8") == "uncheckpointed-agent\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == "uncheckpointed-agent\n"


@pytest.mark.asyncio
async def test_uncheckpointed_isolate_labor_can_keep_project(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("uncheckpointed-agent\n", encoding="utf-8")
    (repo / "app.py").write_text("from-editor\n", encoding="utf-8")

    prepared = await manager._prepare_isolated_workspace(prepared)

    resolved = await manager.resolve_publish_conflicts(
        thread.id, action="keep_project"
    )
    assert resolved.publish_blocked is False
    assert resolved.publish_conflicts == []
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-editor\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == "from-editor\n"


@pytest.mark.asyncio
async def test_publish_waits_while_sibling_turn_is_active(
    runtime_app, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    first = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    second = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(first)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("from-agent\n", encoding="utf-8")
    turn_id = "turn_busy"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "from-agent\n"},
        )
    )
    async with manager._active_lock:
        manager._active[second.id] = SimpleNamespace(
            active_turn=SimpleNamespace(turn_id="turn_other")
        )
    skipped = await manager._publish_isolated_thread(prepared)
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    assert skipped.publish_blocked is False
    async with manager._active_lock:
        manager._active.pop(second.id, None)
    published = await manager._publish_isolated_thread(prepared)
    assert published.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-agent\n"


@pytest.mark.asyncio
async def test_completed_isolated_labor_stays_pending_until_user_applies(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("draft\n", encoding="utf-8")
    turn_id = "turn_explicit_apply"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "draft\n"},
        )
    )

    await manager._after_turn_released(prepared.id)

    persisted = manager.store.load_thread(prepared.id)
    assert persisted.publish_pending is True
    assert persisted.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"


@pytest.mark.asyncio
async def test_apply_endpoint_reports_applied_and_updates_project(
    runtime_app, client: AsyncClient, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("draft\n", encoding="utf-8")
    turn_id = "turn_apply_endpoint"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "draft\n"},
        )
    )

    response = await client.post(
        f"/v1/threads/{prepared.id}/worktree/resolve",
        json={"action": "apply"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    assert response.json()["thread"]["publish_pending"] is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "draft\n"


@pytest.mark.asyncio
async def test_apply_endpoint_queues_behind_active_sibling_and_retries(
    runtime_app, client: AsyncClient, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    draft_thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    active_thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(draft_thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("queued-draft\n", encoding="utf-8")
    turn_id = "turn_queued_apply"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "queued-draft\n"},
        )
    )
    async with manager._active_lock:
        manager._active[active_thread.id] = SimpleNamespace(
            active_turn=SimpleNamespace(turn_id="turn_other")
        )

    response = await client.post(
        f"/v1/threads/{prepared.id}/worktree/resolve",
        json={"action": "apply"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    queued = manager.store.load_thread(prepared.id)
    assert queued.publish_request_action == "apply"
    assert queued.publish_waiting_on == active_thread.id
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"

    async with manager._active_lock:
        manager._active.pop(active_thread.id, None)
    await manager._after_turn_released(active_thread.id)

    applied = manager.store.load_thread(prepared.id)
    assert applied.publish_pending is False
    assert applied.publish_request_action is None
    assert applied.publish_waiting_on is None
    assert (repo / "app.py").read_text(encoding="utf-8") == "queued-draft\n"
