"""Memory, review, recall, plan, note, rlm_query, and skill_load tools.

Mirrors Rust tools at ``crates/tui/src/tools/{remember,review,recall_archive}.rs``
and ``crates/tui/src/commands/{note,review}.rs``.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config

# ===========================================================================
# remember — persist a note to user memory (Rust remember.rs, 138 LOC)
# ===========================================================================


class RememberTool(ToolSpec):
    """Append a durable note to the user memory file."""

    def name(self) -> str:
        return "remember"

    def description(self) -> str:
        return (
            "Append a durable note to the user memory file so it surfaces in "
            "future sessions. Use this when the user states a preference, a "
            "convention they want enforced, or a fact about themselves or "
            "their workflow that you should not have to relearn next time. "
            "Keep notes terse (one sentence)."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": "The single-sentence durable note to remember.",
                }
            },
            "required": ["note"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        note = _require_string(input_data, "note")
        memory_path = _memory_path(context)
        memory_path.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        entry = f"- ({timestamp}) {note.strip()}\n"
        with memory_path.open("a", encoding="utf-8") as f:
            f.write(entry)

        return ToolResult(
            success=True,
            content=f"remembered: {note.strip()}",
            metadata={"path": str(memory_path)},
        )


# ===========================================================================
# note — quick note tool (Rust commands/note.rs, ~60 LOC)
# ===========================================================================


class NoteTool(ToolSpec):
    """Append a quick note to the session notes file."""

    def name(self) -> str:
        return "note"

    def description(self) -> str:
        return "Append a short note to the session notes file for later reference."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The note content.",
                }
            },
            "required": ["content"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        content = _require_string(input_data, "content")
        notes_path = _notes_path(context)
        notes_path.parent.mkdir(parents=True, exist_ok=True)

        entry = f"\n---\n{content.strip()}\n"
        with notes_path.open("a", encoding="utf-8") as f:
            f.write(entry)

        return ToolResult(
            success=True,
            content=f"Note appended to {notes_path}",
            metadata={"path": str(notes_path)},
        )


# ===========================================================================
# review — code review tool (Rust tools/review.rs, 540 LOC)
# ===========================================================================

REVIEW_SYSTEM_PROMPT = (
    "You are a senior code reviewer. Return ONLY valid JSON with the following schema:\n"
    '{\n  "summary": "short overview",\n'
    '  "issues": [\n    {\n      "severity": "error|warning|info",\n'
    '      "title": "issue title",\n      "description": "details and impact",\n'
    '      "path": "relative/file/path or null",\n      "line": 123\n    }\n  ],\n'
    '  "suggestions": [\n    {\n      "path": "relative/file/path or null",\n'
    '      "line": 123,\n      "suggestion": "actionable improvement"\n    }\n  ],\n'
    '  "overall_assessment": "final assessment"\n}\n'
    "If a field is unknown, use an empty string or null. "
    "Prioritize correctness and missing tests."
)

DEFAULT_MAX_CHARS = 200_000


class ReviewTool(ToolSpec):
    """Perform structured code review via LLM."""

    def __init__(self, config: Config | None = None) -> None:
        self._config = config

    def name(self) -> str:
        return "review"

    def description(self) -> str:
        return (
            "Analyze code (file, diff, or PR) and produce a structured review "
            "with issues, suggestions, and an overall assessment."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "File path, 'git diff', or 'pr:<number>' to review.",
                },
                "focus": {
                    "type": "string",
                    "description": "Optional focus area (e.g. 'security', 'performance').",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max chars of content to send for review.",
                },
            },
            "required": ["target"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.NETWORK]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        target = _require_string(input_data, "target")
        focus = _optional_string(input_data, "focus")
        max_chars = _optional_int(input_data, "max_chars") or DEFAULT_MAX_CHARS

        content = _gather_review_content(target, context, max_chars)
        user_prompt = f"Review the following code:\n\n```\n{content}\n```"
        if focus:
            user_prompt += f"\n\nFocus especially on: {focus}"

        from deepseek_tui.client.deepseek import DeepSeekClient
        from deepseek_tui.config.loader import ConfigLoader
        from deepseek_tui.config.models import Config
        from deepseek_tui.protocol.messages import Message

        config = self._config
        if config is None:
            try:
                config = ConfigLoader().load()
            except Exception:
                config = Config()
        client = DeepSeekClient.from_config(config)

        from deepseek_tui.protocol.requests import MessageRequest

        request = MessageRequest(
            model="deepseek-chat",
            messages=[Message.user(user_prompt)],
            system_prompt=REVIEW_SYSTEM_PROMPT,
            max_tokens=2048,
        )

        result_text: list[str] = []
        from deepseek_tui.protocol.responses import StreamTextDelta

        async for event in client.stream_with_retry(request):
            if isinstance(event, StreamTextDelta):
                result_text.append(event.text)

        output = "".join(result_text)
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = {"raw": output}

        return ToolResult(
            success=True,
            content=output,
            metadata={"target": target, "parsed": parsed},
        )


# ===========================================================================
# rlm_query — recursive LLM query (Rust rlm/, 406 LOC)
# ===========================================================================


class RlmQueryTool(ToolSpec):
    """Send a sub-query to the LLM and return the answer."""

    def __init__(self, config: Config | None = None) -> None:
        self._config = config

    def name(self) -> str:
        return "rlm_query"

    def description(self) -> str:
        return (
            "Send a focused sub-query to the LLM to get an answer without "
            "consuming main conversation context. Useful for factual lookups, "
            "summarization, or focused analysis."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question or task for the LLM.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional context to include.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum tokens in the response.",
                },
            },
            "required": ["query"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.NETWORK]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        query = _require_string(input_data, "query")
        extra_context = _optional_string(input_data, "context") or ""
        max_tokens = _optional_int(input_data, "max_tokens") or 1024

        user_content = query
        if extra_context:
            user_content = f"Context:\n{extra_context}\n\nQuestion:\n{query}"

        from deepseek_tui.client.deepseek import DeepSeekClient
        from deepseek_tui.config.loader import ConfigLoader
        from deepseek_tui.config.models import Config
        from deepseek_tui.protocol.messages import Message
        from deepseek_tui.protocol.requests import MessageRequest
        from deepseek_tui.protocol.responses import StreamTextDelta

        config = self._config
        if config is None:
            try:
                config = ConfigLoader().load()
            except Exception:
                config = Config()
        try:
            client = DeepSeekClient.from_config(config)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                content=f"rlm_query: cannot build LLM client: {exc}",
                metadata={"query": query},
            )

        request = MessageRequest(
            model=getattr(config, "model", None) or "deepseek-chat",
            messages=[Message.user(user_content)],
            max_tokens=max_tokens,
            stream=True,
        )

        result_text: list[str] = []
        try:
            async for event in client.stream_chat_completion(request):
                if isinstance(event, StreamTextDelta):
                    result_text.append(event.text)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                content=f"rlm_query failed: {exc}",
                metadata={"query": query},
            )
        finally:
            await client.close()

        output = "".join(result_text)
        return ToolResult(success=True, content=output, metadata={"query": query})


# ===========================================================================
# plan_update — update the agent's plan (Rust 406 LOC)
# ===========================================================================


class PlanUpdateTool(ToolSpec):
    """Update the current execution plan."""

    def name(self) -> str:
        return "update_plan"

    def description(self) -> str:
        return (
            "Update or replace the current execution plan. Use this to track "
            "progress, add new steps, or mark steps complete."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "The full updated plan (markdown format).",
                },
                "completed_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Steps to mark as completed.",
                },
            },
            "required": ["plan"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        plan = _require_string(input_data, "plan")
        plan_path = context.working_directory / ".deepseek" / "plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(plan, encoding="utf-8")

        return ToolResult(
            success=True,
            content=f"Plan updated ({len(plan)} chars)",
            metadata={"path": str(plan_path)},
        )


# ===========================================================================
# recall_archive — BM25 search over cycle archives (Rust 723 LOC)
# ===========================================================================

DEFAULT_MAX_RECALL_RESULTS = 3
HARD_MAX_RECALL_RESULTS = 10
CONTEXT_WINDOW_CHARS = 240
K1 = 1.5
B = 0.75


class RecallArchiveTool(ToolSpec):
    """Search prior context cycles for content not in the briefing."""

    def name(self) -> str:
        return "recall_archive"

    def description(self) -> str:
        return (
            "Search prior context cycles for content not in your briefing. "
            "Use sparingly — frequent recalls mean your briefing was too sparse."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. BM25-scored against archived messages.",
                },
                "cycle": {
                    "type": "integer",
                    "description": "Optional: limit to a specific prior cycle number.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum hits to return (default 3, capped at 10).",
                },
            },
            "required": ["query"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        query = _require_string(input_data, "query")
        cycle_filter = _optional_int(input_data, "cycle")
        max_results = min(
            _optional_int(input_data, "max_results") or DEFAULT_MAX_RECALL_RESULTS,
            HARD_MAX_RECALL_RESULTS,
        )

        archives_dir = _archives_dir(context)
        if not archives_dir.exists():
            return ToolResult(
                success=True,
                content="No cycle archives found.",
                metadata={"hits": 0},
            )

        hits = _bm25_search(archives_dir, query, cycle_filter, max_results)
        if not hits:
            return ToolResult(
                success=True,
                content="No matching archived messages found.",
                metadata={"hits": 0, "query": query},
            )

        lines = []
        for hit in hits:
            lines.append(
                f"[cycle {hit['cycle']}, msg {hit['index']}, {hit['role']}] "
                f"(score={hit['score']:.2f})\n  {hit['excerpt']}"
            )
        content = "\n\n".join(lines)
        return ToolResult(
            success=True,
            content=content,
            metadata={"hits": len(hits), "query": query},
        )


# ===========================================================================
# skill_load — load a skill file into context (Rust 365 LOC)
# ===========================================================================


class SkillLoadTool(ToolSpec):
    """Load a skill file to extend the agent's capabilities."""

    def name(self) -> str:
        return "skill_load"

    def description(self) -> str:
        return (
            "Load a SKILL.md file from the skills directory to provide "
            "specialized instructions for a particular task."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to load (e.g. 'uml', 'review').",
                },
                "path": {
                    "type": "string",
                    "description": "Alternative: direct path to a SKILL.md file.",
                },
            },
            "required": [],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        skill_name = _optional_string(input_data, "skill_name")
        path_str = _optional_string(input_data, "path")

        if path_str:
            skill_path = Path(path_str).expanduser()  # noqa: ASYNC240
        elif skill_name:
            skill_path = _find_skill(skill_name, context)
        else:
            raise ToolError("Either 'skill_name' or 'path' must be provided")

        if not skill_path.exists():
            raise ToolError(f"Skill file not found: {skill_path}")

        content = skill_path.read_text(encoding="utf-8")
        return ToolResult(
            success=True,
            content=content,
            metadata={"skill": skill_name or skill_path.name, "path": str(skill_path)},
        )


