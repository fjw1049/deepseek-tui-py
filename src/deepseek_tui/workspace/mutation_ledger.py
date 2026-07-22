"""Per-turn file mutation ledger and folded turn-diff snapshots."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal

from deepseek_tui.workspace.diff_synth import count_diff_stats, truncate_unified_diff

MutationSource = Literal[
    "edit_file",
    "apply_patch",
    "write_file",
    "shell_allowlist",
    "git_reconcile",
]
MutationOp = Literal["create", "update", "delete", "rename"]
MutationStatus = Literal["pending", "applied", "failed"]

# Cap SSE/item detail size; full text remains available via item fetch when truncated.
DEFAULT_DIFF_MAX_CHARS = 48_000


@dataclass(slots=True)
class FileMutation:
    mutation_id: str
    turn_id: str
    path: str
    op: MutationOp
    unified_diff: str
    additions: int
    deletions: int
    source: MutationSource
    status: MutationStatus = "applied"
    tool_call_id: str | None = None
    agent_id: str | None = None
    old_path: str | None = None
    # 1-based line of the first change in the NEW file; None when unknown.
    line_start: int | None = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    detail_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TurnFileFold:
    path: str
    op: MutationOp
    additions: int
    deletions: int
    unified_diff: str
    detail_truncated: bool = False
    line_start: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TurnDiffSnapshot:
    turn_id: str
    files: tuple[TurnFileFold, ...]
    totals: dict[str, int]
    revision: int
    merged_unified_diff: str
    complete: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "files": [f.to_dict() for f in self.files],
            "totals": dict(self.totals),
            "revision": self.revision,
            "merged_unified_diff": self.merged_unified_diff,
            "complete": self.complete,
        }


def mutation_to_dict(mutation: FileMutation) -> dict[str, Any]:
    return mutation.to_dict()


def mutation_from_metadata(
    meta: dict[str, Any] | None,
    *,
    turn_id: str,
    tool_call_id: str | None = None,
    agent_id: str | None = None,
    source_fallback: MutationSource = "write_file",
) -> list[FileMutation]:
    """Extract FileMutation list from tool result metadata."""
    if not isinstance(meta, dict):
        return []
    out: list[FileMutation] = []
    raw_list = meta.get("mutations")
    if isinstance(raw_list, list) and raw_list:
        for entry in raw_list:
            m = _one_mutation_from_dict(
                entry,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                agent_id=agent_id,
                source_fallback=source_fallback,
                path_fallback=meta.get("path") if isinstance(meta.get("path"), str) else None,
            )
            if m is not None:
                out.append(m)
        return out
    single = meta.get("mutation")
    if isinstance(single, dict):
        m = _one_mutation_from_dict(
            single,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            agent_id=agent_id,
            source_fallback=source_fallback,
            path_fallback=meta.get("path") if isinstance(meta.get("path"), str) else None,
        )
        if m is not None:
            out.append(m)
    return out


def _one_mutation_from_dict(
    entry: Any,
    *,
    turn_id: str,
    tool_call_id: str | None,
    agent_id: str | None,
    source_fallback: MutationSource,
    path_fallback: str | None,
) -> FileMutation | None:
    if not isinstance(entry, dict):
        return None
    path = entry.get("path") or path_fallback
    if not isinstance(path, str) or not path.strip():
        return None
    path = path.replace("\\", "/").strip()
    unified = entry.get("unified_diff")
    if not isinstance(unified, str):
        unified = ""
    stats = count_diff_stats(unified) if unified else None
    additions = entry.get("additions")
    deletions = entry.get("deletions")
    if not isinstance(additions, int):
        additions = stats.additions if stats else 0
    if not isinstance(deletions, int):
        deletions = stats.deletions if stats else 0
    op_raw = entry.get("op")
    op: MutationOp = (
        op_raw
        if op_raw in ("create", "update", "delete", "rename")
        else "update"
    )
    source_raw = entry.get("source")
    source: MutationSource = (
        source_raw
        if source_raw
        in ("edit_file", "apply_patch", "write_file", "shell_allowlist", "git_reconcile")
        else source_fallback
    )
    status_raw = entry.get("status")
    status: MutationStatus = (
        status_raw if status_raw in ("pending", "applied", "failed") else "applied"
    )
    mid = entry.get("mutation_id")
    if not isinstance(mid, str) or not mid.strip():
        mid = f"mut_{uuid.uuid4().hex[:12]}"
    old_path = entry.get("old_path")
    line_start_raw = entry.get("line_start")
    line_start = (
        line_start_raw
        if isinstance(line_start_raw, int) and not isinstance(line_start_raw, bool)
        else None
    )
    return FileMutation(
        mutation_id=mid,
        turn_id=turn_id,
        path=path,
        op=op,
        unified_diff=unified,
        additions=max(0, additions),
        deletions=max(0, deletions),
        source=source,
        status=status,
        tool_call_id=tool_call_id,
        agent_id=agent_id if isinstance(agent_id, str) else None,
        old_path=old_path if isinstance(old_path, str) else None,
        line_start=line_start,
        detail_truncated=bool(entry.get("detail_truncated")),
    )


class TurnMutationLedger:
    """Accumulates mutations for one turn; folds by path for snapshots."""

    def __init__(
        self,
        turn_id: str,
        *,
        diff_max_chars: int = DEFAULT_DIFF_MAX_CHARS,
        on_snapshot: Callable[[TurnDiffSnapshot], None] | None = None,
        throttle_ms: int = 150,
    ) -> None:
        self.turn_id = turn_id
        self._diff_max_chars = diff_max_chars
        self._on_snapshot = on_snapshot
        self._throttle_ms = max(0, throttle_ms)
        self._history: list[FileMutation] = []
        self._revision = 0
        self._complete = False
        self._last_emit_ms = 0
        self._pending_emit = False

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def history(self) -> tuple[FileMutation, ...]:
        return tuple(self._history)

    def covered_paths(self) -> set[str]:
        return {
            m.path.replace("\\", "/")
            for m in self._history
            if m.status == "applied"
        }

    def commit(self, mutation: FileMutation, *, emit: bool = True) -> TurnDiffSnapshot:
        if mutation.turn_id != self.turn_id:
            mutation.turn_id = self.turn_id
        # Preserve authentic +/− even when the stored patch body is truncated.
        if mutation.additions == 0 and mutation.deletions == 0 and mutation.unified_diff:
            stats = count_diff_stats(mutation.unified_diff)
            mutation.additions = stats.additions
            mutation.deletions = stats.deletions
        diff, truncated = truncate_unified_diff(
            mutation.unified_diff, self._diff_max_chars
        )
        if truncated:
            mutation.unified_diff = diff
            mutation.detail_truncated = True
        self._history.append(mutation)
        self._revision += 1
        snap = self.snapshot()
        if emit:
            self._emit(snap, force=False)
        return snap

    def mark_complete(self, *, emit: bool = True) -> TurnDiffSnapshot:
        self._complete = True
        self._revision += 1
        snap = self.snapshot()
        if emit:
            self._emit(snap, force=True)
        return snap

    def snapshot(self) -> TurnDiffSnapshot:
        folded = self._fold_by_path()
        totals = {
            "files": len(folded),
            "additions": sum(f.additions for f in folded),
            "deletions": sum(f.deletions for f in folded),
        }
        merged_parts = [f.unified_diff.rstrip() for f in folded if f.unified_diff.strip()]
        merged = "\n\n".join(merged_parts)
        if merged and not merged.endswith("\n"):
            merged += "\n"
        return TurnDiffSnapshot(
            turn_id=self.turn_id,
            files=tuple(folded),
            totals=totals,
            revision=self._revision,
            merged_unified_diff=merged,
            complete=self._complete,
        )

    def flush(self) -> TurnDiffSnapshot | None:
        """Force emit latest snapshot if a throttled emit was pending."""
        if not self._pending_emit and self._revision == 0:
            return None
        snap = self.snapshot()
        self._emit(snap, force=True)
        return snap

    def _fold_by_path(self) -> list[TurnFileFold]:
        latest: dict[str, FileMutation] = {}
        for m in self._history:
            if m.status != "applied":
                continue
            key = m.path.replace("\\", "/")
            latest[key] = m
        folds: list[TurnFileFold] = []
        for path in sorted(latest):
            m = latest[path]
            folds.append(
                TurnFileFold(
                    path=path,
                    op=m.op,
                    additions=m.additions,
                    deletions=m.deletions,
                    unified_diff=m.unified_diff,
                    detail_truncated=m.detail_truncated,
                    line_start=m.line_start,
                )
            )
        return folds

    def _emit(self, snap: TurnDiffSnapshot, *, force: bool) -> None:
        if self._on_snapshot is None:
            return
        now = int(time.time() * 1000)
        if (
            not force
            and self._throttle_ms > 0
            and now - self._last_emit_ms < self._throttle_ms
        ):
            self._pending_emit = True
            return
        self._pending_emit = False
        self._last_emit_ms = now
        self._on_snapshot(snap)


def build_mutation_metadata(
    *,
    path: str,
    op: MutationOp,
    unified_diff: str,
    additions: int,
    deletions: int,
    source: MutationSource,
    line_start: int | None = None,
) -> dict[str, Any]:
    """Compact mutation dict for ToolResult.metadata."""
    mutation: dict[str, Any] = {
        "path": path.replace("\\", "/"),
        "op": op,
        "unified_diff": unified_diff,
        "additions": additions,
        "deletions": deletions,
        "source": source,
        "status": "applied",
    }
    if line_start is not None:
        mutation["line_start"] = line_start
    return {
        "path": path.replace("\\", "/"),
        "mutation": mutation,
    }
