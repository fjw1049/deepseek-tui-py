"""Path-not-found enrichment for file tools.

Suggests corrected / similar paths without auto-retrying the tool call.
Fail-open: any probe failure returns the bare error only.
"""

from __future__ import annotations

import time
from pathlib import Path

_HINT_BUDGET_S = 0.1
_MAX_SIMILAR = 3
_MIN_LEAF_LEN = 2


def format_not_found_error(
    *,
    display_path: str,
    resolved_path: Path,
    cwd: Path,
) -> str:
    """Build ``Error: … does not exist.`` plus optional suggestions."""
    base = f"Error: {display_path} does not exist."
    try:
        suggestion, similar = _collect_hints(resolved_path, cwd)
    except OSError:
        suggestion, similar = None, []

    parts = [base]
    if suggestion is not None:
        parts.append(f" Did you mean {suggestion}?")
    elif similar:
        names = ", ".join(similar)
        parts.append(f"\nSimilar entries in parent directory: {names}")
    parts.append(f"\nNote: your workspace working directory is {cwd}")
    return "".join(parts)


def _collect_hints(path: Path, cwd: Path) -> tuple[str | None, list[str]]:
    deadline = time.monotonic() + _HINT_BUDGET_S
    corrected = _suggest_under_cwd(path, cwd)
    if corrected is not None:
        return corrected, []
    if time.monotonic() > deadline:
        return None, []
    return None, _find_similar(path, deadline)


def _suggest_under_cwd(path: Path, cwd: Path) -> str | None:
    """Detect dropped-repo-folder: asked for ``parent/foo`` while cwd is ``parent/repo``."""
    try:
        path = path if path.is_absolute() else (cwd / path)
        path = path.resolve()
        cwd = cwd.resolve()
    except OSError:
        return None
    if path == cwd or _is_relative_to(path, cwd):
        return None
    parent = cwd.parent
    try:
        rel = path.relative_to(parent)
    except ValueError:
        return None
    candidate = cwd / rel
    try:
        if candidate.exists():
            try:
                return str(candidate.relative_to(cwd)).replace("\\", "/")
            except ValueError:
                return str(candidate)
    except OSError:
        return None
    return None


def _find_similar(path: Path, deadline: float) -> list[str]:
    leaf = path.name
    if len(leaf) < _MIN_LEAF_LEN:
        return []
    parent = path.parent
    try:
        if not parent.is_dir():
            return []
        entries = list(parent.iterdir())
    except OSError:
        return []

    leaf_l = leaf.lower()
    stem_l = path.stem.lower()
    scored: list[tuple[int, str]] = []
    for entry in entries:
        if time.monotonic() > deadline:
            break
        name = entry.name
        name_l = name.lower()
        stem_entry = entry.stem.lower()
        if name_l == leaf_l:
            scored.append((0, name))
        elif leaf_l in name_l or name_l in leaf_l:
            scored.append((1, name))
        elif (
            len(stem_l) >= _MIN_LEAF_LEN
            and (stem_l in stem_entry or stem_entry in stem_l)
        ):
            scored.append((2, name))
    scored.sort()
    out: list[str] = []
    seen: set[str] = set()
    for _, name in scored:
        if name not in seen:
            seen.add(name)
            out.append(name)
            if len(out) >= _MAX_SIMILAR:
                break
    return out


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
