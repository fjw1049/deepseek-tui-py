

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path

from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.utils.gitignore import GitIgnoreMatcher, matches_path_glob
from deepseek_tui.tools.utils.sensitive import is_sensitive_path
from deepseek_tui.tools.utils.validation import require_string as _require_string

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
# Same rationale for file_search: a bare pattern='' at the workspace root
# can match thousands of paths (observed: 7 714 ≈ 320k tokens), which blew
# up sub-agent contexts that receive tool output uncompacted.
_MAX_FILE_RESULTS = 500
_MAX_SEARCH_FILE_BYTES = 1024 * 1024
_GLOB_CHARS = frozenset("*?[")


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
            "files_with_matches, then drill in with content. ``glob`` "
            "filters by filename (``*.py`` matches any Python file). "
            "``head_limit`` caps the returned entries (default 200). "
            "Respects .gitignore (and says how many paths it hid) and "
            "skips files over 1 MiB. "
            "Prefer this over grep/rg via exec_shell — this tool caps "
            "output and skips sensitive files (.env, private keys)."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression to match against each line.",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "File or directory to search, workspace-relative. "
                        "Use '.' for the whole workspace; narrower paths "
                        "are faster and less noisy."
                    ),
                },
                "ignore_case": {
                    "type": "boolean",
                    "default": False,
                    "description": "Case-insensitive matching.",
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count_matches"],
                    "default": "files_with_matches",
                    "description": (
                        "files_with_matches: only paths with at least one match "
                        "(default); content: matching lines with line numbers; "
                        "count_matches: per-file match counts plus a total. "
                        "Passing -A/-B/-C without a mode selects content."
                    ),
                },
                "glob": {
                    "type": "string",
                    "description": (
                        "Filename filter (glob). '*.py' matches any Python "
                        "file by name; 'src/*.ts' matches TypeScript files "
                        "directly under src/ (relative to the search root)."
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
        output_mode = _resolve_output_mode(input_data)
        glob = input_data.get("glob")
        if glob is None:
            glob_pattern = None
        elif not isinstance(glob, str):
            raise ToolError("glob must be a string")
        else:
            glob_pattern = glob or None
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
        rows, file_counts, total, skipped_large, skipped_ignored = await asyncio.to_thread(
            _grep_files,
            root,
            compiled,
            before=context_before if output_mode == "content" else 0,
            after=context_after if output_mode == "content" else 0,
            head_limit=head_limit,
            glob=glob_pattern,
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
            paths = [_display_rel(p, root) for p in file_counts]
            shown = paths[:head_limit]
            content_lines = list(shown)
            if len(paths) > len(shown):
                content_lines.append(
                    f"… (showing {len(shown)} of {len(paths)} files; "
                    "refine the pattern or narrow the path)"
                )
            truncated = len(paths) > len(shown)
            shown_count: int = len(shown)
        elif output_mode == "count_matches":
            items = [(_display_rel(p, root), n) for p, n in file_counts.items()]
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
                (
                    f"{_display_rel(p, root)}:{n}:{line}"
                    if not is_context
                    else f"{_display_rel(p, root)}-{n}-{line}"
                )
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
        if skipped_large:
            content_lines.append(
                f"… (skipped {skipped_large} file(s) over {_MAX_SEARCH_FILE_BYTES} bytes)"
            )
        note = _gitignore_skip_note(skipped_ignored)
        if note is not None:
            content_lines.append(note)
        return ToolResult(
            success=True,
            content="\n".join(content_lines),
            metadata={
                "path": str(root),
                "output_mode": output_mode,
                "count": total,
                "shown": shown_count,
                "truncated": truncated,
                "skipped_large": skipped_large,
                "skipped_ignored": skipped_ignored,
            },
        )


class FileSearchTool(ToolSpec):
    def name(self) -> str:
        return "file_search"

    def description(self) -> str:
        return (
            "Find files under a directory (recursive; skips .git, "
            "node_modules, virtualenvs, build output, credential files, and "
            ".gitignore matches). A pattern without glob characters "
            "(* ? [) is a file-name substring: 'config' matches config.py. "
            "A pattern with glob characters matches the relative path: "
            "'*.ts' or 'src/**/*.py'. Use '' to list files. max_depth=1 "
            "lists only the given directory (shallow ls). Prefer this over "
            "find/ls -R via exec_shell. Not for file CONTENTS — use "
            "grep_files."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "File-name substring, or a glob if it contains "
                        "* ? or [. 'config' matches config.py; '*.ts' "
                        "matches any TypeScript file. Use '' to list files."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Directory to search, workspace-relative; '.' for "
                        "the whole workspace."
                    ),
                },
                "max_depth": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Maximum directory depth. 1 lists only this "
                        "directory (no recursion). Omit for unlimited."
                    ),
                },
            },
            "required": ["pattern", "path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        pattern = _require_string(input_data, "pattern")
        root = context.resolve_path(_require_string(input_data, "path"), allow_read_roots=True)
        max_depth = _optional_non_negative_int(input_data, "max_depth")
        if max_depth == 0:
            raise ToolError("max_depth must be >= 1")
        matches, skipped_ignored = await asyncio.to_thread(
            _file_search, root, pattern, max_depth
        )
        logger.info(
            "file_search pattern=%r root=%s match_count=%d",
            pattern,
            root,
            len(matches),
        )
        shown = matches[:_MAX_FILE_RESULTS]
        lines = list(shown)
        if len(matches) > len(shown):
            lines.append(
                f"… (showing {len(shown)} of {len(matches)} files; "
                "narrow the path or use a more specific pattern)"
            )
        note = _gitignore_skip_note(skipped_ignored)
        if note is not None:
            lines.append(note)
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "path": str(root),
                "count": len(matches),
                "skipped_ignored": skipped_ignored,
            },
        )




