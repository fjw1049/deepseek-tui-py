"""Managed git worktrees bound to a thread.

Creates detached checkouts under ``~/.deepseek/worktrees/`` and applies them
back to the project root with an explicit three-way merge. Never auto-syncs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from deepseek_tui.config.paths import user_worktrees_dir
from deepseek_tui.utils import write_text_atomic

logger = logging.getLogger(__name__)

_MAX_TEXT_BYTES = 512 * 1024
_BINARY_SNIFF_BYTES = 8192


class WorktreeError(ValueError):
    """User-facing git / worktree failure."""


@dataclass(slots=True)
class ManagedWorktree:
    path: Path
    base: str
    owned: bool = True
    dirty_copied: bool = False


@dataclass(slots=True)
class ApplyReport:
    applied: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    conflicted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

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
        await remove_managed_worktree(root, dest)
    await _git(root, ["worktree", "prune"], check=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        await _git(root, ["worktree", "add", "--detach", str(dest), head])
    except WorktreeError:
        if dest.exists():
            await remove_managed_worktree(root, dest)
        raise
    dirty_copied = False
    if copy_tracked_dirty:
        tracked = await _copy_tracked_dirty(root, dest)
        untracked = await _copy_untracked(root, dest)
        dirty_copied = tracked or untracked
    return ManagedWorktree(
        path=dest.resolve(), base=head, owned=True, dirty_copied=dirty_copied
    )


async def remove_managed_worktree(project_root: Path, worktree_path: Path) -> None:
    root = project_root.expanduser().resolve()
    dest = worktree_path.expanduser().resolve()
    if not is_managed_path(dest):
        raise WorktreeError("refusing to remove a worktree outside ~/.deepseek/worktrees")
    if await is_git_repo(root):
        await _git(
            root, ["worktree", "remove", "--force", str(dest)], check=False
        )
        await _git(root, ["worktree", "prune"], check=False)
    if dest.exists():
        await asyncio.to_thread(_rmtree, dest)


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


async def promote_worktree_branch(worktree_path: Path, branch: str) -> str:
    """Attach a detached worktree to a new local branch. Does not push."""
    tree = worktree_path.expanduser().resolve()
    name = _branch_name(branch)
    if not name:
        raise WorktreeError("branch name is required")
    exists = await _git(
        tree, ["show-ref", "--verify", "--quiet", f"refs/heads/{name}"], check=False
    )
    # show-ref --quiet: success → stdout empty string; missing ref → None.
    if exists is not None:
        raise WorktreeError(f"branch already exists: {name}")
    await _git(tree, ["checkout", "-b", name])
    return name


def prune_orphaned_worktrees(owned_paths: list[str]) -> int:
    """Delete managed worktree dirs not referenced by any thread."""
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
            _rmtree(resolved)
            removed += 1
        try:
            next(repo_dir.iterdir())
        except StopIteration:
            repo_dir.rmdir()
        except OSError:
            pass
    return removed


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
    if not preview:
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
    else:
        report.applied.extend(raw_copies)
        for rel, _next_text, status in planned:
            if status == "merged":
                report.merged.append(rel)
            else:
                report.applied.append(rel)
    report.applied.sort()
    report.merged.sort()
    report.conflicted.sort()
    report.skipped.sort()
    return report


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
    shutil.copy2(src, dst)


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
