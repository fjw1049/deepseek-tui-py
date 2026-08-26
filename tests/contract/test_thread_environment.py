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
async def test_create_ignores_client_worktree_mode(
    client: AsyncClient, tmp_path: Path
) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    create = await client.post(
        "/v1/threads", json={"workspace": str(folder), "env_mode": "worktree"}
    )
    assert create.status_code == 201
    assert create.json()["env_mode"] == "local"


@pytest.mark.asyncio
async def test_environment_view_after_prepare(runtime_app, tmp_path: Path) -> None:
    import subprocess

    repo = tmp_path / "proj"
    repo.mkdir()
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

    manager = runtime_app.state.thread_manager
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    view = manager.environment_view(prepared.id)
    assert view["workspace"] == str(project_root(prepared))
    assert view["execution_root"] == str(execution_root(prepared))
    assert view["execution_root"] != view["workspace"]
    assert view["publish_blocked"] is False
    assert "suggest_worktree" not in view
