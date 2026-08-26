from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from deepseek_tui.server.threads.models import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnRecord,
)
from deepseek_tui.workspace.execution import execution_root, project_root
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
    (tree / "app.py").write_text("stale-isolate\n", encoding="utf-8")
    (repo / "app.py").write_text("from-claude\n", encoding="utf-8")
    synced = await manager._prepare_isolated_workspace(prepared)
    assert execution_root(synced) == tree
    assert (tree / "app.py").read_text(encoding="utf-8") == "from-claude\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-claude\n"


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
