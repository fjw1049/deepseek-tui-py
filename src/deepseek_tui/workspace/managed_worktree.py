"""Managed git worktrees bound to a thread.

Creates detached checkouts under ``~/.deepseek/worktrees/``. Tools write only
there; a three-way merge publishes onto the project working tree at turn end.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from deepseek_tui.config.paths import user_worktrees_dir
from deepseek_tui.utils import write_text_atomic

logger = logging.getLogger(__name__)

_MAX_TEXT_BYTES = 512 * 1024
_BINARY_SNIFF_BYTES = 8192
_T = TypeVar("_T")


async def _to_thread_complete(
    func: Callable[..., _T], /, *args: object, **kwargs: object
) -> _T:
    """Do not release an outer lease while an uncancellable worker still runs."""
    worker = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # ``to_thread`` cannot stop a running function. Delay propagation until
        # it has finished so callers' lease/context-manager cleanup cannot race
        # the filesystem or Git mutation that is still happening in the worker.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if worker.done() and not worker.cancelled():
            try:
                worker.result()
            except BaseException:
                pass
        raise


def _normalize_worktree_path(path: str) -> str:
    """Normalize separators without changing a legal POSIX filename."""
    return path.replace("\\", "/") if os.name == "nt" else path


def _parse_git_paths(output: str) -> list[str]:
    """Parse a NUL-delimited Git path list without trimming path bytes."""
    return [
        _normalize_worktree_path(path)
        for path in output.split("\0")
        if path != ""
    ]


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
class WorktreeBaseline:
    """Durable identity of the isolate state last copied from the project."""

    head: str
    paths: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {"head": self.head, "paths": dict(self.paths)}

    @classmethod
    def from_dict(cls, raw: dict[str, object] | None) -> WorktreeBaseline | None:
        if not raw:
            return None
        head = raw.get("head")
        paths = raw.get("paths")
        if not isinstance(head, str) or not isinstance(paths, dict):
            return None
        normalized = {
            _normalize_worktree_path(str(path)): signature
            for path, signature in paths.items()
            if isinstance(signature, str)
        }
        if len(normalized) != len(paths):
            return None
        return cls(head=head, paths=normalized)


@dataclass(slots=True)
class PathImage:
    """One file to publish: ``base`` is turn-start, ``theirs`` is turn-end."""

    path: str
    base: str | None
    theirs: str | None


@dataclass(slots=True, frozen=True)
class RawPathImage:
    """Immutable regular-file, symlink, or missing path image.

    ``payload_path`` points at a durable checkpoint sidecar.  File payloads are
    stored as bytes; symlink payloads store the link target bytes.  Missing
    images have no payload.
    """

    path: str
    kind: str
    mode: int | None
    signature: str
    payload_path: Path | None = None


@dataclass(slots=True)
class ApplyReport:
    applied: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    conflicted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    # path -> (project_pre, project_post) for paths this apply wrote or no-op'd.
    images: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    # Exact signatures after a successful text apply, used to CAS a rollback.
    post_signatures: dict[str, str] = field(default_factory=dict)

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
        await _to_thread_complete(_rmtree, dest)
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


def overlay_working_paths(
    source: Path,
    dest: Path,
    paths: list[str],
    *,
    expected_source_signatures: dict[str, str] | None = None,
) -> None:
    """Copy ``source``'s current bytes for ``paths`` onto ``dest`` (missing = delete)."""
    src = source.expanduser().resolve()
    dst = dest.expanduser().resolve()
    report = _apply_raw_paths_sync(
        src,
        dst,
        paths,
        expected_source_signatures,
        allow_directories=True,
    )
    if report.conflicted:
        raise UnpublishedWorktreeError(
            "workspace source changed during sync: "
            + ", ".join(report.conflicted)
        )
    if report.skipped:
        raise OSError(
            "could not sync workspace paths: " + ", ".join(report.skipped)
        )


async def overlay_working_paths_async(
    source: Path,
    dest: Path,
    paths: list[str],
    *,
    expected_source_signatures: dict[str, str] | None = None,
) -> None:
    """Run :func:`overlay_working_paths` without blocking the event loop."""
    await _to_thread_complete(
        overlay_working_paths,
        source,
        dest,
        paths,
        expected_source_signatures=expected_source_signatures,
    )


def paths_requiring_raw_resolution(
    source: Path, dest: Path, paths: list[str]
) -> list[str]:
    """Return paths whose filesystem identity cannot be text-merged safely."""
    src_root = source.expanduser().resolve()
    dst_root = dest.expanduser().resolve()
    unsafe: list[str] = []
    for rel in paths:
        norm = _normalize_worktree_path(rel)
        if not norm:
            continue
        try:
            src_info = (src_root / norm).lstat()
        except FileNotFoundError:
            src_info = None
        except OSError:
            unsafe.append(norm)
            continue
        try:
            dst_info = (dst_root / norm).lstat()
        except FileNotFoundError:
            dst_info = None
        except OSError:
            unsafe.append(norm)
            continue
        if src_info is None and dst_info is None:
            continue
        if src_info is None:
            # Text images can safely plan a regular-file deletion. A symlink,
            # directory, or special target must be removed as an exact path.
            if dst_info is not None and not stat.S_ISREG(dst_info.st_mode):
                unsafe.append(norm)
            continue
        if dst_info is None:
            # Raw creation preserves symlink identity and regular-file mode.
            unsafe.append(norm)
            continue
        src_type = stat.S_IFMT(src_info.st_mode)
        dst_type = stat.S_IFMT(dst_info.st_mode)
        if (
            src_type != stat.S_IFREG
            or dst_type != stat.S_IFREG
            or stat.S_IMODE(src_info.st_mode) != stat.S_IMODE(dst_info.st_mode)
        ):
            unsafe.append(norm)
    return sorted(set(unsafe))


async def capture_worktree_baseline(worktree: Path) -> WorktreeBaseline:
    """Capture the isolate state that is known to have come from the project."""
    root = worktree.expanduser().resolve()
    head = ((await _git(root, ["rev-parse", "HEAD"], check=False)) or "").strip()
    paths = await _changed_paths(root, "HEAD")
    signatures = await asyncio.to_thread(_path_signatures, root, paths)
    return WorktreeBaseline(head=head, paths=signatures)


async def worktree_matches_baseline(
    worktree: Path, baseline: WorktreeBaseline
) -> bool:
    current = await capture_worktree_baseline(worktree)
    return current == baseline


