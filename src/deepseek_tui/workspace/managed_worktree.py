"""Managed git worktrees bound to a thread.

Creates detached checkouts under ``~/.deepseek/worktrees/``. Tools write only
there; a three-way merge publishes onto the project working tree at turn end.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from deepseek_tui.config.paths import user_worktrees_dir
from deepseek_tui.utils import write_text_atomic

logger = logging.getLogger(__name__)

_MAX_TEXT_BYTES = 512 * 1024
_BINARY_SNIFF_BYTES = 8192


class WorktreeError(ValueError):
    """User-facing git / worktree failure."""


class UnpublishedWorktreeError(WorktreeError):
    """An isolate has labor not represented by a publish checkpoint."""


@dataclass(slots=True)
class ManagedWorktree:
    path: Path
    base: str
    owned: bool = True
    dirty_copied: bool = False
    branch: str = ""


@dataclass(slots=True)
class PathImage:
    """One file to publish: ``base`` is turn-start, ``theirs`` is turn-end."""

    path: str
    base: str | None
    theirs: str | None


@dataclass(slots=True)
class ApplyReport:
    applied: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    conflicted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    # path -> (project_pre, project_post) for paths this apply wrote or no-op'd.
    images: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "applied": list(self.applied),
            "merged": list(self.merged),
            "conflicted": list(self.conflicted),
            "skipped": list(self.skipped),
        }


def repo_slug(project_root: Path) -> str:
    root = project_root.expanduser().resolve()
    name = _safe_segment(root.name) or "repo"
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    return f"{name}-{digest}"


def planned_worktree_path(project_root: Path, thread_id: str) -> Path:
    return user_worktrees_dir() / repo_slug(project_root) / _safe_segment(thread_id)


def is_managed_path(path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(user_worktrees_dir().resolve())
    except ValueError:
        return False
    return True


async def is_git_repo(root: Path) -> bool:
    out = await _git(root, ["rev-parse", "--is-inside-work-tree"], check=False)
    return (out or "").strip() == "true"


async def create_managed_worktree(
    project_root: Path,
    thread_id: str,
    *,
    copy_tracked_dirty: bool = True,
) -> ManagedWorktree:
    root = project_root.expanduser().resolve()
    if not await is_git_repo(root):
        raise WorktreeError("workspace is not a git repository")
    head = (await _git(root, ["rev-parse", "HEAD"])).strip()
    if not head:
        raise WorktreeError("workspace has no HEAD commit")
    dest = planned_worktree_path(root, thread_id)
    if dest.exists():
        if await worktree_has_labor(dest):
            raise WorktreeError(
                f"worktree already exists with uncommitted work: {dest}"
            )
        await remove_managed_worktree(root, dest)
    await _git(root, ["worktree", "prune"], check=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        await _git(root, ["worktree", "add", "--detach", str(dest), head])
    except WorktreeError:
        if dest.exists() and not await worktree_has_labor(dest):
            await remove_managed_worktree(root, dest)
        raise
    dirty_copied = False
    if copy_tracked_dirty:
        tracked = await _copy_tracked_dirty(root, dest)
        untracked = await _copy_untracked(root, dest)
        dirty_copied = tracked or untracked
    await _copy_worktree_includes(root, dest)
    return ManagedWorktree(
        path=dest.resolve(),
        base=head,
        owned=True,
        dirty_copied=dirty_copied,
        branch="",
    )


async def remove_managed_worktree(project_root: Path, worktree_path: Path) -> None:
    root = project_root.expanduser().resolve()
    dest = worktree_path.expanduser().resolve()
    if not is_managed_path(dest):
        raise WorktreeError("refusing to remove a worktree outside ~/.deepseek/worktrees")
    branch = await current_worktree_branch(dest) if dest.is_dir() else ""
    if await is_git_repo(root):
        try:
            await _git(root, ["worktree", "remove", "--force", str(dest)])
        except WorktreeError:
            await _git(root, ["worktree", "prune"], check=False)
            if dest.exists():
                raise
    elif dest.exists():
        await asyncio.to_thread(_rmtree, dest)
    if await is_git_repo(root):
        await _git(root, ["worktree", "prune"], check=False)
        await _delete_merged_internal_branch(root, dest, branch)


async def handoff_changes(
    source: Path,
    dest: Path,
    *,
    move: bool = True,
    force: bool = False,
) -> ApplyReport:
    """Copy source working-tree changes onto dest, optionally cleaning source.

    ``base`` is dest HEAD. Conflicts abort all writes unless ``force``.
    """
    from deepseek_tui.workspace.turn_checkpoints import _merge3

    src = source.expanduser().resolve()
    dst = dest.expanduser().resolve()
    if src == dst:
        return ApplyReport()
    dest_head = ((await _git(dst, ["rev-parse", "HEAD"], check=False)) or "").strip()
    paths = await _changed_paths(src, "HEAD")
    planned: list[tuple[str, str | None, str]] = []
    report = ApplyReport()
    for rel in paths:
        theirs = _read_text(src, rel)
        ours = _read_text(dst, rel)
        if theirs is _UNREADABLE or ours is _UNREADABLE:
            if force or ours is None or ours == theirs:
                planned.append((rel, None if theirs is _UNREADABLE else theirs, "applied"))
                continue
            report.conflicted.append(rel)
            continue
        base_text: str | None | object = None
        if dest_head:
            base_text = await _show_at(dst, dest_head, rel)
        if base_text is _UNREADABLE:
            report.skipped.append(rel)
            continue
        status, next_text = await _plan_path(
            base_text if isinstance(base_text, str) or base_text is None else None,
            ours if isinstance(ours, str) or ours is None else None,
            theirs if isinstance(theirs, str) or theirs is None else None,
            mode="merge",
            force=force,
            merge3=_merge3,
        )
        if status == "conflicted":
            report.conflicted.append(rel)
            continue
        if status == "skipped":
            report.skipped.append(rel)
            continue
        planned.append((rel, next_text, status))
    if report.conflicted and not force:
        report.conflicted.sort()
        return report
    for rel, next_text, status in planned:
        theirs = _read_text(src, rel)
        try:
            if theirs is _UNREADABLE:
                _copy_raw(src, dst, rel)
            else:
                _write_text(dst, rel, next_text)
        except OSError:
            logger.debug("worktree_handoff_write_failed path=%s", rel, exc_info=True)
            report.skipped.append(rel)
            continue
        if status == "merged":
            report.merged.append(rel)
        else:
            report.applied.append(rel)
    if move and (report.applied or report.merged):
        await _restore_to_head(src, [rel for rel, _text, _status in planned])
    report.applied.sort()
    report.merged.sort()
    report.conflicted.sort()
    report.skipped.sort()
    return report


def overlay_working_paths(source: Path, dest: Path, paths: list[str]) -> None:
    """Copy ``source``'s current bytes for ``paths`` onto ``dest`` (missing = delete)."""
    src = source.expanduser().resolve()
    dst = dest.expanduser().resolve()
    for rel in paths:
        norm = rel.replace("\\", "/").strip()
        if not norm:
            continue
        theirs = _read_text(src, norm)
        try:
            if theirs is _UNREADABLE:
                _copy_raw(src, dst, norm)
            else:
                _write_text(
                    dst,
                    norm,
                    theirs if isinstance(theirs, str) or theirs is None else None,
                )
        except OSError:
            logger.debug("overlay_working_path_failed path=%s", norm, exc_info=True)