def _resolve_output_mode(input_data: dict[str, object]) -> str:
    output_mode = input_data.get("output_mode")
    if output_mode is None:
        # Context flags only make sense on matching lines.
        if any(key in input_data for key in ("-A", "-B", "-C")):
            return "content"
        return "files_with_matches"
    if output_mode not in ("content", "files_with_matches", "count_matches"):
        raise ToolError(
            "output_mode must be one of: content, files_with_matches, count_matches"
        )
    return output_mode


def _path_matches_glob(path: Path, root: Path, pattern: str) -> bool:
    """Match ``*.py`` against the basename, ``src/*.ts`` against the relpath.

    ``*`` stays inside one path component (same rule as gitignore). A
    basename-only pattern like ``*.py`` still matches at any depth because
    it is tested against ``path.name``.
    """
    if "/" not in pattern:
        return matches_path_glob(path.name, pattern)
    base = root if root.is_dir() else root.parent
    try:
        rel = path.relative_to(base)
    except ValueError:
        return False
    return matches_path_glob(rel.as_posix(), pattern)


def _gitignore_skip_note(count: int) -> str | None:
    if count <= 0:
        return None
    return f"… (skipped {count} path(s) matching .gitignore)"


def _is_glob_pattern(pattern: str) -> bool:
    return any(ch in pattern for ch in _GLOB_CHARS)


def _walk_depth(dirpath: str, root: Path) -> int:
    try:
        return len(Path(dirpath).relative_to(root).parts)
    except ValueError:
        return 0


def _iter_files(
    root: Path,
    glob: str | None = None,
    *,
    max_depth: int | None = None,
    skip_over_bytes: int | None = None,
    skipped_large: list[int] | None = None,
    skipped_ignored: list[int] | None = None,
) -> Iterable[Path]:
    ignore = GitIgnoreMatcher(root if root.is_dir() else root.parent)
    if root.is_file():
        if ignore.ignored(root, is_dir=False):
            if skipped_ignored is not None:
                skipped_ignored[0] += 1
            return
        if not is_sensitive_path(root) and (
            glob is None or _path_matches_glob(root, root, glob)
        ):
            if skip_over_bytes is not None:
                try:
                    if root.stat().st_size > skip_over_bytes:
                        if skipped_large is not None:
                            skipped_large[0] += 1
                        return
                except OSError:
                    return
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        ignore.add_dir(current)
        depth = _walk_depth(dirpath, root)
        kept_dirs: list[str] = []
        ignored_dirs = 0
        for name in dirnames:
            if name in _IGNORED_DIRS:
                continue
            if ignore.ignored(current / name, is_dir=True):
                ignored_dirs += 1
                continue
            kept_dirs.append(name)
        if skipped_ignored is not None:
            skipped_ignored[0] += ignored_dirs
        if max_depth is not None and depth + 1 >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(kept_dirs)
        for name in sorted(filenames):
            path = current / name
            if is_sensitive_path(path):
                continue
            if ignore.ignored(path, is_dir=False):
                if skipped_ignored is not None:
                    skipped_ignored[0] += 1
                continue
            if glob is not None and not _path_matches_glob(path, root, glob):
                continue
            if skip_over_bytes is not None:
                try:
                    if path.stat().st_size > skip_over_bytes:
                        if skipped_large is not None:
                            skipped_large[0] += 1
                        continue
                except OSError:
                    continue
            yield path


def _grep_files(
    root: Path,
    pattern: re.Pattern[str],
    *,
    before: int = 0,
    after: int = 0,
    head_limit: int = _MAX_MATCHES,
    glob: str | None = None,
) -> tuple[list[tuple[Path, int, str, bool]], dict[Path, int], int, int, int]:
    """Return ``(rows, file_counts, total_matches, skipped_large, skipped_ignored)``.

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
    skipped = [0]
    ignored = [0]
    for path in _iter_files(
        root,
        glob,
        skip_over_bytes=_MAX_SEARCH_FILE_BYTES,
        skipped_large=skipped,
        skipped_ignored=ignored,
    ):
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
    return rows, file_counts, total, skipped[0], ignored[0]


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


def _display_rel(path: Path, root: Path) -> str:
    base = root if root.is_dir() else root.parent
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def _file_matches_pattern(path: Path, root: Path, pattern: str) -> bool:
    if not pattern:
        return True
    if _is_glob_pattern(pattern):
        return _path_matches_glob(path, root, pattern)
    return pattern in path.name


def _file_search(
    root: Path, pattern: str, max_depth: int | None
) -> tuple[list[str], int]:
    ignored = [0]
    matches = [
        _display_rel(path, root)
        for path in _iter_files(root, max_depth=max_depth, skipped_ignored=ignored)
        if _file_matches_pattern(path, root, pattern)
    ]
    return matches, ignored[0]