async def worktree_changes_since_baseline(
    worktree: Path, baseline: WorktreeBaseline | None
) -> list[str]:
    """Paths changed by the isolate since its last project-seeded state."""
    root = worktree.expanduser().resolve()
    if baseline is None:
        return sorted(await _changed_paths(root, "HEAD"))
    current = await capture_worktree_baseline(root)
    changed = {
        path
        for path in set(baseline.paths) | set(current.paths)
        if baseline.paths.get(path) != current.paths.get(path)
    }
    if baseline.head and current.head and baseline.head != current.head:
        diff = await _git(
            root,
            ["diff", "--name-only", "-z", baseline.head, current.head],
            check=True,
        )
        changed.update(_parse_git_paths(diff or ""))
    return sorted(changed)


async def worktree_change_signatures_since_baseline(
    worktree: Path, baseline: WorktreeBaseline
) -> dict[str, str]:
    """Exact T-B snapshot used to bind a recovery choice to shown bytes."""
    root = worktree.expanduser().resolve()
    paths = await worktree_changes_since_baseline(root, baseline)
    return await asyncio.to_thread(_path_signatures, root, paths)


def _incomplete_sync_path_signatures(
    journal: dict[str, object] | None,
) -> tuple[dict[str, str], dict[str, str]] | None:
    """Validate the before/target images from an interrupted inbound sync."""
    before = journal.get("before") if isinstance(journal, dict) else None
    target = journal.get("target") if isinstance(journal, dict) else None
    if not isinstance(before, dict) or not isinstance(target, dict):
        return None
    before_signatures = {
        _normalize_worktree_path(path): signature
        for path, signature in before.items()
        if isinstance(path, str) and isinstance(signature, str)
    }
    target_signatures = {
        _normalize_worktree_path(path): signature
        for path, signature in target.items()
        if isinstance(path, str) and isinstance(signature, str)
    }
    if (
        len(before_signatures) != len(before)
        or len(target_signatures) != len(target)
    ):
        return None
    return before_signatures, target_signatures


async def _clean_checkout_target_paths(
    worktree: Path,
    journal: dict[str, object] | None,
    paths: set[str],
) -> set[str]:
    """Paths that still exactly match the journaled checkout commit.

    Moving the isolate HEAD with ``checkout --force`` creates a durable middle
    state before project dirty bytes are overlaid.  The commit SHA is itself the
    content-addressed image; a path belongs to that image only while the current
    HEAD is that exact SHA and Git still reports the path clean against HEAD.
    """
    checkout_head = None
    if isinstance(journal, dict):
        checkout_head = journal.get("checkout_target_head") or journal.get(
            "target_head"
        )
    if not isinstance(checkout_head, str) or not checkout_head or not paths:
        return set()
    current_head = (
        (await _git(worktree, ["rev-parse", "HEAD"], check=False)) or ""
    ).strip()
    if current_head != checkout_head:
        return set()
    changed_from_head = set(await _changed_paths(worktree, "HEAD"))
    return paths.difference(changed_from_head)


async def worktree_recovery_labor_signatures(
    worktree: Path,
    baseline: WorktreeBaseline,
    *,
    project_root: Path | None = None,
    incomplete_sync_journal: dict[str, object] | None = None,
) -> dict[str, str]:
    """Return only task/third-state bytes that require a recovery decision.

    During interrupted project -> isolate synchronization, a path matching its
    journaled pre-sync or target image is a synchronization artifact, not task
    labor. An unjournaled path or any third image remains user-owned evidence.
    """
    root = worktree.expanduser().resolve()
    paths = await worktree_changes_since_baseline(root, baseline)
    current = await asyncio.to_thread(_path_signatures, root, paths)
    if project_root is not None:
        project = project_root.expanduser().resolve()
        current = {
            path: signature
            for path, signature in current.items()
            if not _raw_same(project, root, path)
        }
    journal_images = _incomplete_sync_path_signatures(incomplete_sync_journal)
    if journal_images is None:
        return current
    before, target = journal_images
    journal_paths = set(before) | set(target)
    checkout_target = await _clean_checkout_target_paths(
        root,
        incomplete_sync_journal,
        set(current).intersection(journal_paths),
    )
    return {
        path: signature
        for path, signature in current.items()
        if path not in journal_paths
        or (
            signature not in {before.get(path), target.get(path)}
            and path not in checkout_target
        )
    }