async def sync_isolate_from_project(
    project_root: Path, isolate: Path
) -> str | None:
    """Make the isolate working tree match the current project.

    Turn start copies the project as it is now — including someone else's
    uncommitted files and commits made after the isolate was created.
    Three-way handoff against isolate HEAD is the wrong tool: leftover
    dirty files from a previous publish look like conflicts.
    """
    src = project_root.expanduser().resolve()
    dst = isolate.expanduser().resolve()
    if src == dst:
        head = ((await _git(src, ["rev-parse", "HEAD"], check=False)) or "").strip()
        return head or None
    if await worktree_has_labor(dst) and not await _working_trees_match(src, dst):
        raise UnpublishedWorktreeError(
            f"managed worktree contains unpublished labor: {dst}"
        )
    paths: set[str] = set(await _changed_paths(src, "HEAD"))
    paths.update(await _changed_paths(dst, "HEAD"))
    iso_head = ((await _git(dst, ["rev-parse", "HEAD"], check=False)) or "").strip()
    proj_head = ((await _git(src, ["rev-parse", "HEAD"], check=False)) or "").strip()
    branch = await current_worktree_branch(dst)
    if branch and not _is_legacy_internal_branch(branch, dst):
        # A user-named branch is a durability boundary. Do not silently move it.
        return iso_head or None
    if iso_head and proj_head and iso_head != proj_head:
        reachable = await _git(
            src,
            ["merge-base", "--is-ancestor", iso_head, proj_head],
            check=False,
        )
        if reachable is None:
            # Preserve commits that have not reached the project branch.
            return iso_head
    if iso_head and proj_head and iso_head != proj_head:
        diff = await _git(
            src, ["diff", "--name-only", "-z", iso_head, proj_head], check=False
        )
        for raw in (diff or "").split("\0"):
            path = raw.replace("\\", "/").strip()
            if path:
                paths.add(path)
    if proj_head and (iso_head != proj_head or branch):
        await _git(dst, ["checkout", "--detach", "--force", proj_head])
        if branch:
            await _delete_merged_internal_branch(src, dst, branch)
    overlay_working_paths(src, dst, sorted(paths))
    return proj_head or iso_head or None


