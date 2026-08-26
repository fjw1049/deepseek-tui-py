from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.asyncio
async def test_create_thread_defaults_local_env(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={"model": "deepseek-chat"})
    assert create.status_code == 201
    body = create.json()
    assert body["env_mode"] == "local"
    assert body.get("worktree_path") is None


@pytest.mark.asyncio
async def test_switch_to_worktree_and_apply(
    client: AsyncClient, tmp_path: Path
) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "init")

    create = await client.post(
        "/v1/threads", json={"workspace": str(repo), "model": "deepseek-chat"}
    )
    assert create.status_code == 201
    thread_id = create.json()["id"]

    env = await client.get(f"/v1/threads/{thread_id}/environment")
    assert env.status_code == 200
    assert env.json()["env_mode"] == "local"
    assert env.json()["workspace"] == str(repo.resolve())

    switched = await client.post(
        f"/v1/threads/{thread_id}/environment",
        json={"env_mode": "worktree", "copy_dirty": False},
    )
    assert switched.status_code == 200
    body = switched.json()
    assert body["env_mode"] == "worktree"
    tree = Path(body["worktree_path"])
    assert tree.is_dir()
    (tree / "app.py").write_text("two\n", encoding="utf-8")
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"

    preview = await client.get(f"/v1/threads/{thread_id}/worktree/apply-preview")
    assert preview.status_code == 200
    assert "app.py" in preview.json()["applied"]

    applied = await client.post(
        f"/v1/threads/{thread_id}/worktree/apply", json={"mode": "merge"}
    )
    assert applied.status_code == 200
    assert "app.py" in applied.json()["applied"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "two\n"

    back = await client.post(
        f"/v1/threads/{thread_id}/environment", json={"env_mode": "local"}
    )
    assert back.status_code == 200
    assert back.json()["env_mode"] == "local"


@pytest.mark.asyncio
async def test_switch_copies_dirty_without_moving(
    client: AsyncClient, tmp_path: Path
) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "init")
    (repo / "app.py").write_text("dirty\n", encoding="utf-8")
    (repo / "scratch.txt").write_text("untracked\n", encoding="utf-8")

    create = await client.post(
        "/v1/threads", json={"workspace": str(repo), "model": "deepseek-chat"}
    )
    thread_id = create.json()["id"]
    switched = await client.post(
        f"/v1/threads/{thread_id}/environment", json={"env_mode": "worktree"}
    )
    assert switched.status_code == 200
    tree = Path(switched.json()["worktree_path"])
    assert (tree / "app.py").read_text(encoding="utf-8") == "dirty\n"
    assert (tree / "scratch.txt").read_text(encoding="utf-8") == "untracked\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "dirty\n"
    assert (repo / "scratch.txt").read_text(encoding="utf-8") == "untracked\n"


@pytest.mark.asyncio
async def test_leave_worktree_does_not_move_files(
    client: AsyncClient, tmp_path: Path
) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "init")

    create = await client.post(
        "/v1/threads", json={"workspace": str(repo), "model": "deepseek-chat"}
    )
    thread_id = create.json()["id"]
    switched = await client.post(
        f"/v1/threads/{thread_id}/environment",
        json={"env_mode": "worktree", "copy_dirty": False},
    )
    tree = Path(switched.json()["worktree_path"])
    (tree / "app.py").write_text("from-tree\n", encoding="utf-8")
    (repo / "app.py").write_text("from-project\n", encoding="utf-8")

    back = await client.post(
        f"/v1/threads/{thread_id}/environment", json={"env_mode": "local"}
    )
    assert back.status_code == 200
    assert back.json()["env_mode"] == "local"
    assert (tree / "app.py").read_text(encoding="utf-8") == "from-tree\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-project\n"


@pytest.mark.asyncio
async def test_promote_worktree_branch(
    client: AsyncClient, tmp_path: Path
) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "init")

    create = await client.post(
        "/v1/threads", json={"workspace": str(repo), "model": "deepseek-chat"}
    )
    thread_id = create.json()["id"]
    switched = await client.post(
        f"/v1/threads/{thread_id}/environment",
        json={"env_mode": "worktree", "copy_dirty": False},
    )
    tree = Path(switched.json()["worktree_path"])
    promoted = await client.post(
        f"/v1/threads/{thread_id}/worktree/promote", json={"branch": "ds/demo"}
    )
    assert promoted.status_code == 200
    assert promoted.json()["branch"] == "ds/demo"
    proc = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(tree),
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "ds/demo"

    again = await client.post(
        f"/v1/threads/{thread_id}/worktree/promote", json={"branch": "ds/demo"}
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_worktree_rejected_for_non_git(
    client: AsyncClient, tmp_path: Path
) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    create = await client.post(
        "/v1/threads", json={"workspace": str(folder), "env_mode": "worktree"}
    )
    assert create.status_code == 400