async def sync_isolate_from_project(
    project_root: Path,
    isolate: Path,
    *,
    baseline: WorktreeBaseline | None = None,
    resolved_labor_paths: list[str] | None = None,
    resolved_labor_signatures: dict[str, str] | None = None,
    recover_incomplete_sync: bool = False,
    incomplete_sync_journal: dict[str, object] | None = None,
    discard_isolate_labor: bool = False,
    reset_git_state: bool = False,
    before_mutation: Callable[[WorktreeBaseline, dict[str, object]], None]
    | None = None,
    after_mutation: Callable[[WorktreeBaseline], None] | None = None,
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
    isolate_paths = await _changed_paths(dst, "HEAD")
    isolate_labor = (
        await worktree_changes_since_baseline(dst, baseline)
        if baseline is not None
        else isolate_paths
    )
    if (
        recover_incomplete_sync
        and not discard_isolate_labor
        and not await _incomplete_sync_state_is_safe(
            src,
            dst,
            baseline=baseline,
            isolate_labor=isolate_labor,
            journal=incomplete_sync_journal,
            resolved_labor_signatures=resolved_labor_signatures,
        )
    ):
        raise UnpublishedWorktreeError(
            "managed worktree changed after an interrupted project sync"
        )
    if (
        not (recover_incomplete_sync or discard_isolate_labor)
        and (isolate_labor or await worktree_has_labor(dst))
        and not await _working_trees_match(src, dst)
    ):
        if resolved_labor_paths is not None or resolved_labor_signatures is not None:
            if baseline is None:
                # Legacy isolates have no durable B. After checkpointed paths
                # were applied, accept the old copy only when every dirty byte
                # is already identical to the project. The successful sync
                # immediately establishes B.
                inherited = await _legacy_isolate_labor_matches_project(src, dst)
            else:
                remaining_labor = await worktree_changes_since_baseline(dst, baseline)
                if resolved_labor_signatures is not None:
                    resolved_signatures = {
                        _normalize_worktree_path(path): signature
                        for path, signature in resolved_labor_signatures.items()
                    }
                    current_signatures = await asyncio.to_thread(
                        worktree_path_signatures, dst, remaining_labor
                    )
                    inherited = all(
                        resolved_signatures.get(path) == current_signatures[path]
                        or _raw_same(src, dst, path)
                        for path in remaining_labor
                    )
                else:
                    resolved = {
                        _normalize_worktree_path(path)
                        for path in resolved_labor_paths
                        if path
                    }
                    inherited = set(remaining_labor).issubset(resolved)
        else:
            inherited = (
                all(_raw_same(src, dst, path) for path in isolate_labor)
                if baseline is not None
                else await _legacy_isolate_labor_matches_project(src, dst)
            )
        if not inherited:
            raise UnpublishedWorktreeError(
                f"managed worktree contains unpublished labor: {dst}"
            )
    paths: set[str] = set(await _changed_paths(src, "HEAD"))
    paths.update(await _changed_paths(dst, "HEAD"))
    iso_head = ((await _git(dst, ["rev-parse", "HEAD"], check=False)) or "").strip()
    proj_head = ((await _git(src, ["rev-parse", "HEAD"], check=False)) or "").strip()
    branch = await current_worktree_branch(dst)
    if (
        branch
        and not discard_isolate_labor
        and not reset_git_state
        and not _is_legacy_internal_branch(branch, dst)
    ):
        # A user-named branch is a durability boundary. Do not silently move it.
        return iso_head or None
    if iso_head and proj_head and iso_head != proj_head:
        reachable = await _git(
            src,
            ["merge-base", "--is-ancestor", iso_head, proj_head],
            check=False,
        )
        if reachable is None and not (discard_isolate_labor or reset_git_state):
            # Preserve commits that have not reached the project branch.
            return iso_head
    if iso_head and proj_head and iso_head != proj_head:
        diff = await _git(
            src, ["diff", "--name-only", "-z", iso_head, proj_head], check=True
        )
        paths.update(_parse_git_paths(diff or ""))
    target_baseline = await capture_worktree_baseline(src)
    target_signatures = await asyncio.to_thread(
        _path_signatures, src, sorted(paths)
    )
    if before_mutation is not None:
        journal_baseline = baseline
        if journal_baseline is None:
            baseline_signatures = await asyncio.to_thread(
                _path_signatures, dst, isolate_paths
            )
            journal_baseline = WorktreeBaseline(
                head=iso_head,
                paths=baseline_signatures,
            )
        before_signatures = await asyncio.to_thread(
            _path_signatures, dst, sorted(paths)
        )
        before_mutation(
            journal_baseline,
            {
                "before": before_signatures,
                "target": target_signatures,
                "target_head": proj_head,
                "checkout_target_head": proj_head,
            },
        )
    if proj_head and (iso_head != proj_head or branch):
        await _git(dst, ["checkout", "--detach", "--force", proj_head])
        if branch:
            await _delete_merged_internal_branch(src, dst, branch)
    await overlay_working_paths_async(
        src,
        dst,
        sorted(paths),
        expected_source_signatures=target_signatures,
    )
    synced_baseline = await capture_worktree_baseline(dst)
    if synced_baseline != target_baseline:
        raise UnpublishedWorktreeError(
            "managed worktree changed while project sync was completing"
        )
    if after_mutation is not None:
        after_mutation(target_baseline)
    return proj_head or iso_head or None


async def _incomplete_sync_state_is_safe(
    project: Path,
    isolate: Path,
    *,
    baseline: WorktreeBaseline | None,
    isolate_labor: list[str],
    journal: dict[str, object] | None,
    resolved_labor_signatures: dict[str, str] | None = None,
) -> bool:
    """Prove that current isolate bytes came only from the interrupted sync."""
    journal_images = _incomplete_sync_path_signatures(journal)
    target_head = journal.get("target_head") if isinstance(journal, dict) else None
    if journal_images is None:
        # Compatibility with the short-lived boolean-only journal: only a
        # completely matching copy is safe to adopt without path evidence.
        return await _working_trees_match(project, isolate)
    before_signatures, target_signatures = journal_images
    resolved_signatures = {
        _normalize_worktree_path(path): signature
        for path, signature in (resolved_labor_signatures or {}).items()
    }
    journal_paths = set(before_signatures) | set(target_signatures)
    if not set(isolate_labor).issubset(journal_paths | set(resolved_signatures)):
        return False
    checkout_target = await _clean_checkout_target_paths(
        isolate,
        journal,
        set(isolate_labor).intersection(journal_paths),
    )
    current_signatures = await asyncio.to_thread(
        _path_signatures, isolate, isolate_labor
    )
    for path, current in current_signatures.items():
        if current not in {
            before_signatures.get(path),
            target_signatures.get(path),
            resolved_signatures.get(path),
        } and path not in checkout_target and not _raw_same(project, isolate, path):
            return False
    current_head = (
        (await _git(isolate, ["rev-parse", "HEAD"], check=False)) or ""
    ).strip()
    allowed_heads = {
        head
        for head in (
            baseline.head if baseline is not None else "",
            target_head if isinstance(target_head, str) else "",
        )
        if head
    }
    return bool(current_head and allowed_heads and current_head in allowed_heads)


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
            src, ["diff", "--name-only", "-z", dst_head, src_head], check=True
        )
        paths.update(_parse_git_paths(diff or ""))
    return all(_raw_same(src, dst, rel) for rel in paths)