async def _working_trees_match(project_root: Path, isolate: Path) -> bool:
    """Compare all paths that differ from either checkout's HEAD."""
    src = project_root.expanduser().resolve()
    dst = isolate.expanduser().resolve()
    paths: set[str] = set(await _changed_paths(src, "HEAD"))
    paths.update(await _changed_paths(dst, "HEAD"))
    src_head = ((await _git(src, ["rev-parse", "HEAD"], check=False)) or "").strip()
    dst_head = ((await _git(dst, ["rev-parse", "HEAD"], check=False)) or "").strip()
    if src_head and dst_head and src_head != dst_head:
        diff = await _git(
            src, ["diff", "--name-only", "-z", dst_head, src_head], check=False
        )
        paths.update(
            path
            for raw in (diff or "").split("\0")
            if (path := raw.replace("\\", "/").strip())
        )
    return all(_raw_same(src, dst, rel) for rel in paths)


async def current_worktree_branch(worktree_path: Path) -> str:
    raw = await _git(
        worktree_path.expanduser().resolve(),
        ["branch", "--show-current"],
        check=False,
    )
    return (raw or "").strip()


async def promote_worktree_branch(worktree_path: Path, branch: str) -> str:
    """Name the isolate checkout as a local branch. Does not push."""
    tree = worktree_path.expanduser().resolve()
    name = _branch_name(branch)
    if not name:
        raise WorktreeError("branch name is required")
    current = await current_worktree_branch(tree)
    if current == name:
        return name
    exists = await _git(
        tree, ["show-ref", "--verify", "--quiet", f"refs/heads/{name}"], check=False
    )
    # show-ref --quiet: success → stdout empty string; missing ref → None.
    if exists is not None:
        raise WorktreeError(f"branch already exists: {name}")
    if current:
        await _git(tree, ["branch", "-m", name])
        return name
    await _git(tree, ["checkout", "-b", name])
    return name


def prune_orphaned_worktrees(owned_paths: list[str]) -> int:
    """Reclaim unreferenced *owned* worktrees that have no uncommitted labor.

    Never rmtree a path outside ``~/.deepseek/worktrees``, a folder that is
    not a git worktree, or a checkout with uncommitted work or unreachable
    detached commits. Such orphans stay on disk.
    """
    root = user_worktrees_dir()
    if not root.is_dir():
        return 0
    owned = {
        Path(raw).expanduser().resolve()
        for raw in owned_paths
        if (raw or "").strip()
    }
    removed = 0
    for repo_dir in list(root.iterdir()):
        if not repo_dir.is_dir():
            continue
        for child in list(repo_dir.iterdir()):
            if not child.is_dir():
                continue
            resolved = child.resolve()
            if resolved in owned:
                continue
            if not is_managed_path(resolved):
                continue
            if not _is_git_worktree_sync(resolved):
                continue
            if _has_labor_sync(resolved):
                continue
            if _remove_clean_worktree_sync(resolved):
                removed += 1
        try:
            next(repo_dir.iterdir())
        except StopIteration:
            repo_dir.rmdir()
        except OSError:
            pass
    return removed


