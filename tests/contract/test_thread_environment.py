from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from deepseek_tui.server.threads.models import CreateThreadRequest
from deepseek_tui.workspace.execution import execution_root, project_root


@pytest.mark.asyncio
async def test_create_thread_defaults_local_env(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={"model": "deepseek-chat"})
    assert create.status_code == 201
    body = create.json()
    assert body["env_mode"] == "local"
    assert body.get("worktree_path") is None


@pytest.mark.asyncio
async def test_create_rejects_worktree_mode_on_non_git_folder(
    client: AsyncClient, tmp_path: Path
) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    create = await client.post(
        "/v1/threads", json={"workspace": str(folder), "env_mode": "worktree"}
    )
    assert create.status_code == 400


def _make_git_repo(repo: Path) -> None:
    import subprocess

    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=str(repo), check=True, capture_output=True
    )


@pytest.mark.asyncio
async def test_environment_view_after_prepare(runtime_app, tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _make_git_repo(repo)

    manager = runtime_app.state.thread_manager
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat", env_mode="worktree")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    view = manager.environment_view(prepared.id)
    assert view["workspace"] == str(project_root(prepared))
    assert view["execution_root"] == str(execution_root(prepared))
    assert view["execution_root"] != view["workspace"]
    assert view["publish_blocked"] is False
    assert "suggest_worktree" not in view


@pytest.mark.asyncio
async def test_local_thread_prepare_stays_on_project(
    runtime_app, tmp_path: Path
) -> None:
    repo = tmp_path / "proj"
    _make_git_repo(repo)

    manager = runtime_app.state.thread_manager
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    view = manager.environment_view(prepared.id)
    assert view["env_mode"] == "local"
    assert view["execution_root"] == view["workspace"]


@pytest.mark.asyncio
async def test_update_env_mode_locks_after_first_turn(runtime_app, tmp_path: Path) -> None:
    from deepseek_tui.server.threads.models import UpdateThreadRequest

    repo = tmp_path / "proj"
    _make_git_repo(repo)

    manager = runtime_app.state.thread_manager
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    updated = await manager.update_thread(
        thread.id, UpdateThreadRequest(env_mode="worktree")
    )
    assert updated.env_mode == "worktree"
    # Simulate a completed first turn, then verify the switch is refused.
    persisted = manager.store.load_thread(thread.id)
    persisted.latest_turn_id = "turn_1"
    manager.store.save_thread(persisted)
    with pytest.raises(ValueError, match="before the thread's first turn"):
        await manager.update_thread(
            thread.id, UpdateThreadRequest(env_mode="local")
        )


@pytest.mark.asyncio
async def test_update_worktree_to_local_before_first_turn_reclaims(
    runtime_app, tmp_path: Path
) -> None:
    from deepseek_tui.server.threads.models import UpdateThreadRequest

    repo = tmp_path / "proj"
    _make_git_repo(repo)

    manager = runtime_app.state.thread_manager
    thread = await manager.create_thread(
        CreateThreadRequest(
            workspace=str(repo), model="deepseek-chat", env_mode="worktree"
        )
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    assert prepared.worktree_path is not None
    worktree = Path(prepared.worktree_path)
    assert worktree.is_dir()

    updated = await manager.update_thread(
        thread.id, UpdateThreadRequest(env_mode="local")
    )
    assert updated.env_mode == "local"
    assert updated.worktree_path is None
    assert not worktree.exists()


@pytest.mark.asyncio
async def test_update_worktree_to_local_refused_when_worktree_dirty(
    runtime_app, tmp_path: Path
) -> None:
    from deepseek_tui.server.threads.models import UpdateThreadRequest

    repo = tmp_path / "proj"
    _make_git_repo(repo)

    manager = runtime_app.state.thread_manager
    thread = await manager.create_thread(
        CreateThreadRequest(
            workspace=str(repo), model="deepseek-chat", env_mode="worktree"
        )
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    worktree = Path(prepared.worktree_path)
    # Uncommitted content that exists only in the worktree — reclaim keeps it.
    (worktree / "only_in_worktree.txt").write_text("labor\n", encoding="utf-8")

    with pytest.raises(ValueError, match="uncommitted changes"):
        await manager.update_thread(thread.id, UpdateThreadRequest(env_mode="local"))
    # The record must keep pointing at the worktree so a later prepare
    # reuses (not collides with) the directory.
    persisted = manager.store.load_thread(thread.id)
    assert persisted.env_mode == "worktree"
    assert persisted.worktree_path is not None
    assert worktree.is_dir()
