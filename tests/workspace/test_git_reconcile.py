"""Git turn baseline / reconcile — only new dirt enters the ledger."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from deepseek_tui.workspace.git_reconcile import capture_baseline, reconcile_to_ledger
from deepseek_tui.workspace.mutation_ledger import FileMutation, TurnMutationLedger


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
async def test_reconcile_skips_preexisting_dirt(git_repo: Path) -> None:
    # Dirty before the turn starts.
    (git_repo / "tracked.py").write_text("pre-existing\n", encoding="utf-8")
    (git_repo / "orphan_pre.py").write_text("old\n", encoding="utf-8")

    baseline = await capture_baseline(git_repo)
    assert "tracked.py" in baseline.dirty_at_start
    assert "orphan_pre.py" in baseline.dirty_at_start

    # New dirt introduced during the turn.
    (git_repo / "new_this_turn.py").write_text("fresh\n", encoding="utf-8")
    (git_repo / "tracked.py").write_text("pre-existing\nand more\n", encoding="utf-8")

    ledger = TurnMutationLedger("turn_r", throttle_ms=0)
    added = await reconcile_to_ledger(ledger, baseline)
    paths = {m.path for m in added}
    assert "new_this_turn.py" in paths
    # Pre-existing untracked must not be attributed to this turn.
    assert "orphan_pre.py" not in paths
    # Pre-existing tracked dirt stays excluded even if it changed again.
    assert "tracked.py" not in paths


@pytest.mark.asyncio
async def test_reconcile_skips_paths_already_in_ledger(git_repo: Path) -> None:
    baseline = await capture_baseline(git_repo)
    (git_repo / "via_tool.py").write_text("tool\n", encoding="utf-8")

    ledger = TurnMutationLedger("turn_r2", throttle_ms=0)
    ledger.commit(
        FileMutation(
            mutation_id="m1",
            turn_id="turn_r2",
            path="via_tool.py",
            op="create",
            unified_diff=(
                "diff --git a/via_tool.py b/via_tool.py\n"
                "--- /dev/null\n+++ b/via_tool.py\n@@\n+tool\n"
            ),
            additions=1,
            deletions=0,
            source="write_file",
        ),
        emit=False,
    )
    added = await reconcile_to_ledger(ledger, baseline)
    assert all(m.path != "via_tool.py" for m in added)


@pytest.mark.asyncio
async def test_reconcile_picks_up_untracked_and_modified(git_repo: Path) -> None:
    baseline = await capture_baseline(git_repo)
    (git_repo / "tracked.py").write_text("v2\n", encoding="utf-8")
    (git_repo / "brand_new.py").write_text("n\n", encoding="utf-8")

    ledger = TurnMutationLedger("turn_r3", throttle_ms=0)
    added = await reconcile_to_ledger(ledger, baseline)
    by_path = {m.path: m for m in added}
    assert "tracked.py" in by_path
    assert by_path["tracked.py"].source == "git_reconcile"
    assert "brand_new.py" in by_path
    assert by_path["brand_new.py"].op == "create"
    assert "+n" in by_path["brand_new.py"].unified_diff