def cleanup_legacy_internal_branch(
    project_root: Path, worktree_path: Path, branch: str
) -> bool:
    """Delete a recorded legacy isolate branch after its worktree disappeared.

    The exact generated name must match the recorded managed path, and Git
    must prove that the branch is already contained by the project's HEAD.
    """
    root = project_root.expanduser().resolve()
    dest = worktree_path.expanduser().resolve()
    if dest.exists() or not is_managed_path(dest):
        return False
    if not _is_legacy_internal_branch(branch, dest):
        return False
    before = _branch_exists_sync(root, branch)
    if not before:
        return False
    try:
        _delete_merged_internal_branch_sync(root, dest, branch)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return not _branch_exists_sync(root, branch)


async def apply_worktree(
    project_root: Path,
    worktree_path: Path,
    base: str,
    *,
    mode: str = "merge",
    force: bool = False,
    preview: bool = False,
) -> ApplyReport:
    """Copy worktree changes onto ``project_root``.

    ``merge`` (default): three-way vs ``base``. ``overwrite``: take worktree.
    """
    from deepseek_tui.workspace.turn_checkpoints import _merge3

    project = project_root.expanduser().resolve()
    tree = worktree_path.expanduser().resolve()
    if mode not in {"merge", "overwrite"}:
        raise WorktreeError(f"apply mode must be merge or overwrite, got {mode!r}")
    paths = await _changed_paths(tree, base)
    report = ApplyReport()
    planned: list[tuple[str, str | None, str]] = []
    raw_copies: list[str] = []
    for rel in paths:
        theirs = _read_text(tree, rel)
        ours = _read_text(project, rel)
        if theirs is _UNREADABLE or ours is _UNREADABLE:
            same = _raw_same(tree, project, rel)
            if force or mode == "overwrite" or ours is None or same:
                raw_copies.append(rel)
            else:
                report.conflicted.append(rel)
            continue
        base_text = await _show_at(project, base, rel)
        if base_text is _UNREADABLE:
            report.skipped.append(rel)
            continue
        status, next_text = await _plan_path(
            base_text, ours, theirs, mode=mode, force=force, merge3=_merge3
        )
        if status == "conflicted":
            report.conflicted.append(rel)
            continue
        if status == "skipped":
            report.skipped.append(rel)
            continue
        if next_text == ours:
            if status == "merged":
                report.merged.append(rel)
            else:
                report.applied.append(rel)
            continue
        planned.append((rel, next_text, status))
    abort_writes = bool(report.conflicted) and not force
    if preview or abort_writes:
        if preview:
            report.applied.extend(raw_copies)
            for rel, _next_text, status in planned:
                if status == "merged":
                    report.merged.append(rel)
                else:
                    report.applied.append(rel)
        else:
            # All-or-nothing publish: conflicts mean nothing is written.
            report.applied.clear()
            report.merged.clear()
        report.applied.sort()
        report.merged.sort()
        report.conflicted.sort()
        report.skipped.sort()
        return report
    for rel in raw_copies:
        try:
            _copy_raw(tree, project, rel)
        except OSError:
            logger.debug("worktree_apply_copy_failed path=%s", rel, exc_info=True)
            report.skipped.append(rel)
            continue
        report.applied.append(rel)
    for rel, next_text, status in planned:
        try:
            _write_text(project, rel, next_text)
        except OSError:
            logger.debug("worktree_apply_write_failed path=%s", rel, exc_info=True)
            report.skipped.append(rel)
            continue
        if status == "merged":
            report.merged.append(rel)
        else:
            report.applied.append(rel)
    report.applied.sort()
    report.merged.sort()
    report.conflicted.sort()
    report.skipped.sort()
    return report


