"""Unified-diff patcher with fuzzy matching.

Mirrors ``crates/tui/src/tools/apply_patch.rs`` (1,469 lines). Provides
pure-Python equivalents for:

- :func:`parse_unified_diff` / :func:`parse_unified_diff_files`
- :func:`apply_hunks_to_lines` / :func:`apply_hunk` (with cumulative
  offset across hunks)
- :func:`matches_at_position` (whitespace-normalized by ``rstrip``)
- :class:`Hunk` / :class:`HunkLine` / :class:`PatchResult` /
  :class:`FileSummary`

``MAX_FUZZ = 50`` follows Rust (apply_patch.rs:21). Fuzz search starts
at the adjusted line (cumulative offset applied) and widens symmetrically
up to ``max_fuzz`` lines on either side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Constants — mirror Rust
MAX_FUZZ = 50
HUNK_PREVIEW_LINES = 4
SNIPPET_RADIUS = 2
FILE_LIST_LIMIT = 6


class HunkLineKind(str, Enum):
    CONTEXT = "context"
    ADD = "add"
    REMOVE = "remove"


@dataclass(slots=True, frozen=True)
class HunkLine:
    kind: HunkLineKind
    content: str


@dataclass(slots=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[HunkLine]


@dataclass(slots=True)
class FilePatch:
    path: str
    hunks: list[Hunk] = field(default_factory=list)
    delete_after: bool = False
    create_if_missing: bool = False


@dataclass(slots=True)
class FileSummary:
    path: str
    hunks: int
    hunks_applied: int
    fuzz_used: int
    hunks_with_fuzz: int
    created: bool
    deleted: bool


@dataclass(slots=True)
class PatchResult:
    success: bool
    files_applied: int
    files_total: int
    hunks_applied: int
    hunks_total: int
    fuzz_used: int
    hunks_with_fuzz: int
    touched_files: list[str] = field(default_factory=list)
    file_summaries: list[FileSummary] = field(default_factory=list)
    message: str = ""


class ApplyPatchError(Exception):
    """Raised when a patch cannot be parsed or applied."""


@dataclass(slots=True)
class HunkApplyStats:
    hunks_applied: int = 0
    fuzz_used: int = 0
    hunks_with_fuzz: int = 0


# --- parsing ---------------------------------------------------------------


def parse_unified_diff(patch: str) -> list[Hunk]:
    """Parse a single-file unified diff, returning its hunks.

    Header lines (``---``/``+++``) are skipped; the caller is expected to
    supply ``path`` externally. Mirrors Rust ``parse_unified_diff``.
    """
    lines = patch.splitlines()
    idx = 0
    # Skip non-@@ preamble.
    while idx < len(lines) and not lines[idx].startswith("@@"):
        idx += 1

    hunks: list[Hunk] = []
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("@@"):
            hunk, idx = _parse_hunk(lines, idx)
            hunks.append(hunk)
        else:
            idx += 1
    return hunks


def parse_unified_diff_files(
    patch: str, create_if_missing: bool = False
) -> list[FilePatch]:
    """Parse a multi-file unified diff (with ``---``/``+++`` headers).

    Mirrors Rust ``parse_unified_diff_files``. Recognizes ``/dev/null`` and
    strips ``a/``/``b/`` prefixes.
    """
    lines = patch.splitlines()
    files: list[FilePatch] = []
    current: FilePatch | None = None
    old_path: str | None = None

    idx = 0
    while idx < len(lines):
        line = lines[idx]

        if line.startswith("diff --git "):
            if current is not None:
                files.append(current)
                current = None
            old_path = None
            idx += 1
            continue

        if line.startswith("--- "):
            old_path = line[4:].strip()
            idx += 1
            continue

        if line.startswith("+++ "):
            new_path = line[4:].strip()
            path, delete_after, create_flag = _resolve_diff_paths(
                old_path, new_path, create_if_missing
            )
            if current is not None:
                files.append(current)
            current = FilePatch(
                path=path,
                hunks=[],
                delete_after=delete_after,
                create_if_missing=create_flag,
            )
            old_path = None
            idx += 1
            continue

        if line.startswith("@@"):
            if current is None:
                if old_path is not None:
                    raise ApplyPatchError(
                        f"Patch hunk encountered after `--- {old_path}` but before a"
                        " matching `+++` header."
                    )
                raise ApplyPatchError(
                    "Patch hunk encountered before any file header."
                )
            hunk, idx = _parse_hunk(lines, idx)
            current.hunks.append(hunk)
            continue

        idx += 1

    if current is not None:
        files.append(current)
    return files


def _parse_hunk(lines: list[str], start_idx: int) -> tuple[Hunk, int]:
    header = lines[start_idx]
    parts = header.split()
    if len(parts) < 3:
        raise ApplyPatchError(
            f"Invalid hunk header: {header}. Expected `@@ -start,count +start,count @@`."
        )
    old_range = parts[1].lstrip("-")
    new_range = parts[2].lstrip("+")
    old_start, old_count = _parse_range(old_range)
    new_start, new_count = _parse_range(new_range)

    hunk_lines: list[HunkLine] = []
    expected = max(old_count, new_count) + min(old_count, new_count)
    # Rust loops up to expected*2 to forgive mis-sized hunks.
    budget = max(1, expected * 2)
    idx = start_idx + 1
    while idx < len(lines) and budget > 0:
        line = lines[idx]
        if line.startswith("@@"):
            break
        if line.startswith("diff ") or line.startswith("--- ") or line.startswith("+++ "):
            # Next file section — let the outer loop see it.
            break
        if line.startswith("-"):
            hunk_lines.append(HunkLine(HunkLineKind.REMOVE, line[1:]))
            idx += 1
            budget -= 1
            continue
        if line.startswith("+"):
            hunk_lines.append(HunkLine(HunkLineKind.ADD, line[1:]))
            idx += 1
            budget -= 1
            continue
        if line.startswith(" ") or line == "":
            content = line[1:] if line else ""
            hunk_lines.append(HunkLine(HunkLineKind.CONTEXT, content))
            idx += 1
            budget -= 1
            continue
        if line.startswith("\\"):
            # "\ No newline at end of file" etc.
            idx += 1
            budget -= 1
            continue
        # Fallback: unprefixed text treated as context (Rust does the same).
        hunk_lines.append(HunkLine(HunkLineKind.CONTEXT, line))
        idx += 1
        budget -= 1

    return (
        Hunk(
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            lines=hunk_lines,
        ),
        idx,
    )


def _parse_range(raw: str) -> tuple[int, int]:
    parts = raw.split(",")
    try:
        start = int(parts[0])
    except ValueError as exc:
        raise ApplyPatchError(
            f"Invalid line number `{parts[0]}` in hunk header."
        ) from exc
    if len(parts) > 1:
        try:
            count = int(parts[1])
        except ValueError as exc:
            raise ApplyPatchError(
                f"Invalid line count `{parts[1]}` in hunk header."
            ) from exc
    else:
        count = 1
    return start, count


def _resolve_diff_paths(
    old_path: str | None, new_path: str | None, create_if_missing: bool
) -> tuple[str, bool, bool]:
    old_norm = _normalize_diff_path(old_path) if old_path is not None else None
    new_norm = _normalize_diff_path(new_path) if new_path is not None else None
    delete_after = new_norm is None
    create_flag = create_if_missing or old_norm is None
    path = new_norm or old_norm
    if path is None:
        raise ApplyPatchError("Patch is missing both old and new file paths")
    return path, delete_after, create_flag


def _normalize_diff_path(raw: str) -> str | None:
    s = raw.strip()
    if not s:
        return None
    if s in ("/dev/null", "dev/null"):
        return None
    for prefix in ("a/", "b/"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s


# --- applying --------------------------------------------------------------


def apply_hunks_to_lines(
    lines: list[str], hunks: list[Hunk], fuzz: int = MAX_FUZZ
) -> HunkApplyStats:
    """Apply all hunks in order, with cumulative offset tracking.

    Mutates ``lines`` in place. Returns per-file stats. Raises
    :class:`ApplyPatchError` when a hunk cannot find a match.
    """
    stats = HunkApplyStats()
    cumulative_offset = 0
    for idx, hunk in enumerate(hunks):
        try:
            fuzz_used, cumulative_offset = _apply_hunk(
                lines, hunk, fuzz, cumulative_offset
            )
        except _NoMatch as exc:
            raise ApplyPatchError(
                f"Failed to apply hunk {idx + 1}/{len(hunks)}: "
                f"expected at line {exc.expected_line}, adjusted to "
                f"{exc.adjusted_line} (offset {exc.offset:+d})"
            ) from exc
        stats.fuzz_used += fuzz_used
        stats.hunks_applied += 1
        if fuzz_used > 0:
            stats.hunks_with_fuzz += 1
    return stats


class _NoMatch(Exception):
    def __init__(self, expected_line: int, adjusted_line: int, offset: int) -> None:
        super().__init__(
            f"no match at line {expected_line} (adjusted {adjusted_line})"
        )
        self.expected_line = expected_line
        self.adjusted_line = adjusted_line
        self.offset = offset


def _apply_hunk(
    lines: list[str], hunk: Hunk, max_fuzz: int, cumulative_offset: int
) -> tuple[int, int]:
    old_lines = [
        line.content
        for line in hunk.lines
        if line.kind in (HunkLineKind.CONTEXT, HunkLineKind.REMOVE)
    ]
    new_lines = [
        line.content
        for line in hunk.lines
        if line.kind in (HunkLineKind.CONTEXT, HunkLineKind.ADD)
    ]

    base_idx = hunk.old_start - 1 if hunk.old_start > 0 else 0
    start_idx = max(0, base_idx + cumulative_offset)

    for fuzz in range(max_fuzz + 1):
        if fuzz == 0:
            candidates = [start_idx]
        else:
            lo = max(0, start_idx - fuzz)
            hi = min(len(lines), start_idx + fuzz)
            candidates = list(range(lo, hi + 1))
        for pos in candidates:
            if matches_at_position(lines, old_lines, pos):
                end_pos = pos + len(old_lines)
                lines[pos:end_pos] = new_lines
                delta = len(new_lines) - len(old_lines)
                return fuzz, cumulative_offset + delta

    # Special case: adding to empty file or appending.
    if not old_lines and (not lines or start_idx >= len(lines)):
        lines.extend(new_lines)
        return 0, cumulative_offset + len(new_lines)

    raise _NoMatch(
        expected_line=hunk.old_start,
        adjusted_line=start_idx + 1,
        offset=cumulative_offset,
    )


def matches_at_position(
    lines: list[str], old_lines: list[str], pos: int
) -> bool:
    """Check whether ``old_lines`` match ``lines`` starting at ``pos``.

    Uses ``rstrip()`` on both sides to normalize trailing whitespace
    (matches Rust's ``trim_end`` comparison).
    """
    if pos + len(old_lines) > len(lines):
        return False
    for i, expected in enumerate(old_lines):
        if lines[pos + i].rstrip() != expected.rstrip():
            return False
    return True


# --- helpers for file I/O --------------------------------------------------


def apply_patch_to_file(
    path: Path, hunks: list[Hunk], fuzz: int = MAX_FUZZ
) -> HunkApplyStats:
    """Read ``path``, apply ``hunks``, write back in place."""
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    newline_trailing = original.endswith("\n")
    lines = original.splitlines()
    stats = apply_hunks_to_lines(lines, hunks, fuzz=fuzz)
    out = "\n".join(lines)
    if newline_trailing or (out and not out.endswith("\n")):
        out += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out, encoding="utf-8")
    return stats
