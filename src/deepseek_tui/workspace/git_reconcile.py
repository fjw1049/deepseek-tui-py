"""Turn-start baseline and turn-end git reconcile for orphan disk writes."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
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
    porcelain = await _run_git(root, ["status", "--porcelain", "-uall"]) or ""
    dirty = _paths_from_porcelain(porcelain)
    # Also treat currently-untracked files as pre-existing dirt.
    for path in await _list_untracked(root):
        dirty.add(path.replace("\\", "/"))
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
) -> list[FileMutation]:
    """Append git_reconcile mutations for disk deltas *introduced this turn*."""
    if not baseline.is_git:
        return []
    root = baseline.workspace
    patch = await _run_git(root, ["diff", "--no-ext-diff", "--no-color", "HEAD"])
    untracked = await _list_untracked(root)
    covered = ledger.covered_paths()
    pre_dirty = {p.replace("\\", "/") for p in baseline.dirty_at_start}
    added: list[FileMutation] = []

    file_patches = _split_unified_diff_by_file(patch or "")
    for path, unified in file_patches.items():
        norm = path.replace("\\", "/")
        if norm in covered or norm in pre_dirty:
            continue
        stats = count_diff_stats(unified)
        op = "create" if "--- /dev/null" in unified else "update"
        if "\n+++ /dev/null" in unified or unified.rstrip().endswith("+++ /dev/null"):
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
        norm = path.replace("\\", "/")
        if norm in covered or norm in pre_dirty:
            continue
        try:
            content = (root / norm).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
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

    return added


def _paths_from_porcelain(porcelain: str) -> set[str]:
    paths: set[str] = set()
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        entry = line[3:].strip()
        if " -> " in entry:
            # rename: include both sides so neither is attributed to this turn
            left, right = entry.split(" -> ", 1)
            if left.strip():
                paths.add(left.strip().replace("\\", "/"))
            entry = right
        if entry:
            # git quotes paths with spaces: "my file.py"
            if entry.startswith('"') and entry.endswith('"'):
                entry = entry[1:-1].encode("utf-8").decode("unicode_escape")
            paths.add(entry.replace("\\", "/"))
    return paths


def _split_unified_diff_by_file(patch: str) -> dict[str, str]:
    if not patch.strip():
        return {}
    chunks = re_split_diff(patch)
    out: dict[str, str] = {}
    for chunk in chunks:
        path = _path_from_diff_chunk(chunk)
        if path:
            out[path] = chunk if chunk.endswith("\n") else chunk + "\n"
    return out


def re_split_diff(patch: str) -> list[str]:
    lines = patch.splitlines(keepends=True)
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("diff --git ") and current:
            chunks.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("".join(current))
    return chunks


def _path_from_diff_chunk(chunk: str) -> str | None:
    for line in chunk.splitlines():
        if line.startswith("+++ b/"):
            return line[6:].strip()
        if line.startswith("+++ "):
            p = line[4:].strip()
            if p != "/dev/null":
                return p[2:] if p.startswith("b/") else p
        if line.startswith("diff --git "):
            # Prefer the b/ side; handle spaces via `b/<path>` after the a/ token.
            marker = " b/"
            idx = line.find(marker)
            if idx >= 0:
                return line[idx + len(marker) :].strip()
    return None


async def _is_git_repo(root: Path) -> bool:
    out = await _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    return (out or "").strip() == "true"


async def _list_untracked(root: Path) -> list[str]:
    out = await _run_git(
        root, ["ls-files", "--others", "--exclude-standard", "-z"]
    )
    if not out:
        return []
    return [p.replace("\\", "/") for p in out.split("\0") if p.strip()]


async def _run_git(root: Path, args: list[str]) -> str | None:
    def _run() -> str | None:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("git_reconcile_failed args=%s err=%s", args, exc)
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout

    return await asyncio.to_thread(_run)