async def apply_path_images(
    project_root: Path,
    images: list[PathImage],
    *,
    force: bool = False,
    preview: bool = False,
) -> ApplyReport:
    """Three-way publish of captured turn images onto ``project_root``.

    All-or-nothing: any conflict (unless ``force``) writes nothing. Failed
    writes after a successful plan roll back using captured project pre-images.
    """
    from deepseek_tui.workspace.turn_checkpoints import _merge3

    project = project_root.expanduser().resolve()
    report = ApplyReport()
    planned: list[tuple[str, str | None, str, str | None]] = []
    for item in images:
        rel = item.path.replace("\\", "/").strip()
        if not rel:
            continue
        ours = _read_text(project, rel)
        if ours is _UNREADABLE:
            report.skipped.append(rel)
            continue
        ours_text = ours if isinstance(ours, str) or ours is None else None
        status, next_text = await _plan_path(
            item.base,
            ours_text,
            item.theirs,
            mode="merge",
            force=force,
            merge3=_merge3,
        )
        if status == "conflicted":
            report.conflicted.append(rel)
            continue
        if status == "skipped":
            report.skipped.append(rel)
            continue
        planned.append((rel, next_text, status, ours_text))
        report.images[rel] = (ours_text, next_text)
    if (report.conflicted or report.skipped) and not force:
        report.applied.clear()
        report.merged.clear()
        report.images.clear()
        report.conflicted.sort()
        report.skipped.sort()
        return report
    if preview:
        for rel, _next_text, status, _ours in planned:
            if status == "merged":
                report.merged.append(rel)
            else:
                report.applied.append(rel)
        report.applied.sort()
        report.merged.sort()
        report.conflicted.sort()
        report.skipped.sort()
        return report
    written: list[tuple[str, str | None]] = []
    try:
        for rel, next_text, status, ours_text in planned:
            if next_text == ours_text:
                if status == "merged":
                    report.merged.append(rel)
                else:
                    report.applied.append(rel)
                continue
            _write_text(project, rel, next_text)
            written.append((rel, ours_text))
            if status == "merged":
                report.merged.append(rel)
            else:
                report.applied.append(rel)
    except OSError:
        for rel, previous in reversed(written):
            try:
                _write_text(project, rel, previous)
            except OSError:
                logger.debug("worktree_apply_rollback_failed path=%s", rel, exc_info=True)
        report.applied.clear()
        report.merged.clear()
        report.images.clear()
        report.skipped.extend(rel for rel, _prev in written)
        logger.debug("worktree_apply_atomic_failed", exc_info=True)
    report.applied.sort()
    report.merged.sort()
    report.conflicted.sort()
    report.skipped.sort()
    return report


async def apply_raw_paths(
    source_root: Path, project_root: Path, paths: list[str]
) -> ApplyReport:
    """Atomically take selected opaque paths from an isolate.

    Used only after an explicit ``use_agent`` conflict decision for files
    that cannot participate in text three-way merge (binary, oversized, or
    conservatively attributed paths). Destination pre-images are backed up
    first so a failed copy restores the whole batch.
    """
    return await asyncio.to_thread(
        _apply_raw_paths_sync,
        source_root.expanduser().resolve(),
        project_root.expanduser().resolve(),
        paths,
    )


def _apply_raw_paths_sync(source: Path, dest: Path, paths: list[str]) -> ApplyReport:
    report = ApplyReport()
    normalized: list[str] = []
    for raw in paths:
        rel = raw.replace("\\", "/").strip()
        candidate = Path(rel)
        if (
            not rel
            or candidate.is_absolute()
            or ".." in candidate.parts
            or rel in normalized
        ):
            if rel:
                report.skipped.append(rel)
            continue
        src = source / rel
        if src.exists() and src.is_dir():
            report.skipped.append(rel)
            continue
        normalized.append(rel)
    if report.skipped:
        report.skipped.sort()
        return report

    with tempfile.TemporaryDirectory(prefix="dstui-raw-apply-") as raw_tmp:
        backup = Path(raw_tmp)
        try:
            for rel in normalized:
                target = dest / rel
                if target.exists():
                    _copy_raw(dest, backup, rel)
            for rel in normalized:
                _copy_raw(source, dest, rel)
        except OSError:
            logger.debug("worktree_raw_apply_failed", exc_info=True)
            for rel in reversed(normalized):
                try:
                    # Missing from the backup means it was absent before.
                    _copy_raw(backup, dest, rel)
                except OSError:
                    logger.debug(
                        "worktree_raw_apply_rollback_failed path=%s", rel, exc_info=True
                    )
            report.skipped = sorted(normalized)
            return report
    report.applied = sorted(normalized)
    return report


