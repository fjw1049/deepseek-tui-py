"""Per-turn file checkpoints backing rewind / code-restore.

Each turn gets one JSON file (``<root>/<turn_id>.json``) recording every
workspace path the turn mutated plus, where known, the file's pre-turn
content. Restoring walks the affected turns newest-to-oldest and writes each
turn's pre-turn content back unconditionally, so the final on-disk state is
the oldest restored turn's pre-image — exactly the state before those turns
ran. Per path the pre-image resolves as:

1. ``pre_contents[path]`` when recorded (``None`` = file did not exist then,
   so restore deletes it);
2. otherwise ``git show <head>:<path>`` for git workspaces (the path missing
   from HEAD means it did not exist then -> restore deletes it; a blob that
   is not UTF-8 text is unrecoverable -> skipped, never deleted);
3. otherwise the path cannot be restored and lands in
   :attr:`RestoreReport.skipped`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.utils import write_json_atomic, write_text_atomic
from deepseek_tui.workspace.git_reconcile import _run_git
from deepseek_tui.workspace.shell_mutation_watch import ShellMutationSnapshot

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TurnCheckpoint:
    turn_id: str
    is_git: bool
    # HEAD sha at turn start (git workspaces only).
    head: str | None = None
    # path (posix, workspace-relative) -> pre-turn content; None = absent then.
    pre_contents: dict[str, str | None] = field(default_factory=dict)
    # Every path mutated this turn (ordered, deduplicated).
    mutated: list[str] = field(default_factory=list)
    # Owning thread (one directory is shared across threads) and creation
    # time (epoch seconds) for newest-first restore ordering. Both default
    # for checkpoints written before these fields existed.
    thread_id: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "is_git": self.is_git,
            "head": self.head,
            "pre_contents": self.pre_contents,
            "mutated": self.mutated,
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
            mutated=[str(p) for p in raw.get("mutated") or []],
            thread_id=str(raw.get("thread_id") or ""),
            created_at=float(raw.get("created_at") or 0.0),
        )


@dataclass(slots=True)
class RestoreReport:
    # Paths written back or deleted (sorted, deduplicated).
    restored: list[str] = field(default_factory=list)
    # Mutated paths whose pre-image could not be resolved in any turn.
    skipped: list[str] = field(default_factory=list)
    # Turn ids with no checkpoint on disk (nothing recorded for them).
    turns_without_checkpoint: list[str] = field(default_factory=list)


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

    def record_out_of_band(self, turn_id: str, path: str) -> None:
        """Note a shell/git-side mutation; pre-image resolved at restore time."""
        norm = path.replace("\\", "/")
        with self._lock:
            checkpoint = self.load(turn_id)
            if checkpoint is None or norm in checkpoint.mutated:
                return
            checkpoint.mutated.append(norm)
            self._save(checkpoint)

    async def restore(self, turn_ids_newest_first: list[str], workspace: Path) -> RestoreReport:
        """Write every affected turn's pre-image back, newest to oldest."""
        root = _resolved_root(workspace)
        report = RestoreReport()
        resolved: set[str] = set()
        unresolved: set[str] = set()
        for turn_id in turn_ids_newest_first:
            checkpoint = self.load(turn_id)
            if checkpoint is None:
                report.turns_without_checkpoint.append(turn_id)
                continue
            for path in checkpoint.mutated:
                content = await self._resolve_pre_image(root, checkpoint, path)
                if isinstance(content, _Unresolvable):
                    if path not in resolved:
                        unresolved.add(path)
                    continue
                try:
                    _write_pre_image(root, path, content)
                except OSError:
                    logger.debug(
                        "turn_checkpoint_restore_failed path=%s",
                        path,
                        exc_info=True,
                    )
                    if path not in resolved:
                        unresolved.add(path)
                    continue
                resolved.add(path)
                unresolved.discard(path)
        report.restored = sorted(resolved)
        report.skipped = sorted(unresolved)
        return report

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


class _Unresolvable:
    """Sentinel: no pre-image available (non-git workspace, none recorded)."""


def _resolved_root(workspace: Path) -> Path:
    return workspace.expanduser().resolve()


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