async def _legacy_isolate_labor_matches_project(
    project_root: Path, isolate: Path
) -> bool:
    """Recognize project-seeded dirt for worktrees created before baselines."""
    src = project_root.expanduser().resolve()
    dst = isolate.expanduser().resolve()
    src_head = ((await _git(src, ["rev-parse", "HEAD"], check=False)) or "").strip()
    dst_head = ((await _git(dst, ["rev-parse", "HEAD"], check=False)) or "").strip()
    if src_head and dst_head and src_head != dst_head:
        reachable = await _git(
            src,
            ["merge-base", "--is-ancestor", dst_head, src_head],
            check=False,
        )
        if reachable is None:
            return False
    paths = await _changed_paths(dst, "HEAD")
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
    force_paths: list[str] | set[str] | None = None,
    preview: bool = False,
    before_write: Callable[
        [dict[str, tuple[str | None, str | None]]], None
    ]
    | None = None,
) -> ApplyReport:
    """Three-way publish of captured turn images onto ``project_root``.

    All-or-nothing: any conflict (unless ``force``) writes nothing. Failed
    writes after a successful plan roll back using captured project pre-images.
    """
    from deepseek_tui.workspace.turn_checkpoints import _merge3

    project = project_root.expanduser().resolve()
    report = ApplyReport()
    forced = {
        _normalize_worktree_path(path) for path in (force_paths or []) if path
    }
    planned: list[tuple[str, str | None, str, str | None, str]] = []
    for item in images:
        rel = _normalize_worktree_path(item.path)
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
            force=force or rel in forced,
            merge3=_merge3,
        )
        if status == "conflicted":
            report.conflicted.append(rel)
            continue
        if status == "skipped":
            report.skipped.append(rel)
            continue
        try:
            ours_signature = _path_signature(_exact_workspace_path(project, rel))
        except OSError:
            report.skipped.append(rel)
            continue
        planned.append((rel, next_text, status, ours_text, ours_signature))
        report.images[rel] = (ours_text, next_text)
    if (report.conflicted or report.skipped) and not force:
        report.applied.clear()
        report.merged.clear()
        report.images.clear()
        report.conflicted.sort()
        report.skipped.sort()
        return report
    if preview:
        for rel, _next_text, status, _ours, _ours_signature in planned:
            if status == "merged":
                report.merged.append(rel)
            else:
                report.applied.append(rel)
        report.applied.sort()
        report.merged.sort()
        report.conflicted.sort()
        report.skipped.sort()
        return report
    if before_write is not None:
        # The caller's journal must be durable before the first project
        # mutation. This also runs for raw-only checkpoints (empty images).
        before_write(dict(report.images))
    stale = [
        rel
        for rel, _next, _status, _ours, signature in planned
        if _path_signature(project / rel) != signature
    ]
    if stale:
        report.images.clear()
        report.conflicted.extend(stale)
        report.conflicted.sort()
        report.skipped.sort()
        return report

    written: list[tuple[str, str | None, str, str]] = []
    outcome_signatures: dict[str, str] = {}
    failed_path: str | None = None
    concurrent_change = False
    for rel, next_text, status, ours_text, ours_signature in planned:
        # A later path may change while an earlier replacement is landing.
        if _path_signature(project / rel) != ours_signature:
            failed_path = rel
            concurrent_change = True
            break
        if next_text == ours_text:
            outcome_signatures[rel] = ours_signature
        else:
            try:
                _write_text(project, rel, next_text)
            except OSError:
                failed_path = rel
                logger.debug(
                    "worktree_apply_write_failed path=%s", rel, exc_info=True
                )
                break
            post_signature = _path_signature(project / rel)
            written.append((rel, ours_text, ours_signature, post_signature))
            if _read_text(project, rel) != next_text:
                failed_path = rel
                concurrent_change = True
                break
            outcome_signatures[rel] = post_signature
        if status == "merged":
            report.merged.append(rel)
        else:
            report.applied.append(rel)

    if failed_path is None:
        changed_after_write = [
            rel
            for rel, expected in outcome_signatures.items()
            if _path_signature(project / rel) != expected
        ]
        if changed_after_write:
            failed_path = changed_after_write[0]
            concurrent_change = True

    if failed_path is not None:
        for rel, previous, previous_signature, post_signature in reversed(written):
            # Never roll back over an edit that arrived after our replacement.
            if _path_signature(project / rel) != post_signature:
                report.skipped.append(rel)
                continue
            try:
                _write_text(project, rel, previous)
            except OSError:
                report.skipped.append(rel)
                logger.debug(
                    "worktree_apply_rollback_failed path=%s", rel, exc_info=True
                )
                continue
            if _path_signature(project / rel) != previous_signature:
                report.skipped.append(rel)
        report.applied.clear()
        report.merged.clear()
        report.images.clear()
        report.skipped.extend(rel for rel, *_rest in planned)
        if concurrent_change:
            report.conflicted.append(failed_path)
        logger.debug("worktree_apply_atomic_failed path=%s", failed_path)
    else:
        report.post_signatures = dict(outcome_signatures)
    report.applied = sorted(set(report.applied))
    report.merged = sorted(set(report.merged))
    report.conflicted = sorted(set(report.conflicted))
    report.skipped = sorted(set(report.skipped))
    return report


async def apply_raw_paths(
    source_root: Path,
    project_root: Path,
    paths: list[str],
    *,
    expected_source_signatures: dict[str, str] | None = None,
) -> ApplyReport:
    """Atomically take selected opaque paths from an isolate.

    Used only after an explicit ``use_agent`` conflict decision for files
    that cannot participate in text three-way merge (binary, oversized, or
    conservatively attributed paths). Destination pre-images are backed up
    first so a failed copy restores the whole batch.
    """
    return await _to_thread_complete(
        _apply_raw_paths_sync,
        source_root.expanduser().resolve(),
        project_root.expanduser().resolve(),
        paths,
        expected_source_signatures,
    )


async def apply_raw_path_images(
    project_root: Path,
    pre_images: list[RawPathImage],
    post_images: list[RawPathImage],
    *,
    target: str = "post",
) -> ApplyReport:
    """Apply a durable raw-image transaction with crash-safe replay.

    Every destination must still equal either its journaled pre-image or
    post-image.  A mixture of those two states is an interrupted transaction
    and is completed idempotently.  A third state is never overwritten.
    Ordinary failures roll every path that still carries the target image back
    to the opposite durable image; a hard process crash can simply replay the
    same call later.
    """

    if target not in {"pre", "post"}:
        raise ValueError("raw image target must be pre or post")
    return await _to_thread_complete(
        _apply_raw_path_images_sync,
        project_root.expanduser().resolve(),
        pre_images,
        post_images,
        target,
    )


async def validate_raw_path_images(
    project_root: Path,
    pre_images: list[RawPathImage],
    post_images: list[RawPathImage],
) -> ApplyReport:
    """Validate durable raw descriptors and sidecars without touching disk."""
    return await _to_thread_complete(
        _validate_raw_path_images_sync,
        project_root.expanduser().resolve(),
        pre_images,
        post_images,
    )