async def worktree_has_labor(path: Path) -> bool:
    dest = path.expanduser()
    if not dest.is_dir():
        return False
    return await asyncio.to_thread(_has_labor_sync, dest.resolve())


async def resolve_unpublished_worktree_labor(
    project_root: Path,
    worktree_path: Path,
    *,
    use_worktree: bool,
) -> ApplyReport:
    """Resolve dirty isolate files that have no turn checkpoint.

    This is an explicit recovery path. Choosing the worktree copies its dirty
    files to the project first; choosing the project discards those isolate
    files. In both cases the isolate is then re-synced to the canonical project.
    """
    project = project_root.expanduser().resolve()
    tree = worktree_path.expanduser().resolve()
    labor_paths = await _changed_paths(tree, "HEAD")
    if not labor_paths:
        raise UnpublishedWorktreeError(
            f"managed worktree labor could not be enumerated: {tree}"
        )

    report = ApplyReport()
    if use_worktree:
        report = await handoff_changes(tree, project, move=False, force=True)
        if report.conflicted or report.skipped:
            return report
    else:
        report.applied = sorted(labor_paths)

    # The selected version is durable in the project (or was already there),
    # so the stale isolate copy can now be cleared without losing user work.
    await _restore_to_head(tree, labor_paths)
    await sync_isolate_from_project(project, tree)
    return report


async def reclaim_managed_worktree(
    project_root: Path, worktree_path: Path, *, owned: bool
) -> str:
    """Delete an owned, clean worktree. Dirty or unowned paths are left.

    Returns ``removed``, ``kept``, ``skipped``, or ``gone``.
    """
    dest = worktree_path.expanduser().resolve()
    if not owned:
        return "skipped"
    if not is_managed_path(dest):
        return "skipped"
    if not dest.exists():
        return "gone"
    if await worktree_has_labor(dest):
        if await asyncio.to_thread(_detached_head_is_unreachable_sync, dest):
            return "kept"
        if not await _working_trees_match(project_root, dest):
            return "kept"
        # A legacy isolate can look dirty only because its HEAD predates the
        # project. Move the baseline before reclaiming; identical project dirt
        # remains safe because the canonical copy is already in the project.
        await sync_isolate_from_project(project_root, dest)
        if not await _working_trees_match(project_root, dest):
            return "kept"
    await remove_managed_worktree(project_root, dest)
    return "removed"


async def _plan_path(
    base: str | None,
    ours: str | None,
    theirs: str | None,
    *,
    mode: str,
    force: bool,
    merge3: object,
) -> tuple[str, str | None]:
    if ours == theirs:
        return "applied", ours
    if mode == "overwrite" or force:
        return "applied", theirs
    if ours == base:
        return "applied", theirs
    if theirs == base:
        return "applied", ours
    if isinstance(base, str) and isinstance(ours, str) and isinstance(theirs, str):
        merged = await merge3(base=base, ours=ours, theirs=theirs)  # type: ignore[operator]
        if merged is not None:
            return "merged", merged
    return "conflicted", ours


