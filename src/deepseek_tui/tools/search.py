

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path

from deepseek_tui.tools.validation import require_string as _require_string
from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext

logger = logging.getLogger(__name__)

# Directories that are virtually never the search target but can hold
# gigabytes of vendored/generated content (a single `grep packages/workbench`
# walked a 1 GB node_modules and returned 2128 minified-JS matches, blowing the
# turn context past 5M tokens). Pruned during traversal so we never descend.
_IGNORED_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".egg-info",
    }
)

# Hard caps on grep output so one call can never dominate the context window.
_MAX_MATCHES = 200
_MAX_LINE_LEN = 300


class GrepFilesTool(ToolSpec):
    def name(self) -> str:
        return "grep_files"

    def description(self) -> str:
        return (
            "Search files for a regular expression. ``pattern`` is a Python "
            "regex (use ``\\\\b`` for word boundaries, ``(?i)`` for case-insensitive). "
            "``ignore_case`` toggles case insensitivity without inline flags. "
            "``output_mode`` selects the result shape: 'files_with_matches' "
            "(default first pass — just the paths that match, cheap), "
            "'content' (matching lines as path:line_number:line, with "
            "optional -A/-B/-C context lines), or 'count_matches' "
            "(path:match_count plus a total). Locate with "
            "files_with_matches, then drill in with content. ``head_limit`` "
            "caps the returned entries (default 200)."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression to match against each line.",
                },
                "path": {"type": "string"},
                "ignore_case": {"type": "boolean", "default": False},
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count_matches"],
                    "default": "content",
                    "description": (
                        "content: matching lines with line numbers; "
                        "files_with_matches: only paths with at least one match; "
                        "count_matches: per-file match counts plus a total."
                    ),
                },
                "head_limit": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Maximum entries to return (matching lines in content "
                        "mode, files otherwise). Default 200."
                    ),
                },
                "-C": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Context lines before and after each match (content mode only).",
                },
                "-A": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Context lines after each match (content mode only).",
                },
                "-B": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Context lines before each match (content mode only).",
                },
            },
            "required": ["pattern", "path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        pattern = _require_string(input_data, "pattern")
        root = context.resolve_path(_require_string(input_data, "path"), allow_read_roots=True)
        ignore_case = bool(input_data.get("ignore_case", False))
        output_mode = input_data.get("output_mode", "content")
        if output_mode not in ("content", "files_with_matches", "count_matches"):
            raise ToolError(
                "output_mode must be one of: content, files_with_matches, count_matches"
            )
        head_limit = _optional_non_negative_int(input_data, "head_limit")
        if head_limit is None:
            head_limit = _MAX_MATCHES
        context_before = _optional_non_negative_int(input_data, "-B") or 0
        context_after = _optional_non_negative_int(input_data, "-A") or 0
        context_both = _optional_non_negative_int(input_data, "-C")
        if context_both is not None:
            # -A / -B win over -C on their respective side (grep semantics).
            if "-B" not in input_data:
                context_before = context_both
            if "-A" not in input_data:
                context_after = context_both
        try:
            flags = re.IGNORECASE if ignore_case else 0
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            logger.warning("grep_files_invalid_regex pattern=%r error=%s", pattern, exc)
            raise ToolError(f"invalid regex pattern: {exc}") from exc
        rows, file_counts, total = await asyncio.to_thread(
            _grep_files,
            root,
            compiled,
            before=context_before if output_mode == "content" else 0,
            after=context_after if output_mode == "content" else 0,
            head_limit=head_limit,
        )
        logger.info(
            "grep_files pattern=%r root=%s ignore_case=%s mode=%s match_count=%d",
            pattern,
            root,
            ignore_case,
            output_mode,
            total,
        )
        if output_mode == "files_with_matches":
            paths = list(file_counts)
            shown = paths[:head_limit]
            content_lines = [str(p) for p in shown]
            if len(paths) > len(shown):
                content_lines.append(
                    f"… (showing {len(shown)} of {len(paths)} files; "
                    "refine the pattern or narrow the path)"
                )
            truncated = len(paths) > len(shown)
            shown_count: int = len(shown)
        elif output_mode == "count_matches":
            items = list(file_counts.items())
            shown_items = items[:head_limit]
            content_lines = [f"{p}:{n}" for p, n in shown_items]
            if len(items) > len(shown_items):
                content_lines.append(
                    f"… (showing {len(shown_items)} of {len(items)} files)"
                )
            content_lines.append(f"total: {total}")
            truncated = len(items) > len(shown_items)
            shown_count = len(shown_items)
        else:
            content_lines = [
                f"{p}:{n}:{line}" if not is_context else f"{p}-{n}-{line}"
                for p, n, line, is_context in rows
            ]
            shown_matches = sum(1 for r in rows if not r[3])
            if total > shown_matches:
                content_lines.append(
                    f"… (showing {shown_matches} of {total} matches; "
                    "refine the pattern or narrow the path)"
                )
            truncated = total > shown_matches
            shown_count = shown_matches
        return ToolResult(
            success=True,
            content="\n".join(content_lines),
            metadata={
                "path": str(root),
                "output_mode": output_mode,
                "count": total,
                "shown": shown_count,
                "truncated": truncated,
            },
        )


class FileSearchTool(ToolSpec):
    def name(self) -> str:
        return "file_search"

    def description(self) -> str:
        return "Find files by name pattern under a directory."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["pattern", "path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        pattern = _require_string(input_data, "pattern")
        root = context.resolve_path(_require_string(input_data, "path"), allow_read_roots=True)
        matches = await asyncio.to_thread(_file_search, root, pattern)
        logger.info(
            "file_search pattern=%r root=%s match_count=%d",
            pattern,
            root,
            len(matches),
        )
        return ToolResult(
            success=True,
            content="\n".join(matches),
            metadata={"path": str(root), "count": len(matches)},
        )




def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in place so os.walk never descends
        # into them (sorted for deterministic output order).
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def _grep_files(
    root: Path,
    pattern: re.Pattern[str],
    *,
    before: int = 0,
    after: int = 0,
    head_limit: int = _MAX_MATCHES,
) -> tuple[list[tuple[Path, int, str, bool]], dict[Path, int], int]:
    """Return ``(rows, file_counts, total_matches)``.

    ``rows`` are ``(path, line_number, line, is_context)`` tuples in output
    order; matching rows are capped at ``head_limit`` (context rows ride
    along for free). ``file_counts`` maps every file with at least one
    match to its true match count, so files/count modes can report the
    full picture even when content rows are capped.
    """
    rows: list[tuple[Path, int, str, bool]] = []
    file_counts: dict[Path, int] = {}
    total = 0
    shown_matches = 0
    for path in _iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lines = text.splitlines()
        match_idx = [i for i, line in enumerate(lines) if pattern.search(line)]
        if not match_idx:
            continue
        file_counts[path] = len(match_idx)
        total += len(match_idx)
        match_lines = set(match_idx)  # 0-based; a real match never renders as context
        last_emitted = 0  # 1-based line no. dedup for overlapping context
        for i in match_idx:
            if shown_matches >= head_limit:
                break
            shown_matches += 1
            lo = max(0, i - before)
            hi = min(len(lines) - 1, i + after)
            for j in range(lo, hi + 1):
                line_no = j + 1
                if line_no <= last_emitted:
                    continue
                last_emitted = line_no
                line = lines[j]
                if len(line) > _MAX_LINE_LEN:
                    line = line[:_MAX_LINE_LEN] + "… (line truncated)"
                rows.append((path, line_no, line, j not in match_lines))
    return rows, file_counts, total


def _optional_non_negative_int(
    input_data: dict[str, object], key: str
) -> int | None:
    if key not in input_data:
        return None
    value = input_data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{key} must be a non-negative integer")
    if value < 0:
        raise ToolError(f"{key} must be a non-negative integer")
    return value


def _file_search(root: Path, pattern: str) -> list[str]:
    return [str(path) for path in _iter_files(root) if pattern in path.name]
