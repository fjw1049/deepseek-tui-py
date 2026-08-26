from __future__ import annotations

import os
from pathlib import Path

import pytest

from deepseek_tui.workspace.project_lease import ProjectLease


@pytest.mark.asyncio
async def test_project_lease_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    first = ProjectLease(root)
    second = ProjectLease(root)
    assert await first.acquire(nonblocking=True)
    assert await second.acquire(nonblocking=True) is False
    first.release()
    assert await second.acquire(nonblocking=True)
    second.release()
    assert first.path.parent == (tmp_path / "home" / "locks")
    assert os.getpid() > 0