async def _copy_tracked_dirty(project: Path, worktree: Path) -> bool:
    patch = await _git(project, ["diff", "--binary", "HEAD"], check=False)
    if not (patch or "").strip():
        return False
    def _apply() -> bool:
        try:
            proc = subprocess.run(
                ["git", "apply", "--binary", "-"],
                cwd=str(worktree),
                input=patch,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    ok = await asyncio.to_thread(_apply)
    if not ok:
        logger.debug("worktree_copy_dirty_failed dest=%s", worktree)
    return ok


async def _copy_untracked(source: Path, dest: Path) -> bool:
    listed = await _git(
        source,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        check=False,
    )
    copied = False
    for raw in (listed or "").split("\0"):
        rel = raw.replace("\\", "/").strip()
        if not rel:
            continue
        try:
            _copy_raw(source, dest, rel)
        except OSError:
            logger.debug("worktree_copy_untracked_failed path=%s", rel, exc_info=True)
            continue
        copied = True
    return copied


async def _copy_worktree_includes(source: Path, dest: Path) -> bool:
    """Copy explicitly selected ignored setup files into a new worktree."""
    include_file = source / ".worktreeinclude"
    if not include_file.is_file():
        return False
    listed = await _git(
        source,
        [
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-from=.worktreeinclude",
            "-z",
        ],
        check=False,
    )
    copied = False
    for raw in (listed or "").split("\0"):
        rel = raw.replace("\\", "/").strip()
        if not rel:
            continue
        src = source / rel
        target = dest / rel
        # Setup copies never follow symlinks and never replace checkout files.
        if src.is_symlink() or target.exists():
            continue
        ignored = await _git(
            source, ["check-ignore", "--quiet", "--", rel], check=False
        )
        if ignored is None:
            continue
        try:
            _copy_raw(source, dest, rel)
        except OSError:
            logger.debug("worktree_include_copy_failed path=%s", rel, exc_info=True)
            continue
        copied = True
    return copied


def _raw_same(source: Path, dest: Path, rel: str) -> bool:
    src = source / rel
    dst = dest / rel
    try:
        if not src.exists() and not dst.exists():
            return True
        if src.exists() != dst.exists() or src.is_dir() != dst.is_dir():
            return False
        if src.is_dir():
            return True
        return src.read_bytes() == dst.read_bytes()
    except OSError:
        return False


def _copy_raw(source: Path, dest: Path, rel: str) -> None:
    import shutil

    src = (source / rel).resolve()
    dst = (dest / rel).resolve()
    src.relative_to(source)
    dst.relative_to(dest)
    if not src.exists():
        dst.unlink(missing_ok=True)
        return
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", dir=str(dst.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


async def _restore_to_head(root: Path, paths: list[str]) -> None:
    if not paths:
        return
    untracked = {
        p.replace("\\", "/")
        for p in (
            (
                await _git(
                    root,
                    ["ls-files", "--others", "--exclude-standard", "-z"],
                    check=False,
                )
                or ""
            ).split("\0")
        )
        if p.strip()
    }
    tracked = [p for p in paths if p not in untracked]
    if tracked:
        await _git(root, ["checkout", "HEAD", "--", *tracked], check=False)
    for rel in paths:
        if rel in untracked:
            try:
                (root / rel).unlink(missing_ok=True)
            except OSError:
                logger.debug("worktree_handoff_unlink_failed path=%s", rel, exc_info=True)


def _is_git_worktree_sync(path: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _has_labor_sync(path: Path) -> bool:
    if not _is_git_worktree_sync(path):
        return False
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    if proc.returncode != 0 or proc.stdout.strip():
        return True
    return _detached_head_is_unreachable_sync(path)


def _detached_head_is_unreachable_sync(path: Path) -> bool:
    """Return true only for a detached HEAD not protected by a durable ref."""
    try:
        current = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        name = (current.stdout or "").strip()
        if name:
            return False
        refs = subprocess.run(
            [
                "git",
                "for-each-ref",
                "--contains",
                "HEAD",
                "--format=%(refname)",
                "refs/heads",
                "refs/remotes",
                "refs/tags",
            ],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return refs.returncode != 0 or not (refs.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return True


def _remove_clean_worktree_sync(path: Path) -> bool:
    if _has_labor_sync(path) or not is_managed_path(path):
        return False
    project = _project_from_worktree_sync(path)
    if project is not None:
        branch = _current_branch_sync(path)
        try:
            removed = subprocess.run(
                ["git", "worktree", "remove", str(path)],
                cwd=str(project),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if removed.returncode != 0:
                return False
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=str(project),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            _delete_merged_internal_branch_sync(project, path, branch)
        except (OSError, subprocess.TimeoutExpired):
            return False
    if path.exists():
        return False
    return True


def _current_branch_sync(path: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _is_legacy_internal_branch(branch: str, path: Path) -> bool:
    prefix = "ds/"
    if not branch.startswith(prefix):
        return False
    tail = branch[len(prefix) :]
    expected = path.name
    if tail == expected:
        return True
    suffix = (
        tail.removeprefix(f"{expected}-")
        if tail.startswith(f"{expected}-")
        else ""
    )
    return len(suffix) == 6 and all(ch in "0123456789abcdef" for ch in suffix.lower())


def _branch_exists_sync(project: Path, branch: str) -> bool:
    try:
        probe = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


async def _delete_merged_internal_branch(
    project: Path, worktree: Path, branch: str
) -> None:
    if not _is_legacy_internal_branch(branch, worktree):
        return
    merged = await _git(
        project,
        ["merge-base", "--is-ancestor", f"refs/heads/{branch}", "HEAD"],
        check=False,
    )
    if merged is not None:
        await _git(project, ["branch", "-d", branch], check=False)


def _delete_merged_internal_branch_sync(
    project: Path, worktree: Path, branch: str
) -> None:
    if not _is_legacy_internal_branch(branch, worktree):
        return
    merged = subprocess.run(
        ["git", "merge-base", "--is-ancestor", f"refs/heads/{branch}", "HEAD"],
        cwd=str(project),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if merged.returncode != 0:
        return
    subprocess.run(
        ["git", "branch", "-d", branch],
        cwd=str(project),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _project_from_worktree_sync(path: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    common = Path((proc.stdout or "").strip())
    if not common.is_absolute():
        common = (path / common).resolve()
    git_dir = common
    if git_dir.name != ".git":
        git_dir = git_dir.parent.parent
    if git_dir.name != ".git":
        return None
    return git_dir.parent


def _branch_name(raw: str) -> str:
    text = (raw or "").strip().replace(" ", "-")
    cleaned = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "/", "."} else "-" for ch in text
    )
    cleaned = "/".join(part.strip(".-") for part in cleaned.split("/") if part.strip(".-"))
    if cleaned.startswith("-") or ".." in cleaned:
        return ""
    return cleaned[:120]


async def _changed_paths(worktree: Path, base: str) -> list[str]:
    diff = await _git(
        worktree, ["diff", "--name-only", "-z", base], check=False
    )
    extra = await _git(
        worktree,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        check=False,
    )
    seen: set[str] = set()
    out: list[str] = []
    for raw in ((diff or "") + "\0" + (extra or "")).split("\0"):
        path = raw.replace("\\", "/").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


async def _show_at(root: Path, rev: str, rel: str) -> str | None | object:
    out = await _git(root, ["show", f"{rev}:{rel}"], check=False)
    if out is None:
        # Missing from the commit (new file) — treat as absent, not unreadable.
        probe = await _git(
            root, ["cat-file", "-e", f"{rev}:{rel}"], check=False
        )
        if probe is None:
            return None
        return _UNREADABLE
    if "\0" in out[:_BINARY_SNIFF_BYTES]:
        return _UNREADABLE
    return out


def _read_text(root: Path, rel: str) -> str | None | object:
    path = root / rel
    try:
        if path.stat().st_size > _MAX_TEXT_BYTES:
            return _UNREADABLE
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:_BINARY_SNIFF_BYTES]:
        return _UNREADABLE
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return _UNREADABLE


def _write_text(root: Path, rel: str, content: str | None) -> None:
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise OSError(f"apply path escapes project: {rel!r}") from exc
    if content is None:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(target, content)


def _safe_segment(raw: str) -> str:
    text = (raw or "").strip()
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in text)
    cleaned = cleaned.strip(".-")
    return cleaned[:80]


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


async def _git(root: Path, args: list[str], *, check: bool = True) -> str | None:
    def _run() -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, "", str(exc)
        return proc.returncode, proc.stdout, proc.stderr

    code, out, err = await asyncio.to_thread(_run)
    if code != 0:
        if check:
            raise WorktreeError((err or out or f"git {' '.join(args)} failed").strip())
        return None
    return out


_UNREADABLE = object()

read_working_text = _read_text
write_working_text = _write_text
