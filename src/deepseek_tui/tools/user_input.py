"""User input and tool result retrieval.

Consolidates user_input_tool.py and retrieve_tool_result.py.
"""

from __future__ import annotations



# RequestUserInputTool — pauses execution to ask the user a question.
#
# Mirrors `crates/tui/src/tools/user_input.rs`.
#
# The Engine intercepts this tool name, validates the input, emits a
# UserInputRequiredEvent, and blocks until the TUI resolves the future.
# The ToolSpec itself always raises — it must never be dispatched directly.
#
from typing import Any

from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext
import json
import re
from pathlib import Path

REQUEST_USER_INPUT_NAME = "request_user_input"


class UserInputQuestion:
    """Validated question structure."""

    __slots__ = ("header", "id", "question", "options")

    def __init__(self, header: str, id: str, question: str, options: list[dict[str, str]]) -> None:
        self.header = header
        self.id = id
        self.question = question
        self.options = options


def validate_user_input_request(input_data: dict[str, Any]) -> list[UserInputQuestion]:
    """Validate and parse the request_user_input input.

    Mirrors Rust UserInputRequest::validate().
    Raises ToolError on invalid input.
    """
    tool_uses = input_data.get("questions")
    if not isinstance(tool_uses, list) or not (1 <= len(tool_uses) <= 3):
        raise ToolError("questions must be an array of 1-3 items")

    questions: list[UserInputQuestion] = []
    for item in tool_uses:
        if not isinstance(item, dict):
            raise ToolError("each question must be an object")
        header = item.get("header", "")
        qid = item.get("id", "")
        question_text = item.get("question", "")
        if not header or not qid or not question_text:
            raise ToolError("header, id, and question are required and must be non-empty")

        options = item.get("options")
        if not isinstance(options, list) or not (2 <= len(options) <= 3):
            raise ToolError("each question must have 2-3 options")

        for opt in options:
            if not isinstance(opt, dict):
                raise ToolError("each option must be an object")
            label = opt.get("label", "")
            description = opt.get("description", "")
            if not label or not description:
                raise ToolError("option label and description are required and must be non-empty")

        questions.append(UserInputQuestion(
            header=header,
            id=qid,
            question=question_text,
            options=options,
        ))

    return questions


