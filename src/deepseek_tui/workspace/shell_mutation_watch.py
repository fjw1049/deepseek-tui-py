"""Per-shell-command detection of on-disk source mutations.

The agent can edit files through shell commands (``git apply``, ``patch``,
heredocs) which bypass the tool layer, so no ``file_change`` items or
mutation metadata are emitted for them. This module snapshots the
dirty/untracked file set right before a shell command runs and diffs the
on-disk state right after it completes, yielding mutation dicts in the
``build_mutation_metadata`` inner shape (source ``shell_detected``).

Known limitation: concurrent shell commands in one turn that touch the same
file get merged attribution — the change is reported against whichever
command's post-run detection observes it first.
"""

from __future__ import annotations

import asyncio
import os
import re
import stat
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.workspace.diff_synth import synthesize_unified_diff
from deepseek_tui.workspace.git_reconcile import (
    _is_git_repo,
    _list_untracked,
    _run_git,
)

# Files larger than this are never read for before/after comparison.
_MAX_FILE_BYTES = 512 * 1024
# A NUL byte in the first chunk marks a file as binary.
_BINARY_SNIFF_BYTES = 8192

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", re.MULTILINE)


class _Unreadable:
    """Sentinel: file exists but cannot be diffed (binary/undecodable/large)."""


_UNREADABLE = _Unreadable()


@dataclass(slots=True)
class ShellMutationSnapshot:
    workspace: Path
    is_git: bool
    # path (posix, repo-relative) -> file text at snapshot time; None = absent then.
    contents: dict[str, str | None]
    # Regular-file permission bits; None means the path was absent.
    modes: dict[str, int | None] = field(default_factory=dict)


async def capture_shell_snapshot(workspace: Path) -> ShellMutationSnapshot:
    """Record the current content of every dirty/untracked file."""
    root = workspace.expanduser().resolve()
    if not await _is_git_repo(root):
        return ShellMutationSnapshot(workspace=root, is_git=False, contents={})
    contents: dict[str, str | None] = {}
    modes: dict[str, int | None] = {}
    for path in sorted(await _candidate_paths(root)):
        mode = await asyncio.to_thread(_read_regular_mode, root, path)
        if mode is not _MODE_UNKNOWN:
            modes[path] = mode
        value = await asyncio.to_thread(_read_file, root, path)
        if isinstance(value, _Unreadable):
            continue  # binary/undecodable/oversized — cannot diff safely
        contents[path] = value
    return ShellMutationSnapshot(
        workspace=root, is_git=True, contents=contents, modes=modes
    )


async def detect_shell_mutations(
    snapshot: ShellMutationSnapshot,
    *,
    skip_paths: Collection[str] = (),
    include_contents: bool = False,
) -> list[dict[str, Any]]:
    """Diff the workspace against ``snapshot``; one mutation dict per file."""
    if not snapshot.is_git:
        return []
    root = snapshot.workspace
    skip = {_normalize_relative_path(p) for p in skip_paths}
    candidates = (set(snapshot.contents) | await _candidate_paths(root)) - skip
    mutations: list[dict[str, Any]] = []
    for path in sorted(candidates):
        if path in snapshot.contents:
            before = snapshot.contents[path]
            before_mode = snapshot.modes.get(path, _MODE_UNKNOWN)
        elif path in snapshot.modes:
            before = _UNREADABLE
            before_mode = snapshot.modes[path]
        else:
            # Clean tracked file at snapshot time — HEAD holds the before text.
            before = await _head_content(root, path)
            before_mode = await _head_mode(root, path)
        after = await asyncio.to_thread(_read_file, root, path)
        after_mode = await asyncio.to_thread(_read_regular_mode, root, path)
        content_comparable = not isinstance(before, _Unreadable) and not isinstance(
            after, _Unreadable
        )
        content_changed = content_comparable and before != after
        mode_changed = (
            before_mode is not _MODE_UNKNOWN
            and after_mode is not _MODE_UNKNOWN
            and before_mode != after_mode
        )
        if not content_changed and not mode_changed:
            continue
        # None marks absence, so the op comes from presence, not from the diff
        # text — synthesize_unified_diff would mislabel the deletion of an
        # empty file as a create (old == new == "").
        if content_comparable and before is None:
            op = "create"
        elif content_comparable and after is None:
            op = "delete"
        else:
            op = "update"
        if content_comparable:
            unified, stats, _ = synthesize_unified_diff(
                path, before or "", after or "", op=op
            )
        else:
            unified, stats, _ = synthesize_unified_diff(
                path, "", "", op="update"
            )
        mutation: dict[str, Any] = {
            "path": path,
            "op": op,
            "unified_diff": unified,
            "additions": stats.additions,
            "deletions": stats.deletions,
            "source": "shell_detected",
            "status": "applied",
        }
        line_start = _line_start_for(op, unified)
        if line_start is not None:
            mutation["line_start"] = line_start
        if mode_changed:
            mutation["mode_before"] = before_mode
            mutation["mode_after"] = after_mode
        if include_contents and content_comparable:
            mutation["_before_content"] = before
            mutation["_after_content"] = after
        mutations.append(mutation)
    return mutations


async def _candidate_paths(root: Path) -> set[str]:
    """Tracked files differing from HEAD (staged+unstaged) plus untracked."""
    out = await _run_git(root, ["diff", "--name-only", "-z", "HEAD"])
    paths = {
        _normalize_relative_path(p)
        for p in (out or "").split("\0")
        if p != ""
    }
    paths.update(await _list_untracked(root))
    return paths


async def _head_content(root: Path, rel: str) -> str | None:
    """File text at HEAD; None when the path is not tracked there."""
    try:
        return await _run_git(root, ["show", f"HEAD:{rel}"])
    except UnicodeDecodeError:  # binary blob at HEAD
        return None


async def _head_mode(root: Path, rel: str) -> int | None | object:
    raw = await _run_git(
        root,
        ["ls-files", "--stage", "-z", "--", f":(literal){rel}"],
    )
    if raw is None:
        return _MODE_UNKNOWN
    if raw == "":
        return None
    try:
        return stat.S_IMODE(int(raw.split(" ", 1)[0], 8))
    except (ValueError, IndexError):
        return _MODE_UNKNOWN


def _read_file(root: Path, rel: str) -> str | None | _Unreadable:
    """File text; None when absent; _UNREADABLE when not safely diffable."""
    path = root / rel
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_FILE_BYTES:
            return _UNREADABLE
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        # Permission / IO failure is not absence — a later successful read
        # must not be reported as a fresh "create".
        return _UNREADABLE
    if b"\0" in data[:_BINARY_SNIFF_BYTES]:
        return _UNREADABLE
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return _UNREADABLE


_MODE_UNKNOWN = object()


def _read_regular_mode(root: Path, rel: str) -> int | None | object:
    try:
        info = (root / rel).lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return _MODE_UNKNOWN
    if not stat.S_ISREG(info.st_mode):
        return _MODE_UNKNOWN
    return stat.S_IMODE(info.st_mode)


def _normalize_relative_path(path: str) -> str:
    return path.replace("\\", "/") if os.name == "nt" else path


def _line_start_for(op: str, unified: str) -> int | None:
    if op == "create":
        return 1
    if op == "delete":
        return None
    match = _HUNK_HEADER_RE.search(unified)
    if match is None:
        return None
    return max(1, int(match.group(1)))
