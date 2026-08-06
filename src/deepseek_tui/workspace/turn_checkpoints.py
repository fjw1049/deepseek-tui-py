"""Per-turn file checkpoints backing rewind / code-restore.

Each turn gets one JSON file (``<root>/<turn_id>.json``) recording every
workspace path the turn mutated, the file's pre-turn content where known,
and — once the turn finishes — the file's post-turn content
(:meth:`TurnCheckpointStore.record_post_images`). Per path the pre-image
resolves as:

1. ``pre_contents[path]`` when recorded (``None`` = file did not exist then,
   so restore deletes it);
2. otherwise ``git show <head>:<path>`` for git workspaces (the path missing
   from HEAD means it did not exist then -> restore deletes it; a blob that
   is not UTF-8 text is unrecoverable -> skipped, never deleted);
3. otherwise the path cannot be restored and lands in
   :attr:`RestoreReport.skipped`.

Restore walks the affected turns newest-to-oldest, but a pre-image is never
written back blindly: the workspace is shared with other sessions and other
editors, so each step compares the file's current content against what this
turn left behind (the post-image):

- current == pre-image  -> already at the target state, nothing to do;
- current == post-image -> only this turn's changes are present, the
  pre-image is written back safely;
- otherwise a third party changed the file after the turn. A three-way
  merge (base = post-image, ours = current, theirs = pre-image) reverts
  only this turn's hunks while keeping the third-party edits; if the merge
  conflicts — or the path was only attributed by turn-end git reconcile
  (``uncertain``), where ownership is a guess — the file is left untouched
  and reported in :attr:`RestoreReport.conflicted` (``force=True``
  overrides and writes the pre-image anyway).

Checkpoints written before post-images existed (JSON lacks a
``post_contents`` field) keep the historical unconditional-write
behaviour for tool-written paths (``pre_contents`` present). On
post-image-aware checkpoints, a missing per-path post-image — binary,
oversized, or capture failure — is treated as a conflict, never as a
legacy blind write. Out-of-band paths without a post-image are always
conflicts so a restore can never delete or revert a file it cannot
prove it owns.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.utils import write_json_atomic, write_text_atomic
from deepseek_tui.workspace.git_reconcile import _run_git
from deepseek_tui.workspace.shell_mutation_watch import ShellMutationSnapshot

logger = logging.getLogger(__name__)

# Guards mirrored from shell_mutation_watch: files above this size or with
# NUL bytes in the head are never read for post-image capture / comparison.
_MAX_IMAGE_BYTES = 512 * 1024
_BINARY_SNIFF_BYTES = 8192

# Sentinel distinct from None (None = "file absent"): post-image was never
# recorded for the path (unreadable at capture time, or capture never ran).
_MISSING: Any = object()


@dataclass(slots=True)
class TurnCheckpoint:
    turn_id: str
    is_git: bool
    # HEAD sha at turn start (git workspaces only).
    head: str | None = None
    # path (posix, workspace-relative) -> pre-turn content; None = absent then.
    pre_contents: dict[str, str | None] = field(default_factory=dict)
    # path -> content when the turn finished; None = absent then. Missing key
    # = never captured for this path (unreadable / capture failure).
    post_contents: dict[str, str | None] = field(default_factory=dict)
    # Every path mutated this turn (ordered, deduplicated).
    mutated: list[str] = field(default_factory=list)
    # Paths attributed only by turn-end git reconcile: ownership is a guess
    # (a concurrent session or external editor may have written them), so
    # restore never merges them and requires an exact post-image match.
    uncertain: list[str] = field(default_factory=list)
    # Owning thread (one directory is shared across threads) and creation
    # time (epoch seconds) for newest-first restore ordering. Both default
    # for checkpoints written before these fields existed.
    thread_id: str = ""
    created_at: float = 0.0
    # True when the on-disk JSON carried a ``post_contents`` field (or this
    # checkpoint was created after post-images landed). False only for
    # legacy checkpoints; drives the unconditional-write restore fallback.
    has_post_images: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "is_git": self.is_git,
            "head": self.head,
            "pre_contents": self.pre_contents,
            "post_contents": self.post_contents,
            "mutated": self.mutated,
            "uncertain": self.uncertain,
            "thread_id": self.thread_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TurnCheckpoint:
        return cls(
            turn_id=str(raw["turn_id"]),
            is_git=bool(raw.get("is_git", False)),
            head=raw.get("head") or None,
            pre_contents=dict(raw.get("pre_contents") or {}),
            post_contents=dict(raw.get("post_contents") or {}),
            mutated=[str(p) for p in raw.get("mutated") or []],
            uncertain=[str(p) for p in raw.get("uncertain") or []],
            thread_id=str(raw.get("thread_id") or ""),
            created_at=float(raw.get("created_at") or 0.0),
            # Generational marker: presence of the key, not whether any
            # path was captured. An empty ``post_contents`` still means
            # post-image-aware (capture ran / format supports it).
            has_post_images="post_contents" in raw,
        )


@dataclass(slots=True)
class RestoreReport:
    # Paths written back or deleted (sorted, deduplicated).
    restored: list[str] = field(default_factory=list)
    # Paths where third-party edits were kept via a clean three-way merge.
    merged: list[str] = field(default_factory=list)
    # Paths with third-party edits that collide with this restore — left
    # untouched (restore again with force=True to overwrite).
    conflicted: list[str] = field(default_factory=list)
    # Mutated paths whose pre-image could not be resolved in any turn.
    skipped: list[str] = field(default_factory=list)
    # Turn ids with no checkpoint on disk (nothing recorded for them).
    turns_without_checkpoint: list[str] = field(default_factory=list)


# Per-path outcome labels shared by restore() and preview().
STATUS_RESTORED = "restored"
STATUS_MERGED = "merged"
STATUS_CONFLICTED = "conflicted"
STATUS_SKIPPED = "skipped"


@dataclass(slots=True)
class _PathState:
    # Disk content when the plan started; the plan never mutates disk.
    on_disk: Any
    # Content the path should end up with after the walk so far.
    current: Any
    status: str | None = None
    # A conflict freezes the path: older checkpoints must not touch it.
    done: bool = False


class TurnCheckpointStore:
    """File-based store: one checkpoint JSON per turn under ``root``."""

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)
        # record_* run from tool execution and may race with parallel tool
        # calls; serialize the load-modify-save cycle.
        self._lock = threading.Lock()

    def _path(self, turn_id: str) -> Path:
        return self._root / f"{turn_id}.json"

    def load(self, turn_id: str) -> TurnCheckpoint | None:
        path = self._path(turn_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return TurnCheckpoint.from_dict(raw)
        except Exception:
            logger.warning("Skipping unreadable turn checkpoint: %s", path)
            return None

    def _save(self, checkpoint: TurnCheckpoint) -> None:
        write_json_atomic(self._path(checkpoint.turn_id), checkpoint.to_dict())

    def begin_turn(
        self,
        turn_id: str,
        snapshot: ShellMutationSnapshot | None,
        *,
        head: str | None,
        is_git: bool,
        thread_id: str = "",
    ) -> TurnCheckpoint:
        """Create the checkpoint for a turn, seeded with the snapshot bytes."""
        checkpoint = TurnCheckpoint(
            turn_id=turn_id,
            is_git=is_git,
            head=head,
            pre_contents=dict(snapshot.contents) if snapshot is not None else {},
            thread_id=thread_id,
            created_at=time.time(),
        )
        with self._lock:
            self._save(checkpoint)
        return checkpoint

    def record_pre_write(self, turn_id: str, path: str, old_text: str | None) -> None:
        """Record a tool write's pre-image; first touch of a path wins."""
        norm = path.replace("\\", "/")
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None or norm in checkpoint.mutated:
                return
            checkpoint.pre_contents[norm] = old_text
            checkpoint.mutated.append(norm)
            self._save(checkpoint)

    def record_out_of_band(
        self, turn_id: str, path: str, *, uncertain: bool = False
    ) -> None:
        """Note a shell/git-side mutation; pre-image resolved at restore time.

        ``uncertain=True`` marks paths attributed only by turn-end git
        reconcile — ownership is a guess, so restore holds them to a
        stricter standard (exact post-image match, no merging).
        """
        norm = path.replace("\\", "/")
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None or norm in checkpoint.mutated:
                return
            checkpoint.mutated.append(norm)
            if uncertain:
                checkpoint.uncertain.append(norm)
            self._save(checkpoint)

    def record_post_images(self, turn_id: str, workspace: Path) -> None:
        """Capture every mutated path's end-of-turn content for restore-time
        conflict detection. Unreadable files (binary/oversized) stay
        uncaptured; on post-image-aware checkpoints restore reports them
        as conflicts rather than blindly writing the pre-image."""
        root = _resolved_root(workspace)
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None or not checkpoint.mutated:
                return
            checkpoint.has_post_images = True
            for path in checkpoint.mutated:
                value = _read_disk(root, path)
                if isinstance(value, _Unreadable):
                    continue
                checkpoint.post_contents[path] = value
            self._save(checkpoint)

    async def restore(
        self,
        turn_ids_newest_first: list[str],
        workspace: Path,
        *,
        force: bool = False,
    ) -> RestoreReport:
        """Roll back the given turns' changes, newest to oldest.

        Safe by default: paths whose current content diverged from the
        recorded post-image are three-way merged (third-party edits kept)
        or reported as conflicted and left untouched. ``force=True`` writes
        the pre-image over conflicts as well.
        """
        root, report, states = await self._plan(
            turn_ids_newest_first, workspace, force=force
        )
        restored: set[str] = set()
        merged: set[str] = set()
        conflicted: set[str] = set()
        skipped: set[str] = set()
        for path, state in states.items():
            if state.status is None or state.status == STATUS_SKIPPED:
                skipped.add(path)
                continue
            if state.status == STATUS_CONFLICTED:
                conflicted.add(path)
                continue
            if isinstance(state.current, _Unreadable):
                skipped.add(path)
                continue
            if state.current != state.on_disk:
                try:
                    _write_pre_image(root, path, state.current)
                except OSError:
                    logger.debug(
                        "turn_checkpoint_restore_failed path=%s",
                        path,
                        exc_info=True,
                    )
                    skipped.add(path)
                    continue
            if state.status == STATUS_MERGED:
                merged.add(path)
            else:
                restored.add(path)
        report.restored = sorted(restored)
        report.merged = sorted(merged)
        report.conflicted = sorted(conflicted)
        report.skipped = sorted(skipped)
        return report

    async def preview(
        self, turn_ids_newest_first: list[str], workspace: Path
    ) -> dict[str, str]:
        """Dry-run of :meth:`restore`: per-path outcome, disk untouched."""
        _, _, states = await self._plan(
            turn_ids_newest_first, workspace, force=False
        )
        return {
            path: (state.status or STATUS_SKIPPED)
            for path, state in states.items()
        }

    async def _plan(
        self,
        turn_ids_newest_first: list[str],
        workspace: Path,
        *,
        force: bool,
    ) -> tuple[Path, RestoreReport, dict[str, _PathState]]:
        root = _resolved_root(workspace)
        report = RestoreReport()
        states: dict[str, _PathState] = {}
        for turn_id in turn_ids_newest_first:
            checkpoint = self.load(turn_id)
            if checkpoint is None:
                report.turns_without_checkpoint.append(turn_id)
                continue
            for path in checkpoint.mutated:
                state = states.get(path)
                if state is None:
                    on_disk = await asyncio.to_thread(_read_disk, root, path)
                    state = _PathState(on_disk=on_disk, current=on_disk)
                    states[path] = state
                if state.done:
                    continue
                pre = await self._resolve_pre_image(root, checkpoint, path)
                if isinstance(pre, _Unresolvable):
                    # An older checkpoint may still resolve this path.
                    if state.status is None:
                        state.status = STATUS_SKIPPED
                    continue
                post = checkpoint.post_contents.get(path, _MISSING)
                uncertain = (
                    path in checkpoint.uncertain
                    and path not in checkpoint.pre_contents
                )
                current = state.current
                if current == pre:
                    # Already at this turn's start state.
                    state.current = pre
                    state.status = STATUS_RESTORED
                    continue
                if post is not _MISSING and current == post:
                    # Exactly what this turn left behind — safe to roll back.
                    state.current = pre
                    state.status = STATUS_RESTORED
                    continue
                if (
                    not checkpoint.has_post_images
                    and post is _MISSING
                    and path in checkpoint.pre_contents
                ):
                    # Whole-checkpoint legacy format (no ``post_contents``
                    # field): keep the historical unconditional write for
                    # tool-written paths. Per-path missing posts on a
                    # post-image-aware checkpoint must NOT take this branch
                    # — they fall through to conflict below.
                    state.current = pre
                    state.status = STATUS_RESTORED
                    continue
                if (
                    not uncertain
                    and isinstance(post, str)
                    and isinstance(current, str)
                    and isinstance(pre, str)
                ):
                    merged = await _merge3(base=post, ours=current, theirs=pre)
                    if merged is not None:
                        state.current = merged
                        state.status = STATUS_MERGED
                        continue
                if force:
                    state.current = pre
                    state.status = STATUS_RESTORED
                    continue
                state.current = state.on_disk
                state.status = STATUS_CONFLICTED
                state.done = True
        return root, report, states

    async def _resolve_pre_image(
        self, root: Path, checkpoint: TurnCheckpoint, path: str
    ) -> str | None | _Unresolvable:
        if path in checkpoint.pre_contents:
            return checkpoint.pre_contents[path]
        if checkpoint.is_git and checkpoint.head:
            try:
                # None = path absent from HEAD -> untracked at turn start ->
                # the file did not exist then, so restore deletes it.
                return await _run_git(root, ["show", f"{checkpoint.head}:{path}"])
            except UnicodeDecodeError:
                # Blob exists at HEAD but is not UTF-8 text: restoring text is
                # impossible, and None here would unlink the binary file —
                # report it unrecoverable instead.
                return _Unresolvable()
        return _Unresolvable()

    def list_for_thread(self, thread_id: str) -> list[TurnCheckpoint]:
        """All checkpoints owned by ``thread_id``, oldest first by creation."""
        out: list[TurnCheckpoint] = []
        for path in self._root.glob("*.json"):
            checkpoint = self.load(path.stem)
            if checkpoint is not None and checkpoint.thread_id == thread_id:
                out.append(checkpoint)
        out.sort(key=lambda cp: cp.created_at)
        return out

    def delete(self, turn_id: str) -> None:
        self._path(turn_id).unlink(missing_ok=True)

    def prune_older_than(self, max_age_days: int) -> int:
        """Delete checkpoints older than ``max_age_days``. Returns count removed."""
        if max_age_days < 1:
            return 0
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        for path in list(self._root.glob("*.json")):
            checkpoint = self.load(path.stem)
            if checkpoint is None:
                # Unreadable / corrupt — reclaim the file.
                path.unlink(missing_ok=True)
                removed += 1
                continue
            created = checkpoint.created_at or 0.0
            if created <= 0.0:
                try:
                    created = path.stat().st_mtime
                except OSError:
                    created = 0.0
            if created < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed


class _Unresolvable:
    """Sentinel: no pre-image available (non-git workspace, none recorded)."""


class _Unreadable:
    """Sentinel: file exists but cannot be compared (binary/oversized)."""


def _resolved_root(workspace: Path) -> Path:
    return workspace.expanduser().resolve()


def _read_disk(root: Path, rel: str) -> str | None | _Unreadable:
    """Current file text; None when absent; _Unreadable when not comparable."""
    path = root / rel
    try:
        if path.stat().st_size > _MAX_IMAGE_BYTES:
            return _Unreadable()
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:_BINARY_SNIFF_BYTES]:
        return _Unreadable()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return _Unreadable()


async def _merge3(*, base: str, ours: str, theirs: str) -> str | None:
    """Clean three-way merge of ``theirs`` onto ``ours`` from ``base``.

    Returns the merged text, or None when the merge conflicts or cannot run
    (git missing). Used to revert one turn's changes (base -> theirs) while
    keeping edits other sessions/editors made on top (base -> ours).
    """

    def _run() -> str | None:
        try:
            with tempfile.TemporaryDirectory(prefix="dstui-merge3-") as td:
                d = Path(td)
                (d / "ours").write_text(ours, encoding="utf-8")
                (d / "base").write_text(base, encoding="utf-8")
                (d / "theirs").write_text(theirs, encoding="utf-8")
                proc = subprocess.run(
                    ["git", "merge-file", "-p", "ours", "base", "theirs"],
                    cwd=str(d),
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
        except (OSError, subprocess.TimeoutExpired):
            return None
        # Exit status is the number of conflicts (negative on error).
        if proc.returncode != 0:
            return None
        try:
            return proc.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None

    return await asyncio.to_thread(_run)


def _write_pre_image(root: Path, rel: str, content: str | None) -> None:
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise OSError(f"checkpoint path escapes workspace: {rel!r}") from None
    if content is None:
        target.unlink(missing_ok=True)
    else:
        write_text_atomic(target, content)
