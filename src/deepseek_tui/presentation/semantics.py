"""Pure presentation semantics for tool batches and progress narration."""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import Enum
from typing import Literal

from deepseek_tui.protocol.responses import ToolCall

NarrationLocale = Literal["zh", "en"]

_TOOL_NAME_RE = re.compile(
    r"\b(read_file|list_dir|grep_files?|search_files?|write_file|apply_patch|"
    r"exec_shell|run_terminal|glob_file_search|codebase_search)\b",
    re.I,
)
_MUTATE_TOOLS = frozenset(
    {
        "write_file",
        "apply_patch",
        "edit_file",
        "search_replace",
        "exec_shell",
        "exec_shell_wait",
        "exec_shell_interact",
        "run_terminal_cmd",
    }
)
_SEARCH_TOOLS = frozenset(
    {"grep_files", "grep", "search_files", "glob_file_search", "codebase_search"}
)
_READ_TOOLS = frozenset({"read_file", "read"})
_DIR_TOOLS = frozenset({"list_dir", "list_directory"})
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


class BatchKind(str, Enum):
    EXPLORE_DIR = "explore_dir"
    EXPLORE_READ = "explore_read"
    SEARCH = "search"
    INSPECT = "inspect"
    MUTATE = "mutate"
    MIXED = "mixed"


class Phase(str, Enum):
    EXPLORE = "explore"
    LOCATE = "locate"
    CHANGE = "change"
    VERIFY = "verify"
    RECOVER = "recover"


def script_counts(text: str) -> tuple[int, int]:
    return len(_CJK_RE.findall(text)), len(_LATIN_RE.findall(text))


def resolve_narration_locale(
    user_text: str, *, config_locale: str = "auto"
) -> NarrationLocale:
    """Resolve narration language from user input, with config fallback."""
    cleaned = user_text.strip()
    cjk, latin = script_counts(cleaned)
    total = cjk + latin
    if total >= 4:
        if cjk > 0 and cjk / total >= 0.15:
            return "zh"
        if latin > 0:
            return "en"
    if config_locale in {"zh", "en"}:
        return config_locale  # type: ignore[return-value]
    return "zh"


def truncate_text(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def contains_tool_name(text: str) -> bool:
    return bool(_TOOL_NAME_RE.search(text))


def tool_path(arguments: dict[str, object] | None) -> str | None:
    if not arguments:
        return None
    for key in ("path", "file_path", "target_directory", "directory", "dir"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def classify_batch(tool_calls: Sequence[ToolCall]) -> BatchKind:
    if not tool_calls:
        return BatchKind.MIXED
    names = [tc.name.lower() for tc in tool_calls]
    if any(name in _MUTATE_TOOLS for name in names):
        return BatchKind.MUTATE
    read_count = sum(1 for name in names if name in _READ_TOOLS)
    dir_count = sum(1 for name in names if name in _DIR_TOOLS)
    search_count = sum(1 for name in names if name in _SEARCH_TOOLS)
    if read_count >= 2 and read_count == len(tool_calls):
        return BatchKind.EXPLORE_READ
    if dir_count >= 1 and dir_count + read_count == len(tool_calls) and read_count <= 1:
        return BatchKind.EXPLORE_DIR
    if search_count >= 1 and search_count == len(tool_calls):
        return BatchKind.SEARCH
    if len(tool_calls) == 1 and read_count == 1:
        return BatchKind.INSPECT
    return BatchKind.MIXED


def batch_root(tool_calls: Sequence[ToolCall]) -> str | None:
    for tool_call in tool_calls:
        path = tool_path(dict(tool_call.arguments) if tool_call.arguments else None)
        if path:
            parts = path.replace("\\", "/").strip("/").split("/")
            return parts[0] if parts else path
    return None


def infer_next_phase(
    current: Phase,
    batch: BatchKind,
    *,
    has_tool_error: bool,
) -> Phase:
    if has_tool_error:
        return Phase.RECOVER
    if batch == BatchKind.MUTATE:
        return Phase.CHANGE
    if batch in {BatchKind.INSPECT, BatchKind.EXPLORE_READ} and current == Phase.EXPLORE:
        return Phase.LOCATE
    if current == Phase.CHANGE and batch in {BatchKind.SEARCH, BatchKind.INSPECT}:
        return Phase.VERIFY
    return current


def batch_intent_text(
    batch: BatchKind,
    tool_calls: Sequence[ToolCall],
    *,
    locale: str = "zh",
) -> str:
    if locale == "en":
        if batch == BatchKind.EXPLORE_DIR:
            return f"Survey structure under {batch_root(tool_calls) or 'project root'}"
        if batch == BatchKind.EXPLORE_READ:
            paths = [
                path
                for tool_call in tool_calls
                if (
                    path := tool_path(
                        dict(tool_call.arguments) if tool_call.arguments else None
                    )
                )
            ]
            if paths:
                head = ", ".join(truncate_text(path, 40) for path in paths[:2])
                suffix = f" and {len(paths) - 2} more" if len(paths) > 2 else ""
                return f"Read {head}{suffix} in parallel"
            return "Read multiple source files in parallel"
        if batch == BatchKind.SEARCH:
            return "Search the codebase for relevant implementations"
        if batch == BatchKind.INSPECT:
            path = tool_path(
                dict(tool_calls[0].arguments) if tool_calls[0].arguments else None
            )
            return f"Inspect {truncate_text(path or 'a key file', 48)}"
        if batch == BatchKind.MUTATE:
            return "Apply changes and prepare verification"
        if batch == BatchKind.MIXED:
            return f"Used {len(tool_calls)} tools to continue analysis"

    if batch == BatchKind.EXPLORE_DIR:
        return f"浏览 {batch_root(tool_calls) or '项目目录'} 的结构"
    if batch == BatchKind.EXPLORE_READ:
        paths = [
            path
            for tool_call in tool_calls
            if (
                path := tool_path(
                    dict(tool_call.arguments) if tool_call.arguments else None
                )
            )
        ]
        if paths:
            head = ", ".join(truncate_text(path, 40) for path in paths[:2])
            suffix = f" 等 {len(paths)} 个文件" if len(paths) > 2 else ""
            return f"并行查看 {head}{suffix}"
        return "并行阅读多个源文件"
    if batch == BatchKind.SEARCH:
        return "搜索代码以定位相关实现"
    if batch == BatchKind.INSPECT:
        path = tool_path(
            dict(tool_calls[0].arguments) if tool_calls[0].arguments else None
        )
        return f"深入阅读 {truncate_text(path or '关键文件', 48)}"
    if batch == BatchKind.MUTATE:
        return "实施修改并准备验证"
    if batch == BatchKind.MIXED:
        return f"调用 {len(tool_calls)} 个工具继续分析"


def template_narration(
    *,
    locale: str,
    batch: BatchKind,
    tool_calls: Sequence[ToolCall],
) -> str | None:
    """Return a localized deterministic narration line."""
    text = batch_intent_text(batch, tool_calls, locale=locale)
    if contains_tool_name(text):
        return None
    return truncate_text(text, 120)


__all__ = [
    "BatchKind",
    "NarrationLocale",
    "Phase",
    "batch_intent_text",
    "batch_root",
    "classify_batch",
    "contains_tool_name",
    "infer_next_phase",
    "resolve_narration_locale",
    "script_counts",
    "template_narration",
    "tool_path",
    "truncate_text",
]
