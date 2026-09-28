"""Synthesize unified diffs from before/after text for file mutations."""

from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiffStats:
    additions: int
    deletions: int


def count_diff_stats(unified_diff: str) -> DiffStats:
    additions = 0
    deletions = 0
    in_hunk = False
    for line in unified_diff.split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
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
    rel = path.replace("\\", "/") if os.name == "nt" else path
    while rel.startswith("./"):
        rel = rel[2:]
    if op is None:
        if old_text == "" and new_text == "":
            op = "create"
        elif old_text == "" and new_text != "":
            op = "create"
        elif new_text == "" and old_text != "":
            op = "delete"
        else:
            op = "update"

    def lines(text: str) -> list[str]:
        parts = text.split("\n")
        return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])

    def quoted(name: str) -> str:
        if any(c in name for c in '\\"\t\n\r'):
            return json.dumps(name, ensure_ascii=False)
        return name

    old_lines = lines(old_text)
    new_lines = lines(new_text)

    from_file = "/dev/null" if op == "create" else quoted(f"a/{rel}")
    to_file = "/dev/null" if op == "delete" else quoted(f"b/{rel}")
    records = difflib.unified_diff(
        old_lines, new_lines, fromfile=from_file, tofile=to_file
    )
    body = "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        for line in records
    )
    unified = f"diff --git {quoted(f'a/{rel}')} {quoted(f'b/{rel}')}\n"
    if op == "create":
        unified += "new file mode 100644\n"
    elif op == "delete":
        unified += "deleted file mode 100644\n"
    unified += body or f"--- {from_file}\n+++ {to_file}\n"

    stats = count_diff_stats(unified)
    return unified, stats, op


def truncate_unified_diff(unified_diff: str, max_chars: int) -> tuple[str, bool]:
    """Return truncated diff and whether truncation occurred."""
    if max_chars <= 0 or len(unified_diff) <= max_chars:
        return unified_diff, False
    return unified_diff[:max_chars].rstrip() + "\n…\n", True