def _validate_raw_path_images_sync(
    dest: Path,
    pre_images: list[RawPathImage],
    post_images: list[RawPathImage],
) -> ApplyReport:
    report = ApplyReport()
    pre = {_normalize_worktree_path(image.path): image for image in pre_images}
    post = {_normalize_worktree_path(image.path): image for image in post_images}
    if (
        len(pre) != len(pre_images)
        or len(post) != len(post_images)
        or set(pre) != set(post)
    ):
        report.skipped = sorted(set(pre) | set(post))
        return report
    paths = sorted(pre)
    for rel in paths:
        if not rel or pre[rel].path != post[rel].path:
            report.skipped.append(rel)
            continue
        try:
            _exact_workspace_path(dest, rel)
        except OSError:
            report.skipped.append(rel)
            continue
        if not _raw_image_is_valid(pre[rel]) or not _raw_image_is_valid(post[rel]):
            report.skipped.append(rel)
    report.skipped = sorted(set(report.skipped))
    if not report.skipped:
        report.applied = paths
    return report


def _apply_raw_path_images_sync(
    dest: Path,
    pre_images: list[RawPathImage],
    post_images: list[RawPathImage],
    target_name: str,
) -> ApplyReport:
    report = _validate_raw_path_images_sync(dest, pre_images, post_images)
    if report.skipped:
        return report
    pre = {_normalize_worktree_path(image.path): image for image in pre_images}
    post = {_normalize_worktree_path(image.path): image for image in post_images}
    paths = sorted(pre)
    report.applied.clear()

    current = _path_signatures(dest, paths)
    third_state = [
        rel
        for rel in paths
        if current[rel] not in {pre[rel].signature, post[rel].signature}
    ]
    if third_state:
        report.conflicted = sorted(third_state)
        return report

    wanted = post if target_name == "post" else pre
    opposite = pre if target_name == "post" else post
    failed_path: str | None = None
    failed_with_error = False
    for rel in paths:
        if _path_signature(dest / rel) == wanted[rel].signature:
            continue
        if _path_signature(dest / rel) != opposite[rel].signature:
            failed_path = rel
            break
        try:
            _write_raw_path_image(dest, wanted[rel])
        except OSError:
            failed_path = rel
            failed_with_error = True
            logger.debug("raw_image_apply_failed path=%s", rel, exc_info=True)
            break
        if _path_signature(dest / rel) != wanted[rel].signature:
            failed_path = rel
            break

    if failed_path is None:
        drifted = [
            rel
            for rel in paths
            if _path_signature(dest / rel) != wanted[rel].signature
        ]
        if drifted:
            failed_path = drifted[0]

    if failed_path is not None:
        rollback_failed: set[str] = set()
        for rel in reversed(paths):
            if pre[rel].signature == post[rel].signature:
                continue
            current_signature = _path_signature(dest / rel)
            if current_signature == opposite[rel].signature:
                continue
            if current_signature != wanted[rel].signature:
                rollback_failed.add(rel)
                continue
            try:
                _write_raw_path_image(dest, opposite[rel])
            except OSError:
                rollback_failed.add(rel)
                logger.debug("raw_image_rollback_failed path=%s", rel, exc_info=True)
                continue
            if _path_signature(dest / rel) != opposite[rel].signature:
                rollback_failed.add(rel)
        if failed_with_error:
            report.skipped = sorted({failed_path, *rollback_failed})
        else:
            report.conflicted = sorted({failed_path, *rollback_failed})
        return report

    report.applied = paths
    report.post_signatures = {
        rel: wanted[rel].signature
        for rel in paths
    }
    return report


def _raw_image_is_valid(image: RawPathImage) -> bool:
    if image.kind == "missing":
        return image.mode is None and image.payload_path is None and image.signature == "missing"
    if image.kind not in {"file", "symlink"} or image.mode is None:
        return False
    payload = image.payload_path
    if payload is None:
        return False
    try:
        info = payload.lstat()
        if not stat.S_ISREG(info.st_mode):
            return False
        hasher = hashlib.sha256()
        with payload.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
    except OSError:
        return False
    return image.signature == f"{image.kind}:{image.mode:o}:{digest}"


