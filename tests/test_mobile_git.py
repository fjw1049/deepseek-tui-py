from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deepseek_tui.mobile.git import router


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def mobile_git(tmp_path, monkeypatch):
    helper = os.environ.get("DEEPSEEK_MOBILE_GIT_HELPER", "")
    if not helper or not Path(helper).is_file():
        pytest.skip("Build and set DEEPSEEK_MOBILE_GIT_HELPER to test the original desktop service")
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Mobile test")
    git(root, "config", "user.email", "mobile-test@example.invalid")
    (root / "hello.txt").write_text("before\n")
    git(root, "add", "hello.txt")
    git(root, "commit", "-m", "initial")
    active = AsyncMock(return_value=False)
    app = FastAPI()
    app.state.thread_manager = SimpleNamespace(
        store=SimpleNamespace(
            load_thread=lambda _: SimpleNamespace(workspace=str(root)),
            list_turns_for_thread=lambda thread_id: [SimpleNamespace(diff_snapshot={
                "files": [{"path": "hello.txt" if thread_id == "a" else "other.txt"}]
            })],
        ),
        is_thread_turn_active=active,
    )
    app.include_router(router)
    with TestClient(app) as client:
        yield client, root, active


def test_reused_desktop_git_stage_commit_and_branch(mobile_git):
    client, root, _ = mobile_git
    (root / "hello.txt").write_text("after\n")
    (root / ".env").write_text("DO_NOT_EXPOSE=secret\n")
    state = client.get("/v1/threads/a/git/changes")
    assert state.status_code == 200, state.text
    assert [file["path"] for file in state.json()["files"]] == ["hello.txt"]
    assert "DO_NOT_EXPOSE" not in state.text
    patch = client.get("/v1/threads/a/git/diff", params={"path": "hello.txt"})
    assert "+after" in patch.json()["patch"]
    assert client.post("/v1/threads/a/git/stage", json={"paths": ["hello.txt"]}).status_code == 409
    assert (
        client.post(
            "/v1/threads/a/git/stage", json={"paths": ["hello.txt"], "confirm": True}
        ).status_code
        == 200
    )
    (root / "hello.txt").write_text("later unstaged\n")
    commit = client.post(
        "/v1/threads/a/git/commit", json={"message": "mobile commit", "confirm": True}
    )
    assert commit.status_code == 200, commit.text
    assert git(root, "show", "HEAD:hello.txt") == "after"
    assert (root / "hello.txt").read_text() == "later unstaged\n"
    result = client.post(
        "/v1/threads/a/git/createBranch", json={"branch": "mobile-test", "confirm": True}
    )
    assert result.status_code == 200, result.text
    assert git(root, "branch", "--show-current") == "mobile-test"
    assert (
        client.post(
            "/v1/threads/a/git/switch", json={"branch": "main", "confirm": True}
        ).status_code
        == 200
    )
    assert client.get("/v1/threads/a/git/branches").json()["currentBranch"] == "main"


def test_blocks_active_sensitive_paths_and_sensitive_staged_commit(mobile_git):
    client, root, active = mobile_git
    active.return_value = True
    assert (
        client.post(
            "/v1/threads/a/git/stage", json={"paths": ["hello.txt"], "confirm": True}
        ).status_code
        == 409
    )
    active.return_value = False
    for path in (".env", "../escape", ".git/config"):
        assert client.post(
            "/v1/threads/a/git/stage", json={"paths": [path], "confirm": True}
        ).status_code in {400, 403}
    (root / ".env").write_text("SECRET=not-committed")
    git(root, "add", ".env")
    result = client.post("/v1/threads/a/git/commit", json={"message": "must fail", "confirm": True})
    assert result.status_code == 403
    assert git(root, "log", "-1", "--format=%s") == "initial"
    assert (
        client.post(
            "/v1/threads/a/git/switch", json={"branch": "--detach", "confirm": True}
        ).status_code
        == 400
    )


def test_session_selection_does_not_commit_another_sessions_staged_file(mobile_git):
    client, root, _ = mobile_git
    (root / "other.txt").write_text("other base\n")
    git(root, "add", "other.txt")
    git(root, "commit", "-m", "second file")
    (root / "other.txt").write_text("other session update\n")
    git(root, "add", "other.txt")
    (root / "hello.txt").write_text("this session update\n")
    own = client.get("/v1/threads/a/git/changes?session_only=true")
    assert own.status_code == 200
    assert own.json()["session_only"] is True
    assert [f["path"] for f in own.json()["files"]] == ["hello.txt"]
    assert own.json()["stagedFiles"] == []
    other = client.get("/v1/threads/b/git/changes?session_only=true")
    assert [f["path"] for f in other.json()["files"]] == ["other.txt"]
    assert client.get("/v1/threads/a/git/diff?path=other.txt&session_only=true").status_code == 403
    for action in ("stage", "unstage", "commit"):
        denied = client.post(f"/v1/threads/a/git/{action}", json={
            "paths": ["other.txt"], "message": "wrong selection", "session_only": True, "confirm": True,
        })
        assert denied.status_code == 403
    assert client.post("/v1/threads/a/git/commit", json={
        "message": "must select", "session_only": True, "confirm": True,
    }).status_code == 400
    result = client.post("/v1/threads/a/git/commit", json={
        "message": "own session", "paths": ["hello.txt"], "session_only": True, "confirm": True,
    })
    assert result.status_code == 200, result.text
    assert git(root, "show", "HEAD:hello.txt") == "this session update"
    assert git(root, "show", "HEAD:other.txt") == "other base"
    assert git(root, "diff", "--cached", "--name-only") == "other.txt"
    assert (root / "other.txt").read_text() == "other session update\n"
