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
import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.utils import write_json_atomic, write_text_atomic
from deepseek_tui.workspace.shell_mutation_watch import ShellMutationSnapshot

logger = logging.getLogger(__name__)

# Guards mirrored from shell_mutation_watch: files above this size or with
# NUL bytes in the head are never read for post-image capture / comparison.
_MAX_IMAGE_BYTES = 512 * 1024
_BINARY_SNIFF_BYTES = 8192

# Sentinel distinct from None (None = "file absent"): post-image was never
# recorded for the path (unreadable at capture time, or capture never ran).
_MISSING: Any = object()


class RawCheckpointError(OSError):
    """Opaque checkpoint images could not be staged or validated safely."""

    def __init__(self, paths: list[str], message: str) -> None:
        super().__init__(message)
        self.paths = sorted(set(paths))


def _load_modes(raw: Any) -> dict[str, int | None]:
    if not isinstance(raw, dict):
        return {}
    modes: dict[str, int | None] = {}
    for path, value in raw.items():
        if value is None or (isinstance(value, int) and not isinstance(value, bool)):
            modes[str(path)] = value
    return modes


def _load_raw_images(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    images: dict[str, dict[str, Any]] = {}
    for path, value in raw.items():
        if not isinstance(value, dict):
            continue
        kind = value.get("kind")
        mode = value.get("mode")
        signature = value.get("signature")
        if kind not in {"missing", "file", "symlink"} or not isinstance(
            signature, str
        ):
            continue
        if mode is not None and (
            not isinstance(mode, int) or isinstance(mode, bool)
        ):
            continue
        if kind == "missing" and (mode is not None or signature != "missing"):
            continue
        if kind != "missing" and mode is None:
            continue
        images[_normalize_relative_path(str(path))] = {
            "kind": kind,
            "mode": mode,
            "signature": signature,
        }
    return images


def _normalize_relative_path(path: str) -> str:
    # Backslash is a valid filename character on POSIX, not a separator.
    return path.replace("\\", "/") if os.name == "nt" else path


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
    # POSIX permission bits accompany text images. Missing keys mean the
    # checkpoint predates mode-aware capture or the path was not a regular
    # file/absence that can be restored safely; ``None`` means absent.
    pre_modes: dict[str, int | None] = field(default_factory=dict)
    post_modes: dict[str, int | None] = field(default_factory=dict)
    # Immutable task-copy identity at turn end. Unlike ``post_contents``, this
    # covers binary files, symlinks, type changes, and permission-only edits.
    post_signatures: dict[str, str] = field(default_factory=dict)
    post_signatures_captured: bool = False
    # Durable opaque project pre-images and task post-images. Payload bytes live
    # in a per-checkpoint sidecar directory; JSON stores only type/mode/signature.
    raw_pre_images: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw_post_images: dict[str, dict[str, Any]] = field(default_factory=dict)
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
    # Absolute execution root at capture time. Restore writes only here.
    # After a successful publish this is retargeted to the project root.
    execution_root: str = ""
    # True when the on-disk JSON carried a ``post_contents`` field (or this
    # checkpoint was created after post-images landed). False only for
    # legacy checkpoints; drives the unconditional-write restore fallback.
    has_post_images: bool = True
    # Publishing is journaled across project writes and isolate resync.
    publish_pending_sync: bool = False
    publish_apply_complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "is_git": self.is_git,
            "head": self.head,
            "pre_contents": self.pre_contents,
            "post_contents": self.post_contents,
            "pre_modes": self.pre_modes,
            "post_modes": self.post_modes,
            "post_signatures": self.post_signatures,
            "post_signatures_captured": self.post_signatures_captured,
            "raw_pre_images": self.raw_pre_images,
            "raw_post_images": self.raw_post_images,
            "mutated": self.mutated,
            "uncertain": self.uncertain,
            "thread_id": self.thread_id,
            "created_at": self.created_at,
            "execution_root": self.execution_root,
            "publish_pending_sync": self.publish_pending_sync,
            "publish_apply_complete": self.publish_apply_complete,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TurnCheckpoint:
        return cls(
            turn_id=str(raw["turn_id"]),
            is_git=bool(raw.get("is_git", False)),
            head=raw.get("head") or None,
            pre_contents=dict(raw.get("pre_contents") or {}),
            post_contents=dict(raw.get("post_contents") or {}),
            pre_modes=_load_modes(raw.get("pre_modes")),
            post_modes=_load_modes(raw.get("post_modes")),
            post_signatures={
                _normalize_relative_path(str(path)): signature
                for path, signature in (raw.get("post_signatures") or {}).items()
                if isinstance(signature, str)
            }
            if isinstance(raw.get("post_signatures"), dict)
            else {},
            post_signatures_captured=bool(
                raw.get(
                    "post_signatures_captured",
                    "post_signatures" in raw,
                )
            ),
            raw_pre_images=_load_raw_images(raw.get("raw_pre_images")),
            raw_post_images=_load_raw_images(raw.get("raw_post_images")),
            mutated=[str(p) for p in raw.get("mutated") or []],
            uncertain=[str(p) for p in raw.get("uncertain") or []],
            thread_id=str(raw.get("thread_id") or ""),
            created_at=float(raw.get("created_at") or 0.0),
            execution_root=str(raw.get("execution_root") or ""),
            # Generational marker: presence of the key, not whether any
            # path was captured. An empty ``post_contents`` still means
            # post-image-aware (capture ran / format supports it).
            has_post_images="post_contents" in raw,
            publish_pending_sync=bool(raw.get("publish_pending_sync", False)),
            publish_apply_complete=bool(raw.get("publish_apply_complete", False)),
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
    # Recorded execution roots that are no longer on disk. Those
    # checkpoints are not rewritten onto the current workspace.
    missing_roots: list[str] = field(default_factory=list)


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
    # Permission bits paired with the images above. _MISSING means a legacy
    # or non-regular path whose mode cannot be claimed or restored safely.
    on_disk_mode: Any = _MISSING
    current_mode: Any = _MISSING
    status: str | None = None
    # A conflict freezes the path: older checkpoints must not touch it.
    done: bool = False


@dataclass(slots=True)
class _RawRestorePathState:
    root: Path
    path: str
    on_disk_signature: str
    current_signature: str
    on_disk_image: Any | None = None
    current_image: Any | None = None
    done: bool = False


@dataclass(slots=True)
class _RawRestoreBatch:
    root: Path
    original: list[Any] = field(default_factory=list)
    target: list[Any] = field(default_factory=list)

    @property
    def paths(self) -> list[str]:
        return [image.path for image in self.target]


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

    def _raw_sidecar_dir(self, turn_id: str) -> Path:
        return self._root / f"{turn_id}.raw"

    def _raw_sidecar_path(self, turn_id: str, path: str, phase: str) -> Path:
        digest = hashlib.sha256(
            _normalize_relative_path(path).encode("utf-8", errors="surrogateescape")
        ).hexdigest()
        return self._raw_sidecar_dir(turn_id) / f"{digest}.{phase}"

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
        execution_root: str = "",
    ) -> TurnCheckpoint:
        """Create the checkpoint for a turn, seeded with the snapshot bytes."""
        pre_contents = dict(snapshot.contents) if snapshot is not None else {}
        checkpoint = TurnCheckpoint(
            turn_id=turn_id,
            is_git=is_git,
            head=head,
            pre_contents=pre_contents,
            post_signatures_captured=False,
            thread_id=thread_id,
            created_at=time.time(),
            execution_root=execution_root,
        )
        if snapshot is not None:
            checkpoint.pre_modes.update(snapshot.modes)
        with self._lock:
            self._save(checkpoint)
        return checkpoint

    def record_pre_write(self, turn_id: str, path: str, old_text: str | None) -> None:
        """Record a tool write's pre-image; first touch of a path wins."""
        norm = _normalize_relative_path(path)
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None or norm in checkpoint.mutated:
                return
            checkpoint.pre_contents[norm] = old_text
            root = _existing_checkpoint_root(checkpoint)
            if root is not None:
                mode = _mode_matching_content(root, norm, old_text)
                if mode is not _MISSING:
                    checkpoint.pre_modes[norm] = mode
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
        norm = _normalize_relative_path(path)
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
        from deepseek_tui.workspace.managed_worktree import (
            text_path_signature,
            worktree_path_signatures,
        )

        root = _resolved_root(workspace)
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None or not checkpoint.mutated:
                return
            if checkpoint.post_signatures_captured and checkpoint.post_signatures:
                return
            checkpoint.has_post_images = True
            checkpoint.post_contents.clear()
            checkpoint.post_modes.clear()
            for path in checkpoint.mutated:
                value = _read_disk(root, path)
                if isinstance(value, _Unreadable):
                    continue
                checkpoint.post_contents[path] = value
                mode = _read_regular_mode(root, path)
                if mode is not _MISSING:
                    checkpoint.post_modes[path] = mode
            checkpoint.post_signatures = worktree_path_signatures(
                root, checkpoint.mutated
            )
            checkpoint.post_signatures_captured = (
                set(checkpoint.post_signatures) == set(checkpoint.mutated)
                and all(
                    signature != "invalid"
                    and not signature.endswith(":unreadable")
                    for signature in checkpoint.post_signatures.values()
                )
            )
            if checkpoint.post_signatures_captured:
                for path in checkpoint.mutated:
                    if (
                        path not in checkpoint.post_contents
                        or path not in checkpoint.post_modes
                    ):
                        continue
                    expected = text_path_signature(
                        checkpoint.post_contents[path], checkpoint.post_modes[path]
                    )
                    if expected != checkpoint.post_signatures[path]:
                        checkpoint.post_signatures_captured = False
                        break
            self._save(checkpoint)

    def retarget_to_project(
        self,
        turn_id: str,
        project_root: Path,
        images: dict[str, tuple[str | None, str | None]],
        *,
        raw_source_root: Path | None = None,
        raw_paths: list[str] | None = None,
        expected_raw_post_signatures: dict[str, str] | None = None,
    ) -> None:
        """Stage project provenance before the first project write.

        ``images`` maps path -> (project content before publish, after).
        A retry never replaces already staged images: after a crash, bytes
        already on disk are not the true pre-publish project version.
        """
        root = str(Path(project_root).expanduser().resolve())
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None:
                return
            already_staged = checkpoint.publish_pending_sync
            normalized_raw = sorted(
                {
                    _normalize_relative_path(path)
                    for path in (raw_paths or [])
                    if path
                }
            )
            if already_staged and normalized_raw:
                staged_raw = set(checkpoint.raw_pre_images) | set(
                    checkpoint.raw_post_images
                )
                if set(normalized_raw) != staged_raw:
                    raise RawCheckpointError(
                        normalized_raw,
                        "raw publication journal does not match the staged paths",
                    )
            if not already_staged and normalized_raw:
                if raw_source_root is None:
                    raise RawCheckpointError(
                        normalized_raw, "raw publication source is unavailable"
                    )
                raw_pre, raw_post = self._stage_raw_publish_sidecars(
                    turn_id,
                    Path(root),
                    Path(raw_source_root).expanduser().resolve(),
                    normalized_raw,
                    expected_raw_post_signatures or {},
                )
                checkpoint.raw_pre_images = raw_pre
                checkpoint.raw_post_images = raw_post
            checkpoint.execution_root = root
            checkpoint.has_post_images = True
            checkpoint.publish_pending_sync = True
            if not already_staged:
                checkpoint.publish_apply_complete = False
                for path in checkpoint.mutated:
                    mode = _read_regular_mode(Path(root), path)
                    if mode is not _MISSING:
                        checkpoint.pre_modes[path] = mode
                for path, (pre, post) in images.items():
                    norm = _normalize_relative_path(path)
                    checkpoint.pre_contents[norm] = pre
                    checkpoint.post_contents[norm] = post
            self._save(checkpoint)

    def _stage_raw_publish_sidecars(
        self,
        turn_id: str,
        project_root: Path,
        source_root: Path,
        paths: list[str],
        expected_post_signatures: dict[str, str],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        temp_dir = Path(
            tempfile.mkdtemp(dir=self._root, prefix=f".{turn_id}.raw.")
        )
        final_dir = self._raw_sidecar_dir(turn_id)
        pre: dict[str, dict[str, Any]] = {}
        post: dict[str, dict[str, Any]] = {}
        try:
            for path in paths:
                digest = hashlib.sha256(
                    path.encode("utf-8", errors="surrogateescape")
                ).hexdigest()
                pre[path] = _capture_raw_sidecar_image(
                    project_root, path, temp_dir / f"{digest}.pre"
                )
                post[path] = _capture_raw_sidecar_image(
                    source_root, path, temp_dir / f"{digest}.post"
                )
                expected = expected_post_signatures.get(path)
                if expected is None or post[path]["signature"] != expected:
                    raise RawCheckpointError(
                        [path], "task raw bytes changed before publication"
                    )
            drifted = [
                path
                for path in paths
                if _raw_path_signature(project_root, path)
                != pre[path]["signature"]
                or _raw_path_signature(source_root, path)
                != post[path]["signature"]
            ]
            if drifted:
                raise RawCheckpointError(
                    drifted, "raw bytes changed while publication was staged"
                )
            if final_dir.exists():
                shutil.rmtree(final_dir)
            os.replace(temp_dir, final_dir)
        except BaseException:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        return pre, post

    def raw_publish_images(
        self, turn_id: str, paths: list[str]
    ) -> tuple[list[Any], list[Any]]:
        """Load validated sidecar descriptors for an opaque publish replay."""
        from deepseek_tui.workspace.managed_worktree import RawPathImage

        checkpoint = self.load(turn_id)
        normalized = sorted(
            {_normalize_relative_path(path) for path in paths if path}
        )
        if checkpoint is None:
            raise RawCheckpointError(normalized, "checkpoint is unavailable")
        if set(normalized) != set(checkpoint.raw_pre_images) or set(
            normalized
        ) != set(checkpoint.raw_post_images):
            raise RawCheckpointError(
                normalized, "raw publication sidecar is incomplete"
            )

        def build(phase: str, values: dict[str, dict[str, Any]]) -> list[Any]:
            out: list[Any] = []
            for path in normalized:
                value = values[path]
                kind = str(value["kind"])
                payload = (
                    None
                    if kind == "missing"
                    else self._raw_sidecar_path(turn_id, path, phase)
                )
                out.append(
                    RawPathImage(
                        path=path,
                        kind=kind,
                        mode=value.get("mode"),
                        signature=str(value["signature"]),
                        payload_path=payload,
                    )
                )
            return out

        return (
            build("pre", checkpoint.raw_pre_images),
            build("post", checkpoint.raw_post_images),
        )

    def mark_publish_applied(self, turn_id: str) -> None:
        """Record that every project write for a staged checkpoint landed."""
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None or not checkpoint.publish_pending_sync:
                return
            root = _existing_checkpoint_root(checkpoint)
            if root is None:
                return
            for path in checkpoint.mutated:
                mode = _read_regular_mode(root, path)
                if mode is not _MISSING:
                    checkpoint.post_modes[path] = mode
            checkpoint.publish_apply_complete = True
            self._save(checkpoint)

    def mark_publish_synced(self, turn_id: str) -> None:
        """Complete publish after isolate sync and baseline persistence."""
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None:
                return
            checkpoint.publish_pending_sync = False
            checkpoint.publish_apply_complete = False
            self._save(checkpoint)

    def mark_recovery_resolved(
        self,
        turn_id: str,
        project_root: Path,
        *,
        abandon_paths: list[str] | None = None,
    ) -> None:
        """Retire a stale publish journal after explicit labor recovery.

        ``keep_project`` makes the project's current bytes canonical for the
        paths in ``abandon_paths``. Those rejected task images must not remain
        eligible for a later rewind: a future coincidental match with an old
        post-image could otherwise roll back code the user explicitly kept.
        """
        root = str(Path(project_root).expanduser().resolve())
        abandoned = {
            _normalize_relative_path(path)
            for path in (abandon_paths or [])
            if path
        }
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None:
                return
            checkpoint.execution_root = root
            checkpoint.publish_pending_sync = False
            checkpoint.publish_apply_complete = False
            abandoned_raw = abandoned.intersection(
                set(checkpoint.raw_pre_images) | set(checkpoint.raw_post_images)
            )
            if abandoned:
                checkpoint.mutated = [
                    path for path in checkpoint.mutated if path not in abandoned
                ]
                checkpoint.uncertain = [
                    path for path in checkpoint.uncertain if path not in abandoned
                ]
                for values in (
                    checkpoint.pre_contents,
                    checkpoint.post_contents,
                    checkpoint.pre_modes,
                    checkpoint.post_modes,
                    checkpoint.post_signatures,
                    checkpoint.raw_pre_images,
                    checkpoint.raw_post_images,
                ):
                    for path in abandoned:
                        values.pop(path, None)
            self._save(checkpoint)
            # Persist the reduced journal before reclaiming its payloads. A
            # crash can leave only inert orphan files, never JSON that still
            # references deleted recovery bytes.
            for path in abandoned_raw:
                self._raw_sidecar_path(turn_id, path, "pre").unlink(
                    missing_ok=True
                )
                self._raw_sidecar_path(turn_id, path, "post").unlink(
                    missing_ok=True
                )
            try:
                self._raw_sidecar_dir(turn_id).rmdir()
            except OSError:
                pass

    async def _plan_raw_restore(
        self,
        turn_ids_newest_first: list[str],
        fallback: Path,
    ) -> tuple[
        list[_RawRestoreBatch],
        set[tuple[str, str]],
        set[str],
        set[str],
        set[str],
    ]:
        """Plan every durable raw transition without mutating the workspace."""
        from deepseek_tui.workspace.managed_worktree import (
            validate_raw_path_images,
        )

        states: dict[tuple[str, str], _RawRestorePathState] = {}
        raw_keys: set[tuple[str, str]] = set()
        all_paths: set[str] = set()
        conflicted: set[str] = set()
        skipped: set[str] = set()
        for turn_id in turn_ids_newest_first:
            checkpoint = self.load(turn_id)
            if checkpoint is None:
                continue
            raw_paths = sorted(
                set(checkpoint.raw_pre_images) | set(checkpoint.raw_post_images)
            )
            if not raw_paths:
                continue
            all_paths.update(raw_paths)
            target = _root_for_checkpoint(checkpoint, fallback)
            if target is None:
                skipped.update(raw_paths)
                continue
            root_key = str(target)
            raw_keys.update((root_key, path) for path in raw_paths)
            try:
                raw_pre, raw_post = self.raw_publish_images(turn_id, raw_paths)
            except RawCheckpointError:
                skipped.update(raw_paths)
                continue
            validation = await validate_raw_path_images(
                target, raw_pre, raw_post
            )
            if validation.skipped:
                skipped.update(validation.skipped)
                continue
            pre = {image.path: image for image in raw_pre}
            post = {image.path: image for image in raw_post}
            for path in raw_paths:
                key = (root_key, path)
                state = states.get(key)
                if state is None:
                    signature = _raw_path_signature(target, path)
                    state = _RawRestorePathState(
                        root=target,
                        path=path,
                        on_disk_signature=signature,
                        current_signature=signature,
                    )
                    states[key] = state
                if state.done:
                    continue
                before = pre[path]
                after = post[path]
                if state.current_signature not in {
                    before.signature,
                    after.signature,
                }:
                    conflicted.add(path)
                    state.done = True
                    continue
                if state.on_disk_image is None:
                    state.on_disk_image = (
                        before
                        if state.on_disk_signature == before.signature
                        else after
                    )
                state.current_signature = before.signature
                state.current_image = before

        batches_by_root: dict[str, _RawRestoreBatch] = {}
        if not conflicted and not skipped:
            for state in states.values():
                if state.on_disk_image is None or state.current_image is None:
                    skipped.add(state.path)
                    continue
                if state.on_disk_signature == state.current_signature:
                    continue
                key = str(state.root)
                batch = batches_by_root.setdefault(
                    key, _RawRestoreBatch(root=state.root)
                )
                batch.original.append(state.on_disk_image)
                batch.target.append(state.current_image)
        batches = list(batches_by_root.values())
        for batch in batches:
            paired = sorted(
                zip(batch.original, batch.target, strict=True),
                key=lambda pair: pair[0].path,
            )
            batch.original = [pair[0] for pair in paired]
            batch.target = [pair[1] for pair in paired]
        return batches, raw_keys, all_paths, conflicted, skipped

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
        changes: list[tuple[Path, str, _PathState]] = []
        for (root_key, path), state in states.items():
            target = Path(root_key)
            if not target.is_dir():
                skipped.add(path)
                continue
            if state.status is None or state.status == STATUS_SKIPPED:
                skipped.add(path)
                continue
            if state.status == STATUS_CONFLICTED:
                conflicted.add(path)
                continue
            if isinstance(state.current, _Unreadable):
                skipped.add(path)
                continue
            if (
                state.current != state.on_disk
                or state.current_mode != state.on_disk_mode
            ):
                changes.append((target, path, state))
            else:
                if state.status == STATUS_MERGED:
                    merged.add(path)
                else:
                    restored.add(path)

        (
            raw_batches,
            raw_keys,
            raw_paths,
            raw_conflicted,
            raw_skipped,
        ) = await self._plan_raw_restore(turn_ids_newest_first, root)
        overlap = set(states).intersection(raw_keys)
        if overlap:
            raw_conflicted.update(path for _root, path in overlap)
        conflicted.update(raw_conflicted)
        skipped.update(raw_skipped)
        text_change_paths = {path for _target, path, _state in changes}
        raw_change_paths = {
            path for batch in raw_batches for path in batch.paths
        }
        transaction_paths = text_change_paths | raw_change_paths
        if raw_conflicted or raw_skipped:
            # A durable raw image is part of the same restore request. If it
            # cannot be proven before the first write, no text or sibling raw
            # path may be partially restored and consumed by the caller.
            blocked = text_change_paths | raw_paths
            if raw_conflicted:
                conflicted.update(blocked)
            else:
                skipped.update(blocked)
            restored.difference_update(blocked)
            merged.difference_update(blocked)
            skipped.difference_update(conflicted)
            report.restored = sorted(restored)
            report.merged = sorted(merged)
            report.conflicted = sorted(conflicted)
            report.skipped = sorted(skipped)
            return report

        stale_text = any(
            not _disk_matches_image(
                target, path, state.on_disk, state.on_disk_mode
            )
            for target, path, state in changes
        )
        stale_raw = any(
            _raw_path_signature(batch.root, original.path)
            != original.signature
            for batch in raw_batches
            for original in batch.original
        )
        if stale_text or stale_raw:
            conflicted.update(transaction_paths)
            restored.difference_update(transaction_paths)
            merged.difference_update(transaction_paths)
            skipped.difference_update(conflicted)
            report.restored = sorted(restored)
            report.merged = sorted(merged)
            report.conflicted = sorted(conflicted)
            report.skipped = sorted(skipped)
            return report

        from deepseek_tui.workspace.managed_worktree import apply_raw_path_images

        attempted_raw: list[_RawRestoreBatch] = []
        attempted_text: list[tuple[Path, str, _PathState]] = []
        failure_kind: str | None = None
        for batch in raw_batches:
            attempted_raw.append(batch)
            try:
                raw_report = await apply_raw_path_images(
                    batch.root,
                    batch.original,
                    batch.target,
                    target="post",
                )
            except Exception:  # noqa: BLE001 — rollback the attempted plan
                logger.debug(
                    "turn_checkpoint_raw_restore_failed root=%s",
                    batch.root,
                    exc_info=True,
                )
                failure_kind = STATUS_SKIPPED
                break
            if raw_report.conflicted or raw_report.skipped:
                failure_kind = (
                    STATUS_CONFLICTED
                    if raw_report.conflicted
                    else STATUS_SKIPPED
                )
                break

        if failure_kind is None:
            for target, path, state in changes:
                if not _disk_matches_image(
                    target, path, state.on_disk, state.on_disk_mode
                ):
                    failure_kind = STATUS_CONFLICTED
                    break
                attempted_text.append((target, path, state))
                try:
                    _write_pre_image(
                        target, path, state.current, state.current_mode
                    )
                except OSError:
                    logger.debug(
                        "turn_checkpoint_restore_failed path=%s root=%s",
                        path,
                        target,
                        exc_info=True,
                    )
                    failure_kind = STATUS_SKIPPED
                    break
                if not _disk_matches_image(
                    target, path, state.current, state.current_mode
                ):
                    failure_kind = STATUS_CONFLICTED
                    break

        if failure_kind is None:
            text_drifted = any(
                not _disk_matches_image(
                    target, path, state.current, state.current_mode
                )
                for target, path, state in attempted_text
            )
            raw_drifted = any(
                _raw_path_signature(batch.root, image.path) != image.signature
                for batch in attempted_raw
                for image in batch.target
            )
            if text_drifted or raw_drifted:
                failure_kind = STATUS_CONFLICTED

        if failure_kind is not None:
            rollback_conflicts: set[str] = set()
            rollback_skipped: set[str] = set()
            for target, path, state in reversed(attempted_text):
                if _disk_matches_image(
                    target, path, state.on_disk, state.on_disk_mode
                ):
                    continue
                if not _disk_matches_image(
                    target, path, state.current, state.current_mode
                ):
                    rollback_conflicts.add(path)
                    continue
                try:
                    _write_pre_image(
                        target, path, state.on_disk, state.on_disk_mode
                    )
                except OSError:
                    rollback_skipped.add(path)
                    logger.error(
                        "turn_checkpoint_restore_rollback_failed path=%s root=%s",
                        path,
                        target,
                        exc_info=True,
                    )
                    continue
                if not _disk_matches_image(
                    target, path, state.on_disk, state.on_disk_mode
                ):
                    rollback_conflicts.add(path)
            for batch in reversed(attempted_raw):
                for original, target_image in reversed(
                    list(zip(batch.original, batch.target, strict=True))
                ):
                    raw_rollback = await apply_raw_path_images(
                        batch.root,
                        [original],
                        [target_image],
                        target="pre",
                    )
                    rollback_conflicts.update(raw_rollback.conflicted)
                    rollback_skipped.update(raw_rollback.skipped)
            if failure_kind == STATUS_CONFLICTED or rollback_conflicts:
                conflicted.update(transaction_paths)
            else:
                skipped.update(transaction_paths)
            conflicted.update(rollback_conflicts)
            skipped.update(rollback_skipped)
            restored.difference_update(transaction_paths)
            merged.difference_update(transaction_paths)
        else:
            for _target, path, state in changes:
                if state.status == STATUS_MERGED:
                    merged.add(path)
                else:
                    restored.add(path)
            restored.update(raw_paths)
        skipped.difference_update(conflicted)
        report.restored = sorted(restored)
        report.merged = sorted(merged)
        report.conflicted = sorted(conflicted)
        report.skipped = sorted(skipped)
        return report

    async def preview(
        self, turn_ids_newest_first: list[str], workspace: Path
    ) -> dict[str, str]:
        """Dry-run of :meth:`restore`: per-path outcome, disk untouched."""
        statuses, _report = await self.preview_report(
            turn_ids_newest_first, workspace
        )
        return statuses

    async def preview_report(
        self, turn_ids_newest_first: list[str], workspace: Path
    ) -> tuple[dict[str, str], RestoreReport]:
        """Dry-run plus the full report (missing roots, skipped turns)."""
        _fallback, report, states = await self._plan(
            turn_ids_newest_first, workspace, force=False
        )
        statuses = {
            path: (state.status or STATUS_SKIPPED)
            for (_root, path), state in states.items()
        }
        raw_current: dict[tuple[str, str], str] = {}
        raw_done: set[tuple[str, str]] = set()
        for turn_id in turn_ids_newest_first:
            checkpoint = self.load(turn_id)
            if checkpoint is None:
                continue
            raw_paths = sorted(
                set(checkpoint.raw_pre_images) | set(checkpoint.raw_post_images)
            )
            if not raw_paths:
                continue
            target = _root_for_checkpoint(checkpoint, _fallback)
            if target is None:
                for path in raw_paths:
                    statuses[path] = STATUS_SKIPPED
                continue
            if set(checkpoint.raw_pre_images) != set(
                checkpoint.raw_post_images
            ):
                for path in raw_paths:
                    statuses[path] = STATUS_SKIPPED
                continue
            root_key = str(target)
            for path in raw_paths:
                key = (root_key, path)
                if key in raw_done:
                    continue
                current = raw_current.setdefault(
                    key, _raw_path_signature(target, path)
                )
                pre = str(checkpoint.raw_pre_images[path]["signature"])
                post = str(checkpoint.raw_post_images[path]["signature"])
                if current in {pre, post}:
                    raw_current[key] = pre
                    statuses[path] = STATUS_RESTORED
                else:
                    statuses[path] = STATUS_CONFLICTED
                    raw_done.add(key)
        return statuses, report

    async def _plan(
        self,
        turn_ids_newest_first: list[str],
        workspace: Path,
        *,
        force: bool,
    ) -> tuple[Path, RestoreReport, dict[tuple[str, str], _PathState]]:
        fallback = _resolved_root(workspace)
        report = RestoreReport()
        states: dict[tuple[str, str], _PathState] = {}
        missing_roots: set[str] = set()
        for turn_id in turn_ids_newest_first:
            checkpoint = self.load(turn_id)
            if checkpoint is None:
                report.turns_without_checkpoint.append(turn_id)
                continue
            root = _root_for_checkpoint(checkpoint, fallback)
            if root is None:
                recorded = checkpoint.execution_root or ""
                missing_roots.add(recorded)
                for path in checkpoint.mutated:
                    key = (recorded, path)
                    state = states.get(key)
                    if state is None:
                        state = _PathState(on_disk=_Unreadable(), current=_Unreadable())
                        states[key] = state
                    state.status = STATUS_SKIPPED
                    state.done = True
                continue
            root_key = str(root)
            for path in checkpoint.mutated:
                if (
                    path in checkpoint.raw_pre_images
                    or path in checkpoint.raw_post_images
                ):
                    continue
                key = (root_key, path)
                state = states.get(key)
                if state is None:
                    on_disk = await asyncio.to_thread(_read_disk, root, path)
                    on_disk_mode = await asyncio.to_thread(
                        _read_regular_mode, root, path
                    )
                    state = _PathState(
                        on_disk=on_disk,
                        current=on_disk,
                        on_disk_mode=on_disk_mode,
                        current_mode=on_disk_mode,
                    )
                    states[key] = state
                if state.done:
                    continue
                pre = await self._resolve_pre_image(root, checkpoint, path)
                if isinstance(pre, _Unresolvable):
                    # An older checkpoint may still resolve this path.
                    if state.status is None:
                        state.status = STATUS_SKIPPED
                    continue
                post = checkpoint.post_contents.get(path, _MISSING)
                pre_mode = await self._resolve_pre_mode(
                    root, checkpoint, path, pre
                )
                post_mode = checkpoint.post_modes.get(path, _MISSING)
                uncertain = (
                    path in checkpoint.uncertain
                    and path not in checkpoint.pre_contents
                )
                current = state.current
                mode_aware = all(
                    _known_mode(value)
                    for value in (pre_mode, post_mode, state.current_mode)
                )
                mode_changed = mode_aware and pre_mode != post_mode
                if current == pre and (
                    not mode_changed or state.current_mode == pre_mode
                ):
                    # Already at this turn's start state.
                    state.current = pre
                    state.current_mode = _mode_for_pre_image(
                        current_mode=state.current_mode,
                        pre=pre,
                        pre_mode=pre_mode,
                        mode_aware=mode_aware,
                        mode_changed=mode_changed,
                        restoring=False,
                    )
                    state.status = STATUS_RESTORED
                    continue
                post_matches = post is not _MISSING and current == post
                if post_matches and mode_aware and (uncertain or mode_changed):
                    post_matches = state.current_mode == post_mode
                if post_matches:
                    # Exactly what this turn left behind — safe to roll back.
                    state.current = pre
                    state.current_mode = _mode_for_pre_image(
                        current_mode=state.current_mode,
                        pre=pre,
                        pre_mode=pre_mode,
                        mode_aware=mode_aware,
                        mode_changed=mode_changed,
                        restoring=True,
                    )
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
                    state.current_mode = _mode_for_pre_image(
                        current_mode=state.current_mode,
                        pre=pre,
                        pre_mode=pre_mode,
                        mode_aware=mode_aware,
                        mode_changed=mode_changed,
                        restoring=True,
                    )
                    state.status = STATUS_RESTORED
                    continue
                if (
                    not uncertain
                    and isinstance(post, str)
                    and isinstance(current, str)
                    and isinstance(pre, str)
                ):
                    merge_mode = state.current_mode
                    mode_safe = True
                    if mode_changed:
                        mode_safe = state.current_mode in {pre_mode, post_mode}
                        merge_mode = pre_mode
                    merged = (
                        await _merge3(base=post, ours=current, theirs=pre)
                        if mode_safe
                        else None
                    )
                    if merged is not None:
                        state.current = merged
                        state.current_mode = merge_mode
                        state.status = STATUS_MERGED
                        continue
                if force:
                    state.current = pre
                    state.current_mode = _mode_for_pre_image(
                        current_mode=state.current_mode,
                        pre=pre,
                        pre_mode=pre_mode,
                        mode_aware=mode_aware,
                        mode_changed=mode_changed,
                        restoring=True,
                    )
                    state.status = STATUS_RESTORED
                    continue
                state.current = state.on_disk
                state.status = STATUS_CONFLICTED
                state.done = True
        report.missing_roots = sorted(missing_roots)
        return fallback, report, states

    async def _resolve_pre_image(
        self, root: Path, checkpoint: TurnCheckpoint, path: str
    ) -> str | None | _Unresolvable:
        if path in checkpoint.pre_contents:
            return checkpoint.pre_contents[path]
        if checkpoint.is_git and checkpoint.head:
            image = await asyncio.to_thread(
                _read_git_pre_image, root, checkpoint.head, path
            )
            if isinstance(image, _GitPreImage):
                return image.content
            if isinstance(image, _GitPathAbsent):
                # A successful exact tree lookup proved the path was absent.
                return None
            # Git unavailable, timeout, corrupt object, binary, symlink, etc.
            # None must never mean both "absent" and "command failed": doing
            # so would turn a transient Git error into a destructive unlink.
            return _Unresolvable()
        return _Unresolvable()

    async def _resolve_pre_mode(
        self,
        root: Path,
        checkpoint: TurnCheckpoint,
        path: str,
        pre: str | None,
    ) -> int | None | Any:
        if path in checkpoint.pre_modes:
            return checkpoint.pre_modes[path]
        if pre is None:
            return None
        if checkpoint.is_git and checkpoint.head:
            image = await asyncio.to_thread(
                _read_git_pre_image, root, checkpoint.head, path
            )
            if isinstance(image, _GitPreImage):
                return image.mode
            if isinstance(image, _GitPathAbsent):
                return None
        return _MISSING

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
        shutil.rmtree(self._raw_sidecar_dir(turn_id), ignore_errors=True)

    def prune_older_than(
        self,
        max_age_days: int,
        *,
        protected_turn_ids: set[str] | None = None,
    ) -> int:
        """Delete old unreachable checkpoints and return the removal count.

        A live thread's checkpoints are part of its rollback/publication
        journal and must never disappear solely because wall-clock time passed.
        """
        if max_age_days < 1:
            return 0
        protected = protected_turn_ids or set()
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        for path in list(self._root.glob("*.json")):
            if path.stem in protected:
                continue
            checkpoint = self.load(path.stem)
            if checkpoint is None:
                # Unreadable / corrupt — reclaim the file.
                path.unlink(missing_ok=True)
                shutil.rmtree(self._raw_sidecar_dir(path.stem), ignore_errors=True)
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
                shutil.rmtree(self._raw_sidecar_dir(path.stem), ignore_errors=True)
                removed += 1
        return removed


class _Unresolvable:
    """Sentinel: no pre-image available (non-git workspace, none recorded)."""


class _Unreadable:
    """Sentinel: file exists but cannot be compared (binary/oversized)."""


@dataclass(slots=True)
class _GitPreImage:
    content: str
    mode: int


class _GitPathAbsent:
    """Sentinel: an exact successful tree lookup proved path absence."""


def _raw_path_signature(root: Path, rel: str) -> str:
    try:
        path = _exact_checkpoint_path(root, rel)
        info = path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "path:unreadable"
    mode = stat.S_IMODE(info.st_mode)
    digest = hashlib.sha256()
    if stat.S_ISLNK(info.st_mode):
        try:
            digest.update(
                os.readlink(path).encode("utf-8", errors="surrogateescape")
            )
        except OSError:
            return f"symlink:{mode:o}:unreadable"
        return f"symlink:{mode:o}:{digest.hexdigest()}"
    if not stat.S_ISREG(info.st_mode):
        return f"other-{stat.S_IFMT(info.st_mode):o}:{mode:o}:{digest.hexdigest()}"
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return f"file:{mode:o}:unreadable"
    return f"file:{mode:o}:{digest.hexdigest()}"


def _same_raw_stat(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev == second.st_dev
        and first.st_ino == second.st_ino
        and first.st_mode == second.st_mode
        and first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
    )


def _capture_raw_sidecar_image(
    root: Path, rel: str, payload: Path
) -> dict[str, Any]:
    """Capture one exact file/symlink/missing image without following links."""
    target = _exact_checkpoint_path(root, rel)
    try:
        before = target.lstat()
    except FileNotFoundError:
        return {"kind": "missing", "mode": None, "signature": "missing"}
    except OSError as exc:
        raise RawCheckpointError([rel], "raw path could not be read") from exc
    mode = stat.S_IMODE(before.st_mode)
    payload.parent.mkdir(parents=True, exist_ok=True)
    if stat.S_ISLNK(before.st_mode):
        try:
            data = os.readlink(target).encode("utf-8", errors="surrogateescape")
            after = target.lstat()
        except OSError as exc:
            raise RawCheckpointError([rel], "symlink changed while captured") from exc
        if not _same_raw_stat(before, after):
            raise RawCheckpointError([rel], "symlink changed while captured")
        payload.write_bytes(data)
        with payload.open("rb") as handle:
            os.fsync(handle.fileno())
        signature = f"symlink:{mode:o}:{hashlib.sha256(data).hexdigest()}"
        return {"kind": "symlink", "mode": mode, "signature": signature}
    if not stat.S_ISREG(before.st_mode):
        raise RawCheckpointError(
            [rel], "directories and special paths cannot be published as raw images"
        )

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise RawCheckpointError([rel], "raw file changed while captured") from exc
    digest = hashlib.sha256()
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or not _same_raw_stat(before, opened):
            raise RawCheckpointError([rel], "raw file changed while captured")
        with payload.open("wb") as output:
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        closed = os.fstat(fd)
    finally:
        os.close(fd)
    try:
        after = target.lstat()
    except OSError as exc:
        raise RawCheckpointError([rel], "raw file changed while captured") from exc
    if not _same_raw_stat(opened, closed) or not _same_raw_stat(closed, after):
        raise RawCheckpointError([rel], "raw file changed while captured")
    signature = f"file:{mode:o}:{digest.hexdigest()}"
    return {"kind": "file", "mode": mode, "signature": signature}


def _resolved_root(workspace: Path) -> Path:
    return workspace.expanduser().resolve()


def _read_git_pre_image(
    root: Path, head: str, rel: str
) -> _GitPreImage | _GitPathAbsent | _Unresolvable:
    """Read one exact regular-file blob while distinguishing Git failure."""
    try:
        _exact_checkpoint_path(root, rel)
        listed = subprocess.run(
            [
                "git",
                "ls-tree",
                "-z",
                "--full-tree",
                head,
                "--",
                f":(literal){rel}",
            ],
            cwd=str(root),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _Unresolvable()
    if listed.returncode != 0:
        return _Unresolvable()
    if not listed.stdout:
        return _GitPathAbsent()
    try:
        header, _listed_path = listed.stdout.rstrip(b"\0").split(b"\t", 1)
        raw_mode, object_type, object_id = header.split(b" ", 2)
        mode = int(raw_mode, 8)
    except (ValueError, TypeError):
        return _Unresolvable()
    if object_type != b"blob" or mode not in {0o100644, 0o100755}:
        return _Unresolvable()
    try:
        blob = subprocess.run(
            ["git", "cat-file", "blob", object_id.decode("ascii")],
            cwd=str(root),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, UnicodeDecodeError, subprocess.TimeoutExpired):
        return _Unresolvable()
    data = blob.stdout
    if (
        blob.returncode != 0
        or len(data) > _MAX_IMAGE_BYTES
        or b"\0" in data[:_BINARY_SNIFF_BYTES]
    ):
        return _Unresolvable()
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return _Unresolvable()
    return _GitPreImage(content=content, mode=stat.S_IMODE(mode))


def _existing_checkpoint_root(checkpoint: TurnCheckpoint) -> Path | None:
    raw = checkpoint.execution_root or ""
    if not raw:
        return None
    root = Path(raw).expanduser()
    if not root.is_dir():
        return None
    return root.resolve()


def _root_for_checkpoint(checkpoint: TurnCheckpoint, fallback: Path) -> Path | None:
    """Pinned capture root, or ``fallback`` for legacy checkpoints.

    Returns None when a recorded root is no longer on disk — restore must
    not retarget those files onto the current workspace.
    """
    raw = checkpoint.execution_root or ""
    if not raw:
        return fallback
    path = Path(raw).expanduser()
    if not path.is_dir():
        return None
    return path.resolve()


def _read_disk(root: Path, rel: str) -> str | None | _Unreadable:
    """Current file text; None when absent; _Unreadable when not comparable."""
    try:
        path = _exact_checkpoint_path(root, rel)
    except OSError:
        return _Unreadable()
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return _Unreadable()
        if info.st_size > _MAX_IMAGE_BYTES:
            return _Unreadable()
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return _Unreadable()
    if b"\0" in data[:_BINARY_SNIFF_BYTES]:
        return _Unreadable()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return _Unreadable()


def _disk_matches_image(
    root: Path, rel: str, expected: Any, expected_mode: Any = _MISSING
) -> bool:
    """Fail-closed comparison used at the restore write boundary."""
    if isinstance(expected, _Unreadable):
        return False
    current = _read_disk(root, rel)
    if isinstance(current, _Unreadable) or current != expected:
        return False
    if not _known_mode(expected_mode):
        return True
    return _read_regular_mode(root, rel) == expected_mode


def _known_mode(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def _mode_for_pre_image(
    *,
    current_mode: Any,
    pre: str | None,
    pre_mode: Any,
    mode_aware: bool,
    mode_changed: bool,
    restoring: bool,
) -> Any:
    """Select only a mode the checkpoint can legitimately roll back."""
    if pre is None:
        return None
    if _known_mode(pre_mode) and (
        mode_changed or (not mode_aware and restoring)
    ):
        return pre_mode
    # When pre/post modes are equal, the turn did not own a chmod. Preserve a
    # mode that may have been applied independently after the turn.
    return current_mode


def _read_regular_mode(root: Path, rel: str) -> int | None | Any:
    """Permission bits for a regular file, None for absence, else unknown."""
    try:
        info = _exact_checkpoint_path(root, rel).lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return _MISSING
    if not stat.S_ISREG(info.st_mode):
        return _MISSING
    return stat.S_IMODE(info.st_mode)


def _mode_matching_content(
    root: Path, rel: str, content: str | None
) -> int | None | Any:
    """Capture mode only when disk still matches the supplied text image."""
    current = _read_disk(root, rel)
    if isinstance(current, _Unreadable) or current != content:
        return _MISSING
    return _read_regular_mode(root, rel)


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


def _write_pre_image(
    root: Path,
    rel: str,
    content: str | None,
    mode: int | None | Any = _MISSING,
) -> None:
    target = _exact_checkpoint_path(root, rel)
    if content is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not _known_mode(mode):
            write_text_atomic(target, content)
            return
        fd, tmp_path = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
        try:
            fchmod = getattr(os, "fchmod", None)
            if mode is not None and fchmod is not None:
                fchmod(fd, mode)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None and fchmod is None:
                os.chmod(tmp_path, mode)
            os.replace(tmp_path, target)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return
    try:
        info = target.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(info.st_mode):
        raise OSError(f"refusing checkpoint delete of directory: {rel!r}")
    target.unlink()


def _exact_checkpoint_path(root: Path, rel: str) -> Path:
    root = root.expanduser().resolve()
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise OSError(f"checkpoint path escapes workspace: {rel!r}")
    target = root / candidate
    try:
        target.parent.resolve().relative_to(root)
    except ValueError as exc:
        raise OSError(f"checkpoint path escapes workspace: {rel!r}") from exc
    return target