def _write_raw_path_image(dest: Path, image: RawPathImage) -> None:
    rel = _normalize_worktree_path(image.path)
    target = _exact_workspace_path(dest, rel)
    try:
        current = target.lstat()
    except FileNotFoundError:
        current = None
    if current is not None and not (
        stat.S_ISREG(current.st_mode) or stat.S_ISLNK(current.st_mode)
    ):
        raise OSError(f"refusing raw image write to unsupported path: {rel!r}")
    if image.kind == "missing":
        target.unlink(missing_ok=True)
        return
    if not _raw_image_is_valid(image) or image.payload_path is None:
        raise OSError(f"invalid raw checkpoint sidecar: {rel!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        if image.kind == "symlink":
            payload = image.payload_path.read_bytes()
            tmp.unlink()
            os.symlink(payload.decode("utf-8", errors="surrogateescape"), tmp)
        else:
            with image.payload_path.open("rb") as source, tmp.open("wb") as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(tmp, int(image.mode))
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def _apply_raw_paths_sync(
    source: Path,
    dest: Path,
    paths: list[str],
    expected_source_signatures: dict[str, str] | None = None,
    *,
    allow_directories: bool = False,
) -> ApplyReport:
    report = ApplyReport()
    candidates: set[str] = set()
    for raw in paths:
        rel = _normalize_worktree_path(raw)
        candidate = Path(rel)
        if (
            not rel
            or candidate.is_absolute()
            or ".." in candidate.parts
            or rel in candidates
        ):
            if rel:
                report.skipped.append(rel)
            continue
        candidates.add(rel)

    normalized: list[str] = []
    terminal_roots: list[Path] = []
    for rel in sorted(candidates, key=lambda item: (len(Path(item).parts), item)):
        candidate = Path(rel)
        if any(candidate.is_relative_to(root) for root in terminal_roots):
            continue
        src = source / rel
        target = dest / rel
        try:
            src.parent.resolve().relative_to(source)
            target.parent.resolve().relative_to(dest)
        except ValueError:
            report.skipped.append(rel)
            continue
        try:
            source_info = src.lstat()
        except FileNotFoundError:
            source_info = None
        except OSError:
            report.skipped.append(rel)
            continue
        try:
            dest_info = target.lstat()
        except FileNotFoundError:
            dest_info = None
        except OSError:
            report.skipped.append(rel)
            continue
        # Directory paths (including submodule/gitlink checkouts) cannot be
        # copied as one exact image by this primitive. Never report them as
        # applied while leaving different children behind.
        supported_source = source_info is None or (
            stat.S_ISREG(source_info.st_mode) or stat.S_ISLNK(source_info.st_mode)
            or (allow_directories and stat.S_ISDIR(source_info.st_mode))
        )
        supported_dest = dest_info is None or (
            stat.S_ISREG(dest_info.st_mode) or stat.S_ISLNK(dest_info.st_mode)
            or (allow_directories and stat.S_ISDIR(dest_info.st_mode))
        )
        if not supported_source or not supported_dest:
            report.skipped.append(rel)
            continue
        normalized.append(rel)
        if (
            allow_directories
            and source_info is not None
            and stat.S_ISDIR(source_info.st_mode)
        ):
            terminal_roots.append(candidate)
    if report.skipped:
        report.skipped.sort()
        return report

    source_signatures = _path_signatures(source, normalized)
    unreadable_source = [
        rel
        for rel, signature in source_signatures.items()
        if signature == "invalid" or signature.endswith(":unreadable")
    ]
    if unreadable_source:
        report.skipped = sorted(unreadable_source)
        return report
    if expected_source_signatures is not None:
        expected = {
            _normalize_worktree_path(path): signature
            for path, signature in expected_source_signatures.items()
        }
        drifted = [
            rel
            for rel in normalized
            if expected.get(rel) != source_signatures.get(rel)
        ]
        if drifted:
            report.conflicted = sorted(drifted)
            return report
        bound_source_signatures = {rel: expected[rel] for rel in normalized}
    else:
        bound_source_signatures = dict(source_signatures)

    with tempfile.TemporaryDirectory(prefix="dstui-raw-apply-") as raw_tmp:
        temp_root = Path(raw_tmp)
        source_snapshot = temp_root / "source"
        backup = temp_root / "dest"
        source_snapshot.mkdir()
        backup.mkdir()
        try:
            for rel in normalized:
                if (source / rel).exists() or (source / rel).is_symlink():
                    _copy_raw_tree(source, source_snapshot, rel)
        except OSError:
            logger.debug("worktree_raw_source_snapshot_failed", exc_info=True)
            report.skipped = sorted(normalized)
            return report
        source_after_snapshot = _path_signatures(source, normalized)
        snapshot_signatures = _path_signatures(source_snapshot, normalized)
        source_drifted = [
            rel
            for rel in normalized
            if source_after_snapshot.get(rel) != bound_source_signatures.get(rel)
            or snapshot_signatures.get(rel) != bound_source_signatures.get(rel)
        ]
        if source_drifted:
            report.conflicted = sorted(source_drifted)
            return report

        destination_signatures = _path_signatures(dest, normalized)
        originally_present: set[str] = set()
        try:
            for rel in normalized:
                target = dest / rel
                if target.exists() or target.is_symlink():
                    backup_target = backup / rel
                    if not (backup_target.exists() or backup_target.is_symlink()):
                        _copy_raw_tree(dest, backup, rel)
                    originally_present.add(rel)
        except OSError:
            logger.debug("worktree_raw_backup_failed", exc_info=True)
            report.skipped = sorted(normalized)
            return report
        backup_signatures = _path_signatures(backup, normalized)
        destination_drifted = [
            rel
            for rel in normalized
            if _path_signature(dest / rel) != destination_signatures[rel]
            or (
                rel in originally_present
                and backup_signatures.get(rel) != destination_signatures[rel]
            )
        ]
        if destination_drifted:
            report.conflicted = sorted(destination_drifted)
            return report

        written: list[str] = []
        failed_path: str | None = None
        failed_with_error = False
        for rel in normalized:
            if _path_signature(dest / rel) != destination_signatures[rel]:
                failed_path = rel
                break
            try:
                _copy_raw(source_snapshot, dest, rel)
            except OSError:
                failed_path = rel
                failed_with_error = True
                logger.debug(
                    "worktree_raw_apply_failed path=%s", rel, exc_info=True
                )
                break
            written.append(rel)
            if _path_signature(dest / rel) != bound_source_signatures[rel]:
                failed_path = rel
                break
        if failed_path is None:
            changed_after_write = [
                rel
                for rel in written
                if _path_signature(dest / rel) != bound_source_signatures[rel]
            ]
            if changed_after_write:
                failed_path = changed_after_write[0]

        if failed_path is not None:
            rollback_failed: list[str] = []
            for rel in reversed(written):
                # Preserve an external edit that landed after our replacement.
                if _path_signature(dest / rel) != bound_source_signatures[rel]:
                    rollback_failed.append(rel)
                    continue
                try:
                    if rel in originally_present:
                        _replace_raw_path(dest / rel, None)
                        _copy_raw_tree(backup, dest, rel)
                    else:
                        _replace_raw_path(dest / rel, None)
                except OSError:
                    rollback_failed.append(rel)
                    logger.debug(
                        "worktree_raw_apply_rollback_failed path=%s",
                        rel,
                        exc_info=True,
                    )
                    continue
                if _path_signature(dest / rel) != destination_signatures[rel]:
                    rollback_failed.append(rel)
            if failed_with_error:
                report.skipped = sorted(set(normalized) | set(rollback_failed))
            else:
                report.conflicted = sorted({failed_path, *rollback_failed})
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
    labor_paths: list[str] | None = None,
    baseline: WorktreeBaseline | None = None,
    expected_signatures: dict[str, str] | None = None,
    incomplete_sync_journal: dict[str, object] | None = None,
) -> ApplyReport:
    """Resolve dirty isolate files that have no turn checkpoint.

    This is an explicit recovery path. Choosing the worktree copies its dirty
    files to the project first; choosing the project discards those isolate
    files. In both cases the isolate is then re-synced to the canonical project.
    """
    project = project_root.expanduser().resolve()
    tree = worktree_path.expanduser().resolve()
    selected = sorted(
        {
            _normalize_worktree_path(path)
            for path in (
                labor_paths
                if labor_paths is not None
                else await _changed_paths(tree, "HEAD")
            )
            if path
        }
    )
    if not selected:
        raise UnpublishedWorktreeError(
            f"managed worktree labor could not be enumerated: {tree}"
        )
    if baseline is None:
        raise UnpublishedWorktreeError(
            f"managed worktree labor has no verified baseline: {tree}"
        )
    current_signatures = await worktree_recovery_labor_signatures(
        tree,
        baseline,
        project_root=project,
        incomplete_sync_journal=incomplete_sync_journal,
    )
    current = sorted(current_signatures)
    if current != selected:
        raise UnpublishedWorktreeError(
            "managed worktree labor changed after the recovery choice was shown"
        )
    if expected_signatures is not None:
        normalized_expected = {
            _normalize_worktree_path(path): signature
            for path, signature in expected_signatures.items()
        }
        if current_signatures != normalized_expected:
            raise UnpublishedWorktreeError(
                "managed worktree bytes changed after the recovery choice was shown"
            )

    if use_worktree:
        resolved_signatures = current_signatures
        report = await apply_raw_paths(
            tree,
            project,
            selected,
            expected_source_signatures=resolved_signatures,
        )
    else:
        resolved_signatures = await asyncio.to_thread(
            worktree_path_signatures, project, selected
        )
        report = await apply_raw_paths(
            project,
            tree,
            selected,
            expected_source_signatures=resolved_signatures,
        )
    if report.conflicted or report.skipped:
        return report

    # The selected paths now match. Bring in any other project changes and move
    # the detached baseline without touching unrelated inherited dirt. During
    # interrupted inbound sync recovery, before/target images are allowed sync
    # artifacts while the just-resolved labor is bound to its chosen image.
    await sync_isolate_from_project(
        project,
        tree,
        baseline=baseline,
        resolved_labor_paths=selected,
        resolved_labor_signatures=resolved_signatures,
        recover_incomplete_sync=incomplete_sync_journal is not None,
        incomplete_sync_journal=incomplete_sync_journal,
        reset_git_state=True,
    )
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
    # The ordinary reclaim path must never force removal. Git's final clean-tree
    # check closes the window between our inspection above and deletion: if an
    # editor or tool creates a late file, removal fails and the copy is kept.
    removed = await _to_thread_complete(_remove_clean_worktree_sync, dest)
    return "removed" if removed else "kept"


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
    patch = await _git(project, ["diff", "--binary", "HEAD"], check=True)
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

    ok = await _to_thread_complete(_apply)
    if not ok:
        logger.debug("worktree_copy_dirty_failed dest=%s", worktree)
    return ok