class RequestUserInputTool(ToolSpec):
    def name(self) -> str:
        return REQUEST_USER_INPUT_NAME

    def description(self) -> str:
        return (
            "Ask the user a multiple-choice question. "
            "Must be handled by the engine — direct execution is an error."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "header": {"type": "string"},
                            "id": {"type": "string"},
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["label", "description"],
                                },
                                "minItems": 2,
                                "maxItems": 3,
                            },
                        },
                        "required": ["header", "id", "question", "options"],
                    },
                    "minItems": 1,
                    "maxItems": 3,
                }
            },
            "required": ["questions"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        raise ToolError("request_user_input must be handled by the engine")


# ``retrieve_tool_result`` — selective retrieval for spilled tool outputs.
#
# Mirrors ``docs/DeepSeek-TUI-main/crates/tui/src/tools/tool_result_retrieval.rs``.
#

from deepseek_tui.tools.validation import require_string as _require_string
from deepseek_tui.tools.runtime import spillover_path, spillover_root

DEFAULT_MAX_BYTES = 8 * 1024
HARD_MAX_BYTES = 128 * 1024
DEFAULT_LINE_COUNT = 40
HARD_LINE_COUNT = 500
DEFAULT_MAX_MATCHES = 20
HARD_MAX_MATCHES = 100
DEFAULT_CONTEXT_LINES = 1
HARD_CONTEXT_LINES = 5


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    else:
        return default
    return max(minimum, min(maximum, parsed))


def resolve_spillover_reference(reference: str) -> Path:
    root = spillover_root()
    if root is None:
        raise ToolError("could not resolve ~/.deepseek/tool_outputs")
    root.mkdir(parents=True, exist_ok=True)
    root_canonical = root.resolve()
    trimmed = reference.strip()
    stripped = trimmed.removeprefix("tool_result:")
    raw = Path(stripped)
    if raw.is_absolute():
        candidate = raw
    elif stripped.endswith(".txt") or "/" in stripped:
        candidate = root / stripped
    else:
        resolved = spillover_path(stripped)
        if resolved is None:
            raise ToolError(f"invalid spilled tool-result ref `{reference}`")
        candidate = resolved
    try:
        canonical = candidate.resolve()
    except OSError as err:
        raise ToolError(
            f"spilled tool result `{reference}` was not found at {candidate}: {err}"
        ) from err
    if not str(canonical).startswith(str(root_canonical)):
        raise ToolError(
            f"ref `{reference}` does not point inside {root_canonical}"
        )
    if not canonical.is_file():
        raise ToolError(f"ref `{reference}` does not point to a spillover file")
    return canonical


def _render_numbered_lines(
    numbered: list[tuple[int, str]], max_bytes: int
) -> str:
    parts: list[str] = []
    used = 0
    for line_no, text in numbered:
        chunk = f"{line_no:6}| {text}\n"
        if used + len(chunk.encode("utf-8")) > max_bytes and parts:
            parts.append("…[truncated]\n")
            break
        parts.append(chunk)
        used += len(chunk.encode("utf-8"))
    return "".join(parts)


def _collect_signal_lines(lines: list[str], max_matches: int) -> list[dict[str, object]]:
    patterns = (
        re.compile(r"error", re.I),
        re.compile(r"failed", re.I),
        re.compile(r"panic", re.I),
        re.compile(r"traceback", re.I),
    )
    hits: list[dict[str, object]] = []
    for idx, line in enumerate(lines, start=1):
        if any(p.search(line) for p in patterns):
            hits.append({"line": idx, "text": line[:200]})
        if len(hits) >= max_matches:
            break
    return hits


def _parse_line_selector(
    input_data: dict[str, object],
    total_lines: int,
) -> tuple[int, int]:
    start_raw = input_data.get("start_line")
    end_raw = input_data.get("end_line")
    if start_raw is not None or end_raw is not None:
        if not isinstance(start_raw, int):
            raise ToolError("start_line is required when end_line is supplied")
        end = end_raw if isinstance(end_raw, int) else start_raw
        start = max(1, start_raw)
        end = max(start, min(end, total_lines or 1))
        return start, end
    spec = input_data.get("lines")
    if isinstance(spec, str) and spec.strip():
        text = spec.strip()
        if "-" in text:
            left, right = text.split("-", 1)
            start = int(left.strip())
            end = int(right.strip())
        else:
            start = end = int(text)
        start = max(1, start)
        end = max(start, min(end, total_lines or 1))
        return start, end
    raise ToolError("lines, start_line/end_line required for mode=lines")


class RetrieveToolResultTool(ToolSpec):
    def name(self) -> str:
        return "retrieve_tool_result"

    def description(self) -> str:
        return (
            "Retrieve a previously spilled large tool result from "
            "~/.deepseek/tool_outputs by tool call id, filename, or spillover path. "
            "Supports summary, head, tail, lines, and query modes."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["summary", "head", "tail", "lines", "query"],
                },
                "query": {"type": "string"},
                "lines": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "line_count": {"type": "integer"},
                "max_bytes": {"type": "integer"},
                "max_matches": {"type": "integer"},
                "context_lines": {"type": "integer"},
            },
            "required": ["ref"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        del context
        reference = _require_string(input_data, "ref").strip()
        if not reference:
            raise ToolError("ref cannot be empty")
        mode = str(input_data.get("mode") or "summary").strip().lower()
        max_bytes = _clamp_int(
            input_data.get("max_bytes"), DEFAULT_MAX_BYTES, 1, HARD_MAX_BYTES
        )
        path = resolve_spillover_reference(reference)
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()

        if mode == "summary":
            max_matches = _clamp_int(
                input_data.get("max_matches"),
                DEFAULT_MAX_MATCHES,
                1,
                HARD_MAX_MATCHES,
            )
            head_count = min(DEFAULT_LINE_COUNT, len(lines))
            tail_count = min(DEFAULT_LINE_COUNT, len(lines))
            payload = {
                "ref": reference,
                "path": str(path),
                "mode": "summary",
                "total_bytes": len(content.encode("utf-8")),
                "total_lines": len(lines),
                "non_empty_lines": sum(1 for ln in lines if ln.strip()),
                "signal_lines": _collect_signal_lines(lines, max_matches),
                "head": _render_numbered_lines(
                    list(enumerate(lines[:head_count], start=1)),
                    max_bytes // 2,
                ),
                "tail": _render_numbered_lines(
                    list(enumerate(lines[-tail_count:], start=len(lines) - tail_count + 1)),
                    max_bytes // 2,
                ),
                "hint": "Use mode=head, tail, lines, or query to retrieve a narrower slice.",
            }
        elif mode in ("head", "tail"):
            count = _clamp_int(
                input_data.get("line_count"),
                DEFAULT_LINE_COUNT,
                1,
                HARD_LINE_COUNT,
            )
            if mode == "head":
                selected = list(enumerate(lines[:count], start=1))
            else:
                start = max(0, len(lines) - count)
                selected = list(enumerate(lines[start:], start=start + 1))
            payload = {
                "ref": reference,
                "path": str(path),
                "mode": mode,
                "total_lines": len(lines),
                "line_count": count,
                "excerpt": _render_numbered_lines(selected, max_bytes),
            }
        elif mode == "lines":
            start, end = _parse_line_selector(input_data, len(lines))
            if start > len(lines):
                excerpt = ""
            else:
                excerpt = _render_numbered_lines(
                    list(enumerate(lines[start - 1 : end], start=start)),
                    max_bytes,
                )
            payload = {
                "ref": reference,
                "path": str(path),
                "mode": "lines",
                "total_lines": len(lines),
                "start_line": start,
                "end_line": min(end, len(lines)),
                "excerpt": excerpt,
            }
        elif mode == "query":
            query = input_data.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ToolError("query is required when mode=query")
            needle = query.strip().lower()
            max_matches = _clamp_int(
                input_data.get("max_matches"),
                DEFAULT_MAX_MATCHES,
                1,
                HARD_MAX_MATCHES,
            )
            context_lines = _clamp_int(
                input_data.get("context_lines"),
                DEFAULT_CONTEXT_LINES,
                0,
                HARD_CONTEXT_LINES,
            )
            matched_lines = 0
            results: list[dict[str, object]] = []
            for idx, line in enumerate(lines):
                if needle not in line.lower():
                    continue
                matched_lines += 1
                if len(results) >= max_matches:
                    continue
                start = max(0, idx - context_lines)
                end = min(len(lines) - 1, idx + context_lines)
                excerpt = _render_numbered_lines(
                    list(enumerate(lines[start : end + 1], start=start + 1)),
                    max_bytes // max(max_matches, 1),
                )
                results.append({"line": idx + 1, "excerpt": excerpt})
            payload = {
                "ref": reference,
                "path": str(path),
                "mode": "query",
                "query": query,
                "total_lines": len(lines),
                "matched_lines": matched_lines,
                "matches_returned": len(results),
                "results": results,
            }
        else:
            raise ToolError(
                f"unsupported mode `{mode}` (expected summary, head, tail, lines, or query)"
            )

        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            metadata={"path": str(path), "mode": mode},
        )
