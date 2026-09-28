"""Turn-start baseline and turn-end git reconcile for orphan disk writes."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from deepseek_tui.workspace.diff_synth import count_diff_stats, synthesize_unified_diff
from deepseek_tui.workspace.mutation_ledger import FileMutation, TurnMutationLedger

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GitTurnBaseline:
    workspace: Path
    is_git: bool
    head: str | None = None
    porcelain: str = ""
    # Paths already dirty/untracked at turn start — excluded from reconcile.
    dirty_at_start: set[str] = field(default_factory=set)


async def capture_baseline(workspace: Path) -> GitTurnBaseline:
    root = workspace.expanduser().resolve()
    if not await _is_git_repo(root):
        return GitTurnBaseline(workspace=root, is_git=False)
    head = await _run_git(root, ["rev-parse", "HEAD"])
    porcelain = await _run_git(root, ["status", "--porcelain", "-z", "-uall"]) or ""
    dirty = _paths_from_porcelain(porcelain)
    # Also treat currently-untracked files as pre-existing dirt.
    for path in await _list_untracked(root):
        dirty.add((path.replace("\\", "/") if os.name == "nt" else path))
    return GitTurnBaseline(
        workspace=root,
        is_git=True,
        head=(head or "").strip() or None,
        porcelain=porcelain,
        dirty_at_start=dirty,
    )


async def reconcile_to_ledger(
    ledger: TurnMutationLedger,
    baseline: GitTurnBaseline,
    *,
    exclude_paths: Collection[str] = (),
) -> list[FileMutation]:
    """Record otherwise-unattributed disk deltas introduced this turn.

    New dirty paths (not already in the ledger, not dirty at turn start)
    are appended as ``git_reconcile`` mutations.

    Paths already in the ledger keep their turn-start-to-current net diff.
    Replacing those with ``git diff HEAD`` would mix pre-turn workspace dirt
    into a turn receipt.

    ``exclude_paths`` fences off paths known to belong to someone else
    (e.g. other active turns in the same workspace) so they are never
    attributed to this turn.
    """
    if not baseline.is_git:
        return []
    root = baseline.workspace
    # Pin comparison to the turn-start commit even if HEAD moved meanwhile.
    # Attribution remains best-effort; caller-provided exclusions still apply.
    revision = baseline.head
    diff_args = ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames"]
    if revision:
        diff_args.append(revision)
    else:
        diff_args.append("--cached")
    changed = await _run_git(root, [*diff_args, "--name-only", "-z"])
    untracked = await _list_untracked(root)
    covered = ledger.covered_paths()
    pre_dirty = set(baseline.dirty_at_start)
    excluded = {p.replace("\\", "/") if os.name == "nt" else p for p in exclude_paths}
    added: list[FileMutation] = []

    for norm in (changed or "").split("\0"):
        if not norm or norm in pre_dirty or norm in excluded or norm in covered:
            continue
        unified = await _run_git(root, [*diff_args, "--", f":(literal){norm}"])
        if not unified:
            continue
        stats = count_diff_stats(unified)
        header = unified.split("\n@@", 1)[0].splitlines()
        op = "create" if "--- /dev/null" in header else "update"
        if "+++ /dev/null" in header:
            op = "delete"
        mut = FileMutation(
            mutation_id=f"mut_git_{uuid.uuid4().hex[:12]}",
            turn_id=ledger.turn_id,
            path=norm,
            op=op,  # type: ignore[arg-type]
            unified_diff=unified if unified.endswith("\n") else unified + "\n",
            additions=stats.additions,
            deletions=stats.deletions,
            source="git_reconcile",
            status="applied",
        )
        ledger.commit(mut, emit=False)
        added.append(mut)
        covered.add(norm)

    for path in untracked:
        norm = (path.replace("\\", "/") if os.name == "nt" else path)
        if norm in pre_dirty or norm in excluded:
            continue
        if norm in covered:
            continue
        from deepseek_tui.workspace.shell_mutation_watch import _read_file

        content = await asyncio.to_thread(_read_file, root, norm)
        if not isinstance(content, str):
            continue
        unified, stats, op = synthesize_unified_diff(norm, "", content)
        mut = FileMutation(
            mutation_id=f"mut_git_{uuid.uuid4().hex[:12]}",
            turn_id=ledger.turn_id,
            path=norm,
            op=op,  # type: ignore[arg-type]
            unified_diff=unified,
            additions=stats.additions,
            deletions=stats.deletions,
            source="git_reconcile",
            status="applied",
        )
        ledger.commit(mut, emit=False)
        added.append(mut)
        covered.add(norm)

    return added


def _paths_from_porcelain(porcelain: str) -> set[str]:
    """Parse porcelain v1 -z; rename/copy stores destination then source."""
    paths: set[str] = set()
    entries = iter(porcelain.split("\0"))
    for entry in entries:
        if len(entry) < 4:
            continue
        paths.add(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            previous = next(entries, "")
            if previous:
                paths.add(previous)
    return paths


async def _is_git_repo(root: Path) -> bool:
    out = await _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    return (out or "").strip() == "true"


async def _list_untracked(root: Path) -> list[str]:
    out = await _run_git(
        root, ["ls-files", "--others", "--exclude-standard", "-z"]
    )
    if not out:
        return []
    return [p for p in out.split("\0") if p]


async def _run_git(root: Path, args: list[str]) -> str | None:
    def _run() -> str | None:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(root),
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("git_reconcile_failed args=%s err=%s", args, exc)
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", errors="surrogateescape")

    return await asyncio.to_thread(_run)