async def _copy_untracked(source: Path, dest: Path) -> bool:
    listed = await _git(
        source,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        check=True,
    )
    copied = False
    for rel in _parse_git_paths(listed or ""):
        try:
            _copy_raw(source, dest, rel)
        except OSError:
            logger.debug("worktree_copy_untracked_failed path=%s", rel, exc_info=True)
            continue
        copied = True
    return copied


async def _copy_worktree_includes(source: Path, dest: Path) -> bool:
    """Copy explicitly selected ignored setup files into a new worktree."""
    copied = False
    for rel in await _worktree_include_paths(source):
        src = source / rel
        target = dest / rel
        # Setup copies never follow symlinks and never replace checkout files.
        if src.is_symlink() or target.exists():
            continue
        try:
            _copy_raw(source, dest, rel)
        except OSError:
            logger.debug("worktree_include_copy_failed path=%s", rel, exc_info=True)
            continue
        copied = True
    return copied


async def _worktree_include_paths(root: Path) -> list[str]:
    """Ignored setup files selected by ``.worktreeinclude``.

    These files are deliberately absent from ordinary ``git status`` but are
    part of the managed copy's state, so baseline and labor checks must include
    them too.
    """
    if not (root / ".worktreeinclude").is_file():
        return []
    listed = await _git(
        root,
        [
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-from=.worktreeinclude",
            "-z",
        ],
        check=True,
    )
    out: list[str] = []
    for rel in _parse_git_paths(listed or ""):
        if not rel or (root / rel).is_symlink():
            continue
        ignored = await _git(root, ["check-ignore", "--quiet", "--", rel], check=False)
        if ignored is not None:
            out.append(rel)
    return sorted(set(out))


def _raw_same(source: Path, dest: Path, rel: str) -> bool:
    left = _path_signature(source / rel)
    right = _path_signature(dest / rel)
    if left.endswith(":unreadable") or right.endswith(":unreadable"):
        return False
    return left == right


def _path_signatures(root: Path, paths: list[str]) -> dict[str, str]:
    return {rel: _path_signature(root / rel) for rel in paths}


def worktree_path_signatures(root: Path, paths: list[str]) -> dict[str, str]:
    """Capture exact content/type/mode signatures for workspace-relative paths."""
    workspace = root.expanduser().resolve()
    signatures: dict[str, str] = {}
    for raw in paths:
        rel = _normalize_worktree_path(raw)
        if not rel:
            continue
        try:
            target = _exact_workspace_path(workspace, rel)
        except OSError:
            signatures[rel] = "invalid"
            continue
        signatures[rel] = _path_signature(target)
    return signatures


def text_path_signature(content: str | None, mode: int | None) -> str | None:
    """Build a regular-file/absence signature from a complete text image."""
    if content is None:
        return "missing" if mode is None else None
    if mode is None:
        return None
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"file:{mode:o}:{digest}"