# ===========================================================================
# Helpers
# ===========================================================================


def _require_string(input_data: dict[str, object], key: str) -> str:
    value = input_data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"'{key}' must be a non-empty string")
    return value


def _optional_string(input_data: dict[str, object], key: str) -> str | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"'{key}' must be a string")
    return value


def _optional_int(input_data: dict[str, object], key: str) -> int | None:
    value = input_data.get(key)
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    raise ToolError(f"'{key}' must be an integer")


def _memory_path(context: ToolContext) -> Path:
    """``~/.deepseek/memory.md`` — cross-project long-term memory.

    Mirrors Rust ``tui/config.rs:1930``. ``DEEPSEEK_MEMORY_PATH`` overrides
    for tests.
    """
    from deepseek_tui.config.paths import user_memory_path

    env = os.environ.get("DEEPSEEK_MEMORY_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    return user_memory_path()


def _notes_path(context: ToolContext) -> Path:
    """``~/.deepseek/notes.txt`` — user scratch notes (Rust .txt format).

    ``DEEPSEEK_NOTES_PATH`` env var overrides (used by tests to isolate
    writes from the real ``~/.deepseek/notes.txt``).
    """
    from deepseek_tui.config.paths import user_notes_path

    env = os.environ.get("DEEPSEEK_NOTES_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    return user_notes_path()


def _archives_dir(context: ToolContext) -> Path:
    """Cycle archive search root.

    Rust cycle archives live at ``~/.deepseek/sessions/<id>/cycles/``
    (cycle_manager.rs:460-475); ``_bm25_search`` recurses under this root
    to find every session's cycles. ``DEEPSEEK_ARCHIVES_DIR`` env var
    overrides (used by tests to isolate from the real sessions tree).
    """
    from deepseek_tui.config.paths import user_sessions_dir

    env = os.environ.get("DEEPSEEK_ARCHIVES_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return user_sessions_dir()


def _find_skill(name: str, context: ToolContext) -> Path:
    # ``~/.claude/skills`` stays in $HOME — that's a Claude-Code convention
    # owned by a different tool, not part of our ``.deepseek/`` namespace.
    candidates = [
        context.working_directory / ".deepseek" / "skills" / name / "SKILL.md",
        Path.home() / ".claude" / "skills" / name / "SKILL.md",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _gather_review_content(target: str, context: ToolContext, max_chars: int) -> str:
    if target.startswith("git diff") or target == "diff":
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(context.working_directory),
                timeout=30,
            )
            return result.stdout[:max_chars]
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            raise ToolError(f"Failed to run git diff: {e}") from e

    if target.startswith("pr:"):
        try:
            pr_num = target[3:].strip()
            result = subprocess.run(
                ["gh", "pr", "diff", pr_num],
                capture_output=True,
                text=True,
                cwd=str(context.working_directory),
                timeout=30,
            )
            return result.stdout[:max_chars]
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            raise ToolError(f"Failed to get PR diff: {e}") from e

    file_path = (context.working_directory / target).resolve()
    if not file_path.exists():
        raise ToolError(f"File not found: {target}")
    content = file_path.read_text(encoding="utf-8", errors="replace")
    return content[:max_chars]


# --- BM25 search for recall_archive ----------------------------------------


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _bm25_search(
    archives_dir: Path,
    query: str,
    cycle_filter: int | None,
    max_results: int,
) -> list[dict[str, Any]]:
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    documents: list[dict[str, Any]] = []
    # Walk any ``*.jsonl`` under ``archives_dir`` so we pick up both the
    # real layout (``sessions/<id>/cycles/*.jsonl`` per Rust
    # cycle_manager.rs:460-475) and tests that stage flat files.
    for path in sorted(archives_dir.rglob("*.jsonl")):
        cycle_num = _extract_cycle_num(path.name)
        if cycle_filter is not None and cycle_num != cycle_filter:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _extract_text(msg)
            if text:
                documents.append({
                    "cycle": cycle_num,
                    "index": i,
                    "role": msg.get("role", "unknown"),
                    "text": text,
                    "tokens": _tokenize(text),
                })

    if not documents:
        return []

    avg_dl = sum(len(d["tokens"]) for d in documents) / len(documents)
    df: Counter[str] = Counter()
    for doc in documents:
        unique = set(doc["tokens"])
        for term in unique:
            df[term] += 1

    n = len(documents)
    scored: list[tuple[float, dict[str, Any]]] = []
    for doc in documents:
        score = 0.0
        dl = len(doc["tokens"])
        tf_map = Counter(doc["tokens"])
        for term in query_terms:
            if term not in tf_map:
                continue
            tf = tf_map[term]
            idf = math.log((n - df[term] + 0.5) / (df[term] + 0.5) + 1.0)
            numerator = tf * (K1 + 1)
            denominator = tf + K1 * (1 - B + B * dl / avg_dl)
            score += idf * numerator / denominator
        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    hits = []
    for score, doc in scored[:max_results]:
        excerpt = doc["text"][:CONTEXT_WINDOW_CHARS]
        if len(doc["text"]) > CONTEXT_WINDOW_CHARS:
            excerpt += "…"
        hits.append({
            "cycle": doc["cycle"],
            "index": doc["index"],
            "role": doc["role"],
            "score": score,
            "excerpt": excerpt,
        })
    return hits


def _extract_cycle_num(filename: str) -> int:
    m = re.search(r"(\d+)", filename)
    return int(m.group(1)) if m else 0


def _extract_text(msg: dict[str, Any]) -> str:
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return ""
