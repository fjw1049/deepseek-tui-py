"""Managed worktree removal stops stray processes before deleting the tree."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from deepseek_tui.workspace.managed_worktree import (
    _pids_with_cwd_under_sync,
    terminate_processes_under,
)

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="process enumeration is POSIX-only"
)


def _spawn_sleeper(cwd: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_until_found(pid: int, directory: Path, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pid in _pids_with_cwd_under_sync(directory):
            return True
        time.sleep(0.05)
    return False


def test_pids_with_cwd_under_finds_child(tmp_path: Path) -> None:
    child = _spawn_sleeper(tmp_path)
    try:
        assert _wait_until_found(child.pid, tmp_path)
        assert child.pid not in _pids_with_cwd_under_sync(tmp_path / "other")
    finally:
        child.kill()
        child.wait()


def test_pids_with_cwd_under_handles_missing_directory(tmp_path: Path) -> None:
    assert _pids_with_cwd_under_sync(tmp_path / "does-not-exist") == []


@pytest.mark.asyncio
async def test_terminate_processes_under_kills_child(tmp_path: Path) -> None:
    child = _spawn_sleeper(tmp_path)
    try:
        assert _wait_until_found(child.pid, tmp_path)
        signalled = await terminate_processes_under(tmp_path, grace_seconds=2.0)
        assert signalled >= 1
        child.wait(timeout=10)
        assert child.pid not in _pids_with_cwd_under_sync(tmp_path)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


@pytest.mark.asyncio
async def test_terminate_processes_under_without_processes_is_noop(
    tmp_path: Path,
) -> None:
    assert await terminate_processes_under(tmp_path / "empty") == 0


@pytest.mark.asyncio
async def test_remove_managed_worktree_terminates_strays(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from deepseek_tui.workspace import managed_worktree as mw

    called: list[Path] = []

    async def fake_terminate(directory: Path, **_kwargs: object) -> int:
        called.append(Path(directory))
        return 0

    monkeypatch.setattr(mw, "terminate_processes_under", fake_terminate)
    monkeypatch.setattr(mw, "user_worktrees_dir", lambda: tmp_path / "worktrees")
    dest = tmp_path / "worktrees" / "repo-x" / "thr_1"
    dest.mkdir(parents=True)

    await mw.remove_managed_worktree(tmp_path / "project", dest)

    assert called == [dest.resolve()]
    assert not dest.exists()
