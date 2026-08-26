from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from deepseek_tui.workspace.managed_worktree import (
    PathImage,
    apply_path_images,
    apply_worktree,
    create_managed_worktree,
    handoff_changes,
    promote_worktree_branch,
    prune_orphaned_worktrees,
    reclaim_managed_worktree,
    remove_managed_worktree,
    sync_isolate_from_project,
    WorktreeError,
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


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
async def test_worktree_isolates_and_apply_merges(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_abc", copy_tracked_dirty=False)
    assert created.path.is_dir()
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == "v1\n"

    (created.path / "tracked.py").write_text("v2\n", encoding="utf-8")
    (created.path / "new.py").write_text("added\n", encoding="utf-8")
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "v1\n"
    assert not (git_repo / "new.py").exists()

    report = await apply_worktree(git_repo, created.path, created.base, mode="merge")
    assert "tracked.py" in report.applied
    assert "new.py" in report.applied
    assert report.conflicted == []
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "v2\n"
    assert (git_repo / "new.py").read_text(encoding="utf-8") == "added\n"

    await remove_managed_worktree(git_repo, created.path)
    assert not created.path.exists()


@pytest.mark.asyncio
async def test_apply_conflict_leaves_project(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_def", copy_tracked_dirty=False)
    (created.path / "tracked.py").write_text("from-tree\n", encoding="utf-8")
    (git_repo / "tracked.py").write_text("from-project\n", encoding="utf-8")

    report = await apply_worktree(git_repo, created.path, created.base, mode="merge")
    assert "tracked.py" in report.conflicted
    assert report.applied == []
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "from-project\n"

    forced = await apply_worktree(
        git_repo, created.path, created.base, mode="merge", force=True
    )
    assert "tracked.py" in forced.applied
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "from-tree\n"


@pytest.mark.asyncio
async def test_apply_path_images_conflict_is_atomic(git_repo: Path) -> None:
    (git_repo / "tracked.py").write_text("from-project\n", encoding="utf-8")
    report = await apply_path_images(
        git_repo,
        [
            PathImage(path="tracked.py", base="v1\n", theirs="from-tree\n"),
            PathImage(path="other.py", base=None, theirs="new\n"),
        ],
    )
    assert "tracked.py" in report.conflicted
    assert report.applied == []
    assert not (git_repo / "other.py").exists()
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "from-project\n"

    forced = await apply_path_images(
        git_repo,
        [PathImage(path="tracked.py", base="v1\n", theirs="from-tree\n")],
        force=True,
    )
    assert "tracked.py" in forced.applied
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "from-tree\n"


@pytest.mark.asyncio
async def test_apply_copies_binary(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_bin", copy_tracked_dirty=False)
    payload = b"\x00\x01\x02\xffbinary"
    (created.path / "icon.bin").write_bytes(payload)

    report = await apply_worktree(git_repo, created.path, created.base, mode="merge")
    assert "icon.bin" in report.applied
    assert (git_repo / "icon.bin").read_bytes() == payload


@pytest.mark.asyncio
async def test_handoff_moves_tracked_and_untracked(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    (git_repo / "tracked.py").write_text("dirty\n", encoding="utf-8")
    (git_repo / "scratch.txt").write_text("untracked\n", encoding="utf-8")
    created = await create_managed_worktree(git_repo, "thr_hand", copy_tracked_dirty=False)

    report = await handoff_changes(git_repo, created.path, move=True)
    assert "tracked.py" in report.applied
    assert "scratch.txt" in report.applied
    assert report.conflicted == []
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == "dirty\n"
    assert (created.path / "scratch.txt").read_text(encoding="utf-8") == "untracked\n"
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "v1\n"
    assert not (git_repo / "scratch.txt").exists()


@pytest.mark.asyncio
async def test_handoff_conflict_aborts_without_writes(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_conf", copy_tracked_dirty=False)
    (git_repo / "tracked.py").write_text("from-project\n", encoding="utf-8")
    (created.path / "tracked.py").write_text("from-tree\n", encoding="utf-8")

    report = await handoff_changes(git_repo, created.path, move=True)
    assert "tracked.py" in report.conflicted
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == "from-tree\n"
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "from-project\n"


@pytest.mark.asyncio
async def test_create_copies_untracked(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    (git_repo / "scratch.txt").write_text("keep\n", encoding="utf-8")
    created = await create_managed_worktree(git_repo, "thr_copy", copy_tracked_dirty=True)
    assert (created.path / "scratch.txt").read_text(encoding="utf-8") == "keep\n"
    assert (git_repo / "scratch.txt").read_text(encoding="utf-8") == "keep\n"


@pytest.mark.asyncio
async def test_promote_creates_branch(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_prom", copy_tracked_dirty=False)
    assert created.branch.startswith("ds/")
    assert _git(created.path, "branch", "--show-current") == created.branch
    name = await promote_worktree_branch(created.path, "feature/ship")
    assert name == "feature/ship"
    assert _git(created.path, "branch", "--show-current") == "feature/ship"
    assert await promote_worktree_branch(created.path, "feature/ship") == "feature/ship"
    _git(git_repo, "branch", "feature/taken")
    with pytest.raises(WorktreeError, match="already exists"):
        await promote_worktree_branch(created.path, "feature/taken")


@pytest.mark.asyncio
async def test_apply_conflict_does_not_write_other_files(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_half", copy_tracked_dirty=False)
    (created.path / "tracked.py").write_text("from-tree\n", encoding="utf-8")
    (created.path / "extra.py").write_text("only-tree\n", encoding="utf-8")
    (git_repo / "tracked.py").write_text("from-project\n", encoding="utf-8")

    report = await apply_worktree(git_repo, created.path, created.base, mode="merge")
    assert "tracked.py" in report.conflicted
    assert report.applied == []
    assert not (git_repo / "extra.py").exists()
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "from-project\n"


@pytest.mark.asyncio
async def test_prune_leaves_labor_and_unregistered(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    from deepseek_tui.config.paths import user_worktrees_dir

    clean = await create_managed_worktree(git_repo, "thr_clean", copy_tracked_dirty=False)
    dirty = await create_managed_worktree(git_repo, "thr_dirty", copy_tracked_dirty=False)
    (dirty.path / "labor.py").write_text("keep me\n", encoding="utf-8")
    junk = user_worktrees_dir() / "repo-aaaa" / "plain"
    junk.mkdir(parents=True)
    (junk / "gone.txt").write_text("y\n", encoding="utf-8")

    removed = prune_orphaned_worktrees([])
    assert removed == 1
    assert not clean.path.exists()
    assert dirty.path.is_dir()
    assert (dirty.path / "labor.py").read_text(encoding="utf-8") == "keep me\n"
    assert junk.is_dir()


@pytest.mark.asyncio
async def test_reclaim_keeps_dirty_owned_worktree(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_keep", copy_tracked_dirty=False)
    (created.path / "labor.py").write_text("keep\n", encoding="utf-8")
    status = await reclaim_managed_worktree(git_repo, created.path, owned=True)
    assert status == "kept"
    assert created.path.is_dir()
    skipped = await reclaim_managed_worktree(git_repo, created.path, owned=False)
    assert skipped == "skipped"


@pytest.mark.asyncio
async def test_sync_isolate_matches_project_despite_isolate_dirt(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_sync", copy_tracked_dirty=False)
    (created.path / "tracked.py").write_text("from-isolate\n", encoding="utf-8")
    (git_repo / "tracked.py").write_text("from-claude\n", encoding="utf-8")
    (git_repo / "extra.py").write_text("new\n", encoding="utf-8")
    await sync_isolate_from_project(git_repo, created.path)
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == "from-claude\n"
    assert (created.path / "extra.py").read_text(encoding="utf-8") == "new\n"
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "from-claude\n"
