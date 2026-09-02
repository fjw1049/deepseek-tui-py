from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from pathlib import Path

import pytest

import deepseek_tui.workspace.managed_worktree as managed_worktree
from deepseek_tui.workspace.managed_worktree import (
    PathImage,
    UnpublishedWorktreeError,
    WorktreeError,
    apply_path_images,
    apply_worktree,
    capture_worktree_baseline,
    create_managed_worktree,
    handoff_changes,
    planned_worktree_path,
    promote_worktree_branch,
    prune_orphaned_worktrees,
    reclaim_managed_worktree,
    remove_managed_worktree,
    sync_isolate_from_project,
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


def _git_succeeds(cwd: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0


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


@pytest.mark.skipif(os.name == "nt", reason="executable mode is a POSIX concept")
@pytest.mark.asyncio
async def test_apply_path_images_preserves_existing_mode(git_repo: Path) -> None:
    target = git_repo / "tracked.py"
    target.chmod(0o755)

    report = await apply_path_images(
        git_repo,
        [PathImage(path="tracked.py", base="v1\n", theirs="v2\n")],
    )

    assert report.applied == ["tracked.py"]
    assert target.read_text(encoding="utf-8") == "v2\n"
    assert target.stat().st_mode & 0o777 == 0o755


@pytest.mark.asyncio
async def test_apply_path_images_rejects_destination_change_after_plan(
    git_repo: Path,
) -> None:
    target = git_repo / "tracked.py"

    def edit_after_plan(_images: dict[str, tuple[str | None, str | None]]) -> None:
        target.write_text("late editor change\n", encoding="utf-8")

    report = await apply_path_images(
        git_repo,
        [PathImage(path="tracked.py", base="v1\n", theirs="task\n")],
        before_write=edit_after_plan,
    )

    assert report.applied == []
    assert report.conflicted == ["tracked.py"]
    assert target.read_text(encoding="utf-8") == "late editor change\n"


@pytest.mark.asyncio
async def test_apply_path_images_rollback_preserves_late_destination_edit(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = git_repo / "first.py"
    second = git_repo / "second.py"
    first.write_text("first old\n", encoding="utf-8")
    second.write_text("second old\n", encoding="utf-8")
    real_write = managed_worktree._write_text

    def fail_second_write(root: Path, rel: str, content: str | None) -> None:
        if rel == "second.py" and content == "second task\n":
            first.write_text("late editor change\n", encoding="utf-8")
            raise OSError("injected second write failure")
        real_write(root, rel, content)

    monkeypatch.setattr(managed_worktree, "_write_text", fail_second_write)

    report = await apply_path_images(
        git_repo,
        [
            PathImage(path="first.py", base="first old\n", theirs="first task\n"),
            PathImage(
                path="second.py", base="second old\n", theirs="second task\n"
            ),
        ],
    )

    assert report.applied == []
    assert set(report.skipped) == {"first.py", "second.py"}
    assert first.read_text(encoding="utf-8") == "late editor change\n"
    assert second.read_text(encoding="utf-8") == "second old\n"


@pytest.mark.asyncio
async def test_apply_raw_paths_rejects_changed_source_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    (source / "asset.bin").write_bytes(b"\0checkpoint")
    (dest / "asset.bin").write_bytes(b"\0project")
    expected = managed_worktree.worktree_path_signatures(source, ["asset.bin"])
    (source / "asset.bin").write_bytes(b"\0late")

    report = await managed_worktree.apply_raw_paths(
        source,
        dest,
        ["asset.bin"],
        expected_source_signatures=expected,
    )

    assert report.applied == []
    assert report.conflicted == ["asset.bin"]
    assert (dest / "asset.bin").read_bytes() == b"\0project"


@pytest.mark.asyncio
async def test_apply_raw_paths_never_reports_existing_directory_as_applied(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    (source / "node").mkdir(parents=True)
    (dest / "node").mkdir(parents=True)
    (source / "node" / "child.txt").write_text("task\n", encoding="utf-8")
    (dest / "node" / "child.txt").write_text("project\n", encoding="utf-8")

    report = await managed_worktree.apply_raw_paths(source, dest, ["node"])

    assert report.applied == []
    assert report.skipped == ["node"]
    assert (dest / "node" / "child.txt").read_text(encoding="utf-8") == (
        "project\n"
    )


@pytest.mark.asyncio
async def test_apply_raw_paths_waits_for_worker_before_propagating_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    (source / "asset.bin").write_bytes(b"\0task")
    (dest / "asset.bin").write_bytes(b"\0project")
    started = threading.Event()
    release = threading.Event()
    real_apply = managed_worktree._apply_raw_paths_sync

    def slow_apply(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(managed_worktree, "_apply_raw_paths_sync", slow_apply)
    task = asyncio.create_task(
        managed_worktree.apply_raw_paths(source, dest, ["asset.bin"])
    )
    for _ in range(100):
        if started.is_set():
            break
        await asyncio.sleep(0.001)
    assert started.is_set()

    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert (dest / "asset.bin").read_bytes() == b"\0task"


@pytest.mark.asyncio
async def test_resolve_labor_never_discards_edit_after_raw_apply(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_resolve_late", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    (created.path / "tracked.py").write_text("chosen task\n", encoding="utf-8")
    expected = await managed_worktree.worktree_change_signatures_since_baseline(
        created.path, baseline
    )
    real_apply_raw_paths = managed_worktree.apply_raw_paths

    async def mutate_after_raw_apply(*args, **kwargs):
        report = await real_apply_raw_paths(*args, **kwargs)
        (created.path / "tracked.py").write_text(
            "late task edit\n", encoding="utf-8"
        )
        return report

    monkeypatch.setattr(
        managed_worktree, "apply_raw_paths", mutate_after_raw_apply
    )

    with pytest.raises(UnpublishedWorktreeError):
        await managed_worktree.resolve_unpublished_worktree_labor(
            git_repo,
            created.path,
            use_worktree=True,
            labor_paths=["tracked.py"],
            baseline=baseline,
            expected_signatures=expected,
        )

    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "chosen task\n"
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == (
        "late task edit\n"
    )


@pytest.mark.asyncio
async def test_apply_worktree_git_lookup_failure_never_means_absent(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_show_failure", copy_tracked_dirty=False
    )
    (created.path / "tracked.py").write_text("task\n", encoding="utf-8")
    (git_repo / "tracked.py").write_text("project\n", encoding="utf-8")
    real_git = managed_worktree._git

    async def failing_git(
        root: Path, args: list[str], *, check: bool = True
    ) -> str | None:
        if args and args[0] == "ls-tree":
            raise WorktreeError("injected object lookup failure")
        return await real_git(root, args, check=check)

    monkeypatch.setattr(managed_worktree, "_git", failing_git)

    with pytest.raises(WorktreeError, match="injected object lookup failure"):
        await apply_worktree(git_repo, created.path, created.base)

    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "project\n"


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
    assert created.branch == ""
    assert _git(created.path, "branch", "--show-current") == ""
    name = await promote_worktree_branch(created.path, "feature/ship")
    assert name == "feature/ship"
    assert _git(created.path, "branch", "--show-current") == "feature/ship"


@pytest.mark.asyncio
async def test_create_copies_only_selected_ignored_setup_files(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    (git_repo / ".gitignore").write_text(".env\nsecret.txt\n", encoding="utf-8")
    (git_repo / ".worktreeinclude").write_text(".env\n", encoding="utf-8")
    (git_repo / ".env").write_text("TOKEN=local\n", encoding="utf-8")
    (git_repo / "secret.txt").write_text("do-not-copy\n", encoding="utf-8")
    _git(git_repo, "add", ".gitignore", ".worktreeinclude")
    _git(git_repo, "commit", "-m", "worktree setup policy")

    created = await create_managed_worktree(
        git_repo, "thr_setup", copy_tracked_dirty=False
    )

    assert (created.path / ".env").read_text(encoding="utf-8") == "TOKEN=local\n"
    assert not (created.path / "secret.txt").exists()
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
async def test_reclaim_keeps_edit_that_arrives_at_final_remove(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_late_reclaim", copy_tracked_dirty=False
    )
    real_run = managed_worktree.subprocess.run
    injected = False

    def edit_before_remove(args, *positional, **kwargs):
        nonlocal injected
        if (
            not injected
            and list(args[:3]) == ["git", "worktree", "remove"]
            and str(created.path) in args
        ):
            injected = True
            (created.path / "tracked.py").write_text(
                "late editor change\n", encoding="utf-8"
            )
        return real_run(args, *positional, **kwargs)

    monkeypatch.setattr(managed_worktree.subprocess, "run", edit_before_remove)

    status = await reclaim_managed_worktree(git_repo, created.path, owned=True)

    assert injected is True
    assert status == "kept"
    assert created.path.is_dir()
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == (
        "late editor change\n"
    )


@pytest.mark.asyncio
async def test_reclaim_keeps_detached_unique_commit(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_commit", copy_tracked_dirty=False)
    (created.path / "tracked.py").write_text("committed\n", encoding="utf-8")
    _git(created.path, "add", "tracked.py")
    _git(created.path, "commit", "-m", "agent commit")

    status = await reclaim_managed_worktree(git_repo, created.path, owned=True)

    assert status == "kept"
    assert created.path.is_dir()


@pytest.mark.asyncio
async def test_remove_deletes_only_merged_legacy_internal_branch(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    dest = planned_worktree_path(git_repo, "thr_legacy")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(git_repo, "worktree", "add", "-b", "ds/thr_legacy", str(dest), "HEAD")

    await remove_managed_worktree(git_repo, dest)

    assert not dest.exists()
    assert not _git_succeeds(
        git_repo, "show-ref", "--verify", "--quiet", "refs/heads/ds/thr_legacy"
    )


@pytest.mark.asyncio
async def test_remove_preserves_legacy_branch_with_unique_commit(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    dest = planned_worktree_path(git_repo, "thr_legacy_unique")
    dest.parent.mkdir(parents=True, exist_ok=True)
    branch = "ds/thr_legacy_unique"
    _git(git_repo, "worktree", "add", "-b", branch, str(dest), "HEAD")
    (dest / "tracked.py").write_text("committed\n", encoding="utf-8")
    _git(dest, "add", "tracked.py")
    _git(dest, "commit", "-m", "agent commit")
    commit = _git(dest, "rev-parse", "HEAD")

    await remove_managed_worktree(git_repo, dest)

    assert not dest.exists()
    assert _git(git_repo, "rev-parse", branch) == commit


@pytest.mark.asyncio
async def test_remove_does_not_bypass_git_worktree_lock(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_locked", copy_tracked_dirty=False
    )
    _git(git_repo, "worktree", "lock", str(created.path))

    with pytest.raises(WorktreeError):
        await remove_managed_worktree(git_repo, created.path)

    assert created.path.is_dir()


@pytest.mark.asyncio
async def test_sync_isolate_preserves_uncheckpointed_isolate_labor(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_sync", copy_tracked_dirty=False)
    (created.path / "tracked.py").write_text("from-isolate\n", encoding="utf-8")
    (git_repo / "tracked.py").write_text("from-claude\n", encoding="utf-8")
    (git_repo / "extra.py").write_text("new\n", encoding="utf-8")
    with pytest.raises(UnpublishedWorktreeError):
        await sync_isolate_from_project(git_repo, created.path)

    assert (created.path / "tracked.py").read_text(encoding="utf-8") == "from-isolate\n"
    assert not (created.path / "extra.py").exists()
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "from-claude\n"


@pytest.mark.asyncio
async def test_sync_isolate_accepts_new_project_dirt_after_clean_sync(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    (git_repo / "tracked.py").write_text("project-dirty-a\n", encoding="utf-8")
    created = await create_managed_worktree(
        git_repo, "thr_project_dirt", copy_tracked_dirty=False
    )

    await sync_isolate_from_project(git_repo, created.path)
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == (
        "project-dirty-a\n"
    )

    (git_repo / "extra.py").write_text("project-dirty-b\n", encoding="utf-8")

    await sync_isolate_from_project(git_repo, created.path)

    assert (created.path / "tracked.py").read_text(encoding="utf-8") == (
        "project-dirty-a\n"
    )
    assert (created.path / "extra.py").read_text(encoding="utf-8") == (
        "project-dirty-b\n"
    )


@pytest.mark.skipif(os.name == "nt", reason="executable mode is a POSIX concept")
@pytest.mark.asyncio
async def test_sync_isolate_preserves_uncheckpointed_mode_change(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_mode_labor", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    (created.path / "tracked.py").chmod(0o755)

    with pytest.raises(UnpublishedWorktreeError):
        await sync_isolate_from_project(
            git_repo, created.path, baseline=baseline
        )

    assert (created.path / "tracked.py").stat().st_mode & 0o777 == 0o755
    assert (git_repo / "tracked.py").stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(os.name == "nt", reason="executable mode is a POSIX concept")
@pytest.mark.asyncio
async def test_sync_isolate_copies_project_mode_change(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_project_mode", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    (git_repo / "tracked.py").chmod(0o755)

    await sync_isolate_from_project(
        git_repo, created.path, baseline=baseline
    )

    assert (created.path / "tracked.py").stat().st_mode & 0o777 == 0o755


@pytest.mark.asyncio
async def test_sync_isolate_replaces_file_with_project_directory(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    (git_repo / "node").write_text("old file\n", encoding="utf-8")
    _git(git_repo, "add", "node")
    _git(git_repo, "commit", "-m", "track node file")
    created = await create_managed_worktree(
        git_repo, "thr_type_change", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    (git_repo / "node").unlink()
    (git_repo / "node").mkdir()
    (git_repo / "node" / "child.txt").write_text("new child\n", encoding="utf-8")

    await sync_isolate_from_project(
        git_repo, created.path, baseline=baseline
    )

    assert (created.path / "node").is_dir()
    assert (created.path / "node" / "child.txt").read_text(encoding="utf-8") == (
        "new child\n"
    )


@pytest.mark.asyncio
async def test_sync_advances_detached_baseline_without_fake_dirt(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(git_repo, "thr_advance", copy_tracked_dirty=False)
    (git_repo / "tracked.py").write_text("v2\n", encoding="utf-8")
    _git(git_repo, "add", "tracked.py")
    _git(git_repo, "commit", "-m", "advance project")

    synced_head = await sync_isolate_from_project(git_repo, created.path)

    assert synced_head == _git(git_repo, "rev-parse", "HEAD")
    assert _git(created.path, "rev-parse", "HEAD") == synced_head
    assert _git(created.path, "branch", "--show-current") == ""
    assert _git(created.path, "status", "--porcelain") == ""
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == "v2\n"


@pytest.mark.asyncio
async def test_interrupted_checkout_image_is_a_sync_artifact(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_checkout_journal", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    (git_repo / "tracked.py").write_text("committed target\n", encoding="utf-8")
    _git(git_repo, "add", "tracked.py")
    _git(git_repo, "commit", "-m", "advance project")
    target_head = _git(git_repo, "rev-parse", "HEAD")
    (git_repo / "tracked.py").write_text("project dirty target\n", encoding="utf-8")
    journal: dict[str, object] = {}
    real_overlay = managed_worktree.overlay_working_paths

    def crash_after_checkout(
        _source: Path, dest: Path, _paths: list[str], **_kwargs
    ) -> None:
        assert (dest / "tracked.py").read_text(encoding="utf-8") == (
            "committed target\n"
        )
        raise OSError("simulated crash after checkout")

    monkeypatch.setattr(
        managed_worktree, "overlay_working_paths", crash_after_checkout
    )
    with pytest.raises(OSError, match="simulated crash after checkout"):
        await sync_isolate_from_project(
            git_repo,
            created.path,
            baseline=baseline,
            before_mutation=lambda _baseline, value: journal.update(value),
        )

    assert journal["checkout_target_head"] == target_head
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == (
        "committed target\n"
    )
    recovery = await managed_worktree.worktree_recovery_labor_signatures(
        created.path,
        baseline,
        project_root=git_repo,
        incomplete_sync_journal=journal,
    )
    assert recovery == {}

    monkeypatch.setattr(managed_worktree, "overlay_working_paths", real_overlay)
    await sync_isolate_from_project(
        git_repo,
        created.path,
        baseline=baseline,
        recover_incomplete_sync=True,
        incomplete_sync_journal=journal,
    )

    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == (
        "project dirty target\n"
    )
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == (
        "project dirty target\n"
    )


@pytest.mark.parametrize(
    ("use_worktree", "expected"),
    [(True, "task commit\n"), (False, "v1\n")],
    ids=["use-agent", "keep-project"],
)
@pytest.mark.asyncio
async def test_resolved_detached_commit_is_journaled_across_checkout_crash(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    use_worktree: bool,
    expected: str,
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_committed_journal", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    (created.path / "tracked.py").write_text(
        "task commit\n", encoding="utf-8"
    )
    _git(created.path, "add", "tracked.py")
    _git(created.path, "commit", "-m", "task commit")
    selected = ["tracked.py"]
    source = created.path if use_worktree else git_repo
    dest = git_repo if use_worktree else created.path
    resolved_signatures = await asyncio.to_thread(
        managed_worktree.worktree_path_signatures, source, selected
    )
    applied = await managed_worktree.apply_raw_paths(
        source,
        dest,
        selected,
        expected_source_signatures=resolved_signatures,
    )
    assert applied.applied == selected

    journal: dict[str, object] = {}
    real_overlay = managed_worktree.overlay_working_paths

    def crash_after_checkout(
        _source: Path, dest_path: Path, paths: list[str], **_kwargs
    ) -> None:
        assert paths == selected
        assert _git(dest_path, "rev-parse", "HEAD") == _git(
            git_repo, "rev-parse", "HEAD"
        )
        raise OSError("simulated committed-labor sync crash")

    monkeypatch.setattr(
        managed_worktree, "overlay_working_paths", crash_after_checkout
    )
    with pytest.raises(OSError, match="committed-labor sync crash"):
        await sync_isolate_from_project(
            git_repo,
            created.path,
            baseline=baseline,
            resolved_labor_signatures=resolved_signatures,
            reset_git_state=True,
            before_mutation=lambda _baseline, value: journal.update(value),
        )

    assert set(journal["before"]) == set(selected)
    assert set(journal["target"]) == set(selected)
    assert _git(created.path, "branch", "--show-current") == ""

    monkeypatch.setattr(managed_worktree, "overlay_working_paths", real_overlay)
    await sync_isolate_from_project(
        git_repo,
        created.path,
        baseline=baseline,
        resolved_labor_signatures=resolved_signatures,
        recover_incomplete_sync=True,
        incomplete_sync_journal=journal,
        reset_git_state=True,
    )

    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == expected
    assert (created.path / "tracked.py").read_text(encoding="utf-8") == expected
    assert _git(created.path, "branch", "--show-current") == ""


@pytest.mark.asyncio
async def test_sync_accepts_baseline_delta_already_identical_to_project(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_already_published", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    (git_repo / "tracked.py").write_text("same delivered bytes\n", encoding="utf-8")
    (created.path / "tracked.py").write_text(
        "same delivered bytes\n", encoding="utf-8"
    )
    (git_repo / "project-only.py").write_text("incoming\n", encoding="utf-8")

    await sync_isolate_from_project(
        git_repo, created.path, baseline=baseline
    )

    assert (created.path / "tracked.py").read_text(encoding="utf-8") == (
        "same delivered bytes\n"
    )
    assert (created.path / "project-only.py").read_text(encoding="utf-8") == (
        "incoming\n"
    )


@pytest.mark.asyncio
async def test_recovery_signatures_exclude_paths_matching_project(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_recovery_filter", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    (git_repo / "tracked.py").write_text("already delivered\n", encoding="utf-8")
    (created.path / "tracked.py").write_text(
        "already delivered\n", encoding="utf-8"
    )
    (created.path / "task-only.py").write_text("unpublished\n", encoding="utf-8")

    signatures = await managed_worktree.worktree_recovery_labor_signatures(
        created.path,
        baseline,
        project_root=git_repo,
    )

    assert set(signatures) == {"task-only.py"}


@pytest.mark.asyncio
async def test_resolve_labor_ignores_already_delivered_path(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_resolve_filtered", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    (git_repo / "tracked.py").write_text("already delivered\n", encoding="utf-8")
    (created.path / "tracked.py").write_text(
        "already delivered\n", encoding="utf-8"
    )
    (created.path / "task-only.py").write_text("chosen task\n", encoding="utf-8")
    expected = await managed_worktree.worktree_recovery_labor_signatures(
        created.path,
        baseline,
        project_root=git_repo,
    )

    report = await managed_worktree.resolve_unpublished_worktree_labor(
        git_repo,
        created.path,
        use_worktree=True,
        labor_paths=["task-only.py"],
        baseline=baseline,
        expected_signatures=expected,
    )

    assert report.applied == ["task-only.py"]
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == (
        "already delivered\n"
    )
    assert (git_repo / "task-only.py").read_text(encoding="utf-8") == (
        "chosen task\n"
    )
    assert (created.path / "task-only.py").read_text(encoding="utf-8") == (
        "chosen task\n"
    )


@pytest.mark.asyncio
async def test_included_ignored_file_participates_in_baseline_and_labor_checks(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    (git_repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    (git_repo / ".worktreeinclude").write_text(".env\n", encoding="utf-8")
    _git(git_repo, "add", ".gitignore", ".worktreeinclude")
    _git(git_repo, "commit", "-m", "include local setup")
    (git_repo / ".env").write_text("TOKEN=project\n", encoding="utf-8")
    created = await create_managed_worktree(
        git_repo, "thr_included_labor", copy_tracked_dirty=False
    )
    baseline = await capture_worktree_baseline(created.path)
    assert baseline.paths[".env"]
    (created.path / ".env").write_text("TOKEN=task\n", encoding="utf-8")

    with pytest.raises(UnpublishedWorktreeError):
        await sync_isolate_from_project(
            git_repo, created.path, baseline=baseline
        )

    status = await reclaim_managed_worktree(
        git_repo, created.path, owned=True
    )
    assert status == "kept"
    assert (created.path / ".env").read_text(encoding="utf-8") == "TOKEN=task\n"
    assert (git_repo / ".env").read_text(encoding="utf-8") == "TOKEN=project\n"

    (created.path / ".env").unlink()
    with pytest.raises(UnpublishedWorktreeError):
        await sync_isolate_from_project(
            git_repo, created.path, baseline=baseline
        )
    assert not (created.path / ".env").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits backslashes in filenames")
@pytest.mark.asyncio
async def test_reclaim_preserves_git_paths_verbatim(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_odd_paths", copy_tracked_dirty=False
    )
    names = [" leading.txt", "trailing.txt ", "literal\\backslash.txt"]
    for name in names:
        (created.path / name).write_text(name, encoding="utf-8")

    status = await reclaim_managed_worktree(
        git_repo, created.path, owned=True
    )

    assert status == "kept"
    for name in names:
        assert (created.path / name).read_text(encoding="utf-8") == name


@pytest.mark.parametrize(
    "failing_prefix",
    [
        ["diff", "--name-only", "-z"],
        ["ls-files", "--others", "--exclude-standard", "-z"],
    ],
    ids=["diff", "ls-files"],
)
@pytest.mark.asyncio
async def test_reclaim_fails_closed_when_git_path_enumeration_fails(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failing_prefix: list[str],
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    created = await create_managed_worktree(
        git_repo, "thr_git_failure", copy_tracked_dirty=False
    )
    (created.path / "labor.py").write_text("keep\n", encoding="utf-8")
    real_git = managed_worktree._git

    async def failing_git(
        root: Path, args: list[str], *, check: bool = True
    ) -> str | None:
        if args[: len(failing_prefix)] == failing_prefix:
            if check:
                raise WorktreeError("injected git path enumeration failure")
            return None
        return await real_git(root, args, check=check)

    monkeypatch.setattr(managed_worktree, "_git", failing_git)

    with pytest.raises(WorktreeError, match="injected git path enumeration failure"):
        await reclaim_managed_worktree(git_repo, created.path, owned=True)

    assert created.path.is_dir()
    assert (created.path / "labor.py").read_text(encoding="utf-8") == "keep\n"