def _path_signature(path: Path) -> str:
    """Hash content and filesystem identity without following symlinks."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "path:unreadable"
    mode = stat.S_IMODE(info.st_mode)
    digest = hashlib.sha256()
    if stat.S_ISLNK(info.st_mode):
        try:
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        except OSError:
            return f"symlink:{mode:o}:unreadable"
        kind = "symlink"
    elif stat.S_ISREG(info.st_mode):
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return f"file:{mode:o}:unreadable"
        kind = "file"
    else:
        kind = f"other-{stat.S_IFMT(info.st_mode):o}"
    return f"{kind}:{mode:o}:{digest.hexdigest()}"


def _copy_raw(source: Path, dest: Path, rel: str) -> None:
    import shutil

    source_root = source.resolve()
    dest_root = dest.resolve()
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise OSError(f"copy path escapes workspace: {rel!r}")
    src = source_root / candidate
    dst = dest_root / candidate
    try:
        src.parent.resolve().relative_to(source_root)
        dst.parent.resolve().relative_to(dest_root)
    except ValueError as exc:
        raise OSError(f"copy path escapes workspace: {rel!r}") from exc
    try:
        source_info = src.lstat()
    except FileNotFoundError:
        _replace_raw_path(dst, None)
        return
    if stat.S_ISDIR(source_info.st_mode):
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{dst.name}.", dir=str(dst.parent)))
        try:
            shutil.rmtree(tmp)
            shutil.copytree(src, tmp, symlinks=True)
            _replace_raw_path(dst, tmp)
        finally:
            if tmp.is_dir() and not tmp.is_symlink():
                shutil.rmtree(tmp)
            else:
                tmp.unlink(missing_ok=True)
        return
    if not (stat.S_ISREG(source_info.st_mode) or stat.S_ISLNK(source_info.st_mode)):
        raise OSError(f"unsupported workspace path type: {rel!r}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", dir=str(dst.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        if stat.S_ISLNK(source_info.st_mode):
            tmp.unlink()
            os.symlink(os.readlink(src), tmp)
        else:
            shutil.copy2(src, tmp)
        _replace_raw_path(dst, tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _replace_raw_path(dest: Path, source: Path | str | None) -> None:
    """Replace one exact path, rolling its previous type back on failure."""
    import shutil

    dest.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if dest.exists() or dest.is_symlink():
        fd, backup_name = tempfile.mkstemp(
            prefix=f".{dest.name}.backup.", dir=str(dest.parent)
        )
        os.close(fd)
        backup = Path(backup_name)
        backup.unlink()
        os.replace(dest, backup)
    try:
        if source == "directory":
            dest.mkdir()
        elif isinstance(source, Path):
            os.replace(source, dest)
    except OSError:
        if backup is not None and not (dest.exists() or dest.is_symlink()):
            os.replace(backup, dest)
            backup = None
        raise
    finally:
        if backup is not None:
            if backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            else:
                backup.unlink(missing_ok=True)


def _copy_raw_tree(source: Path, dest: Path, rel: str) -> None:
    """Copy one backup/restore path, preserving a directory's full pre-image."""
    import shutil

    source_root = source.resolve()
    dest_root = dest.resolve()
    src = source_root / rel
    dst = dest_root / rel
    try:
        src.parent.resolve().relative_to(source_root)
        dst.parent.resolve().relative_to(dest_root)
    except ValueError as exc:
        raise OSError(f"copy path escapes workspace: {rel!r}") from exc
    if src.is_dir() and not src.is_symlink():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, symlinks=True)
        return
    _copy_raw(source_root, dest_root, rel)


async def _restore_to_head(root: Path, paths: list[str]) -> None:
    if not paths:
        return
    listed = await _git(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        check=True,
    )
    untracked = set(_parse_git_paths(listed or ""))
    tracked = [p for p in paths if p not in untracked]
    if tracked:
        await _git(root, ["checkout", "HEAD", "--", *tracked], check=True)
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
    included = _worktree_include_paths_sync(path)
    if included is None or included:
        # Included ignored files are intentionally outside git status. Their
        # mere presence is conservatively treated as labor here; byte/baseline
        # comparison decides whether they are inherited or task-owned.
        return True
    return _detached_head_is_unreachable_sync(path)


def _worktree_include_paths_sync(root: Path) -> list[str] | None:
    if not (root / ".worktreeinclude").is_file():
        return []
    try:
        listed = subprocess.run(
            [
                "git",
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-from=.worktreeinclude",
                "-z",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listed.returncode != 0:
        return None
    out: list[str] = []
    for rel in _parse_git_paths(listed.stdout or ""):
        if not rel or (root / rel).is_symlink():
            continue
        try:
            ignored = subprocess.run(
                ["git", "check-ignore", "--quiet", "--", rel],
                cwd=str(root),
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if ignored.returncode == 0:
            out.append(rel)
        elif ignored.returncode != 1:
            return None
    return sorted(set(out))


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
        worktree, ["diff", "--name-only", "-z", base], check=True
    )
    extra = await _git(
        worktree,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        check=True,
    )
    seen: set[str] = set()
    out: list[str] = []
    included = await _worktree_include_paths(worktree)
    for path in [
        *_parse_git_paths(diff or ""),
        *_parse_git_paths(extra or ""),
        *included,
    ]:
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


async def _show_at(root: Path, rev: str, rel: str) -> str | None | object:
    # An exact successful tree lookup is the only evidence of absence. A Git
    # timeout/failure must propagate instead of becoming None (which publish
    # interprets as "create/delete" and could overwrite the project).
    listed = await _git(
        root,
        ["ls-tree", "-z", "--full-tree", rev, "--", f":(literal){rel}"],
        check=True,
    )
    if not listed:
        return None
    try:
        header, _listed_path = listed.rstrip("\0").split("\t", 1)
        raw_mode, object_type, object_id = header.split(" ", 2)
        mode = int(raw_mode, 8)
    except (ValueError, TypeError):
        return _UNREADABLE
    if object_type != "blob" or mode not in {0o100644, 0o100755}:
        return _UNREADABLE
    try:
        out = await _git(root, ["cat-file", "blob", object_id], check=True)
    except UnicodeDecodeError:
        return _UNREADABLE
    if out is None:
        # check=True makes this unreachable for command failure; keep the
        # branch fail-closed for type checkers and future implementations.
        return _UNREADABLE
    if "\0" in out[:_BINARY_SNIFF_BYTES]:
        return _UNREADABLE
    return out


def _read_text(root: Path, rel: str) -> str | None | object:
    try:
        path = _exact_workspace_path(root, rel)
    except OSError:
        return _UNREADABLE
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return _UNREADABLE
        if info.st_size > _MAX_TEXT_BYTES:
            return _UNREADABLE
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return _UNREADABLE
    if b"\0" in data[:_BINARY_SNIFF_BYTES]:
        return _UNREADABLE
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return _UNREADABLE


def _write_text(root: Path, rel: str, content: str | None) -> None:
    target = _exact_workspace_path(root, rel)
    try:
        info = target.lstat()
    except FileNotFoundError:
        info = None
    if info is not None and not stat.S_ISREG(info.st_mode):
        raise OSError(f"refusing text write to non-regular path: {rel!r}")
    if content is None:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(target, content)


def _exact_workspace_path(root: Path, rel: str) -> Path:
    root = root.expanduser().resolve()
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise OSError(f"workspace path escapes root: {rel!r}")
    target = root / candidate
    try:
        target.parent.resolve().relative_to(root)
    except ValueError as exc:
        raise OSError(f"workspace path escapes root: {rel!r}") from exc
    return target


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

    code, out, err = await _to_thread_complete(_run)
    if code != 0:
        if check:
            raise WorktreeError((err or out or f"git {' '.join(args)} failed").strip())
        return None
    return out


_UNREADABLE = object()

read_working_text = _read_text
