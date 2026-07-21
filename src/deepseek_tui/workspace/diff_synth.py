"""Synthesize unified diffs from before/after text for file mutations."""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiffStats:
    additions: int
    deletions: int


def count_diff_stats(unified_diff: str) -> DiffStats:
    additions = 0
    deletions = 0
    for line in unified_diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return DiffStats(additions=additions, deletions=deletions)


def synthesize_unified_diff(
    path: str,
    old_text: str,
    new_text: str,
    *,
    op: str | None = None,
) -> tuple[str, DiffStats, str]:
    """Return ``(unified_diff, stats, resolved_op)``.

    ``op`` is inferred when omitted: create / update / delete.
    """
    rel = path.replace("\\", "/").lstrip("./")
    if op is None:
        if old_text == "" and new_text == "":
            op = "create"
        elif old_text == "" and new_text != "":
            op = "create"
        elif new_text == "" and old_text != "":
            op = "delete"
        else:
            op = "update"

    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    from_file = "/dev/null" if op == "create" else f"a/{rel}"
    to_file = "/dev/null" if op == "delete" else f"b/{rel}"

    body = "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_file,
            tofile=to_file,
        )
    )
    if not body.strip():
        unified = f"diff --git a/{rel} b/{rel}\n--- {from_file}\n+++ {to_file}\n"
    else:
        unified = f"diff --git a/{rel} b/{rel}\n{body}"
        if not unified.endswith("\n"):
            unified += "\n"

    stats = count_diff_stats(unified)
    return unified, stats, op


def truncate_unified_diff(unified_diff: str, max_chars: int) -> tuple[str, bool]:
    """Return truncated diff and whether truncation occurred."""
    if max_chars <= 0 or len(unified_diff) <= max_chars:
        return unified_diff, False
    return unified_diff[:max_chars].rstrip() + "\n…\n", True
