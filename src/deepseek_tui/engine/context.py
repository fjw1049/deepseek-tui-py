"""Context budgeting and prompt-shaping helpers for the engine.

Mirrors `crates/tui/src/core/engine/context.rs:1-382`.
Shared by the streaming turn loop, capacity flow, and engine session
maintenance code.
"""

from __future__ import annotations

import json
import math
from typing import Any

from deepseek_tui.config.provider_registry import context_window_for_model
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.base import ToolResult

# --- Constants (Rust context.rs:17-44) -----------------------------------

TURN_MAX_OUTPUT_TOKENS = 262_144
MIN_RECENT_MESSAGES_TO_KEEP = 4
MAX_CONTEXT_RECOVERY_ATTEMPTS = 2
CONTEXT_HEADROOM_TOKENS = 1024

TOOL_RESULT_CONTEXT_HARD_LIMIT_CHARS = 12_000
TOOL_RESULT_CONTEXT_SOFT_LIMIT_CHARS = 2_000
TOOL_RESULT_CONTEXT_SNIPPET_CHARS = 900

LARGE_CONTEXT_TOOL_RESULT_HARD_LIMIT_CHARS = 180_000
LARGE_CONTEXT_TOOL_RESULT_SOFT_LIMIT_CHARS = 60_000
LARGE_CONTEXT_TOOL_RESULT_SNIPPET_CHARS = 40_000

LARGE_CONTEXT_WINDOW_TOKENS = 500_000

TOOL_RESULT_METADATA_SUMMARY_CHARS = 320

COMPACTION_SUMMARY_MARKER = "Conversation Summary (Auto-Generated)"
WORKING_SET_SUMMARY_MARKER = "## Repo Working Set"

# --- Text summarization (Rust context.rs:52-84) --------------------------


def summarize_text(text: str, limit: int) -> str:
    """Truncate text to limit characters, appending '...' if cut."""
    if len(text) <= limit:
        return text
    take = max(0, limit - 3)
    return text[:take] + "..."


def summarize_text_head_tail(text: str, limit: int) -> str:
    """Keep head + tail of text with a truncation marker in the middle."""
    total = len(text)
    if total <= limit:
        return text
    if limit <= 20:
        return summarize_text(text, limit)

    marker = "\n\n[... output truncated for context ...]\n\n"
    marker_len = len(marker)
    if limit <= marker_len + 20:
        return summarize_text(text, limit)

    remaining = limit - marker_len
    head_len = (remaining * 2) // 3
    tail_len = remaining - head_len
    return text[:head_len] + marker + text[total - tail_len :]


# --- Tool result compaction (Rust context.rs:86-263) ----------------------

_NOISY_TOOLS = frozenset(
    {
        "exec_shell",
        "exec_shell_wait",
        "exec_shell_interact",
        "multi_tool_use.parallel",
        "web_search",
    }
)


def _tool_result_is_noisy(tool_name: str) -> bool:
    return tool_name in _NOISY_TOOLS


def _tool_result_metadata_summary(metadata: dict[str, Any] | None) -> str | None:
    if not metadata or not isinstance(metadata, dict):
        return None
    for key in ("summary", "stdout_summary", "stderr_summary", "message"):
        val = metadata.get(key)
        if isinstance(val, str) and val.strip():
            return summarize_text(val.strip(), TOOL_RESULT_METADATA_SUMMARY_CHARS)
    return None


def _summarize_subagent_status(status: Any) -> str:
    if isinstance(status, str):
        return status
    if isinstance(status, dict):
        for kind, value in status.items():
            if isinstance(value, str) and value.strip():
                return f"{kind}({summarize_text(value.strip(), 120)})"
            return str(kind)
    return str(status)


def _summarize_subagent_snapshot(snapshot: Any, index: int) -> str:
    if not isinstance(snapshot, dict):
        return f"- item {index}: {summarize_text(str(snapshot), 240)}"

    lines: list[str] = []

    result = snapshot.get("result")
    if isinstance(result, str) and result.strip():
        lines.append(f"- result: {summarize_text(result.strip(), 1600)}")
    else:
        lines.append("- result: (not available yet)")

    meta: list[str] = []
    agent_id = snapshot.get("agent_id")
    if isinstance(agent_id, str) and agent_id.strip():
        meta.append(f"id={agent_id}")
    agent_type = snapshot.get("agent_type")
    if isinstance(agent_type, str) and agent_type.strip():
        meta.append(f"type={agent_type}")
    status = _summarize_subagent_status(snapshot.get("status", "unknown"))
    if status and status != "unknown":
        meta.append(f"status={status}")

    assignment = snapshot.get("assignment")
    if isinstance(assignment, dict):
        objective = assignment.get("objective")
        if isinstance(objective, str) and objective.strip():
            meta.append(f"objective={summarize_text(objective.strip(), 120)}")

    steps = snapshot.get("steps_taken")
    duration_ms = snapshot.get("duration_ms")
    if steps is not None or duration_ms is not None:
        s = str(steps) if steps is not None else "?"
        d = str(duration_ms) if duration_ms is not None else "?"
        meta.append(f"steps={s}, duration_ms={d}")

    if meta:
        lines.append(f"  ({'; '.join(meta)})")

    return "\n".join(lines)


def _compact_subagent_tool_result_for_context(
    tool_name: str, raw: str
) -> str | None:
    """Compact agent_result / agent_wait payloads for parent context."""
    if tool_name not in ("agent_result", "agent_wait", "wait"):
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if isinstance(parsed, list):
        snapshots = parsed
    elif isinstance(parsed, dict):
        snapshots = [parsed]
    else:
        return None

    out = [
        "[sub-agent result summarized for parent context]",
        "Lead with the result body; metadata is for routing only.",
        "Child results are self-reports — verify side effects with tools before claiming success.",
    ]
    for idx, snap in enumerate(snapshots):
        if idx >= 8:
            remaining = len(snapshots) - idx
            out.append(
                f"- ... {remaining} more sub-agent result(s) omitted from context summary"
            )
            break
        out.append(_summarize_subagent_snapshot(snap, idx + 1))
    return "\n".join(out)


def _tool_result_context_limits(model: str) -> tuple[int, int, int]:
    """Return (hard_limit, noisy_soft_limit, snippet) for the model."""
    window = context_window_for_model(model)
    if window >= LARGE_CONTEXT_WINDOW_TOKENS:
        return (
            LARGE_CONTEXT_TOOL_RESULT_HARD_LIMIT_CHARS,
            LARGE_CONTEXT_TOOL_RESULT_SOFT_LIMIT_CHARS,
            LARGE_CONTEXT_TOOL_RESULT_SNIPPET_CHARS,
        )
    return (
        TOOL_RESULT_CONTEXT_HARD_LIMIT_CHARS,
        TOOL_RESULT_CONTEXT_SOFT_LIMIT_CHARS,
        TOOL_RESULT_CONTEXT_SNIPPET_CHARS,
    )


def compact_tool_result_for_context(
    model: str, tool_name: str, output: ToolResult
) -> str:
    """Compact a tool result before inserting into the model transcript.

    Mirrors Rust ``compact_tool_result_for_context`` (context.rs:228-263).
    """
    raw = output.content.strip()
    if not raw:
        return ""

    subagent = _compact_subagent_tool_result_for_context(tool_name, raw)
    if subagent is not None:
        return subagent

    hard_limit, noisy_soft, snippet_chars = _tool_result_context_limits(model)
    raw_len = len(raw)
    should_compact = raw_len > hard_limit or (
        _tool_result_is_noisy(tool_name) and raw_len > noisy_soft
    )
    if not should_compact:
        return raw

    snippet = summarize_text_head_tail(raw, snippet_chars)
    omitted = raw_len - len(snippet)
    summary = _tool_result_metadata_summary(output.metadata)

    if summary:
        return (
            f"[{tool_name} output compacted to protect context]\n"
            f"Summary: {summary}\n"
            f"Snippet: {snippet}\n"
            f"(Original: {raw_len} chars, omitted: {omitted} chars.)"
        )
    return (
        f"[{tool_name} output compacted to protect context]\n"
        f"Snippet: {snippet}\n"
        f"(Original: {raw_len} chars, omitted: {omitted} chars.)"
    )


# --- System prompt management (Rust context.rs:265-339) -------------------


def extract_compaction_summary_prompt(prompt: str | None) -> str | None:
    """Extract compaction summary block from a system prompt string.

    Recognizes both the legacy marker and the ``<archived_context>`` tag
    actually emitted by ``compaction._build_summary_system_prompt`` — the
    two had drifted apart, making this function never match real output.
    """
    if not prompt:
        return None
    if COMPACTION_SUMMARY_MARKER not in prompt and "<archived_context>" not in prompt:
        return None
    return prompt


def remove_working_set_summary(prompt: str | None) -> str | None:
    """Remove the working-set summary block from a system prompt."""
    if not prompt:
        return None
    lines = prompt.split("\n")
    filtered = [line for line in lines if WORKING_SET_SUMMARY_MARKER not in line]
    result = "\n".join(filtered).strip()
    return result or None


def append_working_set_summary(
    prompt: str | None, working_set_summary: str | None
) -> str | None:
    """Append a working-set summary to the system prompt."""
    summary = (working_set_summary or "").strip()
    if not summary:
        return prompt
    base = remove_working_set_summary(prompt) or ""
    if base:
        return f"{base}\n\n{summary}"
    return summary


# --- Token estimation (Rust context.rs:341-378) --------------------------


def _estimate_text_tokens_conservative(text: str) -> int:
    return math.ceil(len(text) / 3)


def estimate_input_tokens_conservative(
    messages: list[Message], system_prompt: str | None = None
) -> int:
    """Conservative estimate of input tokens including system prompt.

    Mirrors Rust ``estimate_input_tokens_conservative`` (context.rs:356-366).
    """
    msg_chars = 0
    for msg in messages:
        for block in msg.content:
            for attr in ("text", "content", "input"):
                val = getattr(block, attr, None)
                if isinstance(val, str):
                    msg_chars += len(val)
                elif isinstance(val, dict):
                    msg_chars += len(json.dumps(val))
    message_tokens = (msg_chars * 3) // 2  # conservative 1.5x

    system_tokens = (
        _estimate_text_tokens_conservative(system_prompt) if system_prompt else 0
    )

    framing_overhead = len(messages) * 12 + 48

    return message_tokens + system_tokens + framing_overhead


def context_input_budget(model: str, requested_output_tokens: int) -> int | None:
    """Calculate usable input token budget after reserving output + headroom.

    Mirrors Rust ``context_input_budget`` (context.rs:368-374), with one
    fix: the output reservation is clamped to a quarter of the window.
    Without the clamp, models whose window is smaller than the requested
    output reservation (e.g. 128K window vs 262K reservation) computed a
    negative budget and silently skipped overflow prechecks entirely.
    """
    window = context_window_for_model(model)
    reserve = min(requested_output_tokens, window // 4)
    budget = window - reserve - CONTEXT_HEADROOM_TOKENS
    return budget if budget > 0 else None


def turn_response_headroom_tokens() -> int:
    return TURN_MAX_OUTPUT_TOKENS + CONTEXT_HEADROOM_TOKENS


def is_context_length_error_message(message: str) -> bool:
    """Heuristic check for context-length errors from the provider."""
    lower = message.lower()
    return any(
        needle in lower
        for needle in (
            "context length",
            "context_length",
            "maximum context",
            "token limit",
            "too many tokens",
            "reduce the length",
            "context window",
        )
    )


# --- Legacy aliases (keep backward compatibility with turn_loop) ----------

def estimated_input_tokens(messages: list[Message]) -> int:
    """Rough estimate of input tokens from message list (legacy)."""
    total_chars = 0
    for m in messages:
        total_chars += len(json.dumps(m.model_dump()))
    return max(1, total_chars // 4)


def _api_tool_name(tool: dict[str, Any]) -> str:
    function = tool.get("function")
    if not isinstance(function, dict):
        return ""
    name = function.get("name")
    return name if isinstance(name, str) else ""


def _tool_schema_buckets(api_tools: list[dict[str, Any]] | None) -> tuple[int, int]:
    if not api_tools:
        return 0, 0

    from deepseek_tui.engine.dispatch import is_mcp_tool

    tool_definitions = 0
    mcp = 0
    for tool in api_tools:
        tokens = _estimate_text_tokens_conservative(json.dumps(tool, ensure_ascii=False))
        if is_mcp_tool(_api_tool_name(tool)):
            mcp += tokens
        else:
            tool_definitions += tokens
    return tool_definitions, mcp


def estimate_context_breakdown(
    *,
    model: str,
    messages: list[Message] | None = None,
    system_prompt_override: str | None = None,
    skills_context: str | None = None,
    working_set_summary: str | None = None,
    api_tools: list[dict[str, Any]] | None = None,
    workspace: Any | None = None,
    mode: str = "agent",
) -> dict[str, int]:
    """Estimate token occupancy by category for the next request.

    Shared by :meth:`Engine.context_breakdown`, TUI ``/context``, and the
    Workbench runtime API.

    ``tools`` and ``free`` are retained for old Workbench/TUI clients. Newer
    clients should prefer the more explainable top-level buckets:
    ``tool_definitions``, ``mcp``, ``skills``, ``rules``, and ``conversation``.
    """
    from pathlib import Path

    from deepseek_tui.engine.prompts import build_system_prompt
    from deepseek_tui.prompts import AppMode

    target_model = model or ""
    try:
        app_mode = AppMode((mode or "agent").strip().lower())
    except ValueError:
        app_mode = AppMode.AGENT
    if system_prompt_override and system_prompt_override.strip():
        system_tokens = _estimate_text_tokens_conservative(
            system_prompt_override.strip()
        )
        rules_tokens = 0
        skills_tokens = 0
    else:
        ws = Path(workspace).expanduser().resolve() if workspace else None
        system_text = build_system_prompt(
            None,
            working_set_summary=working_set_summary,
            workspace=ws,
            mode=app_mode,
            project_context_enabled=False,
        )
        system_tokens = _estimate_text_tokens_conservative(system_text)

        rules_text = ""
        if ws is not None:
            from deepseek_tui.engine.project_context import (
                load_project_context_with_parents,
            )

            rules_text = load_project_context_with_parents(ws).as_system_block()
        rules_tokens = (
            _estimate_text_tokens_conservative(rules_text.strip())
            if rules_text.strip()
            else 0
        )
        skills_tokens = (
            _estimate_text_tokens_conservative(skills_context.strip())
            if skills_context and skills_context.strip()
            else 0
        )

    tool_definitions_tokens, mcp_tokens = _tool_schema_buckets(api_tools)
    tools_tokens = tool_definitions_tokens + mcp_tokens

    conv_tokens = estimated_input_tokens(messages) if messages else 0
    total = (
        system_tokens
        + rules_tokens
        + skills_tokens
        + tools_tokens
        + conv_tokens
    )
    window = context_window_for_model(target_model) or 0
    free = max(0, window - total) if window else 0

    return {
        "system_prompt": system_tokens,
        "tool_definitions": tool_definitions_tokens,
        "tools": tools_tokens,
        "mcp": mcp_tokens,
        "skills": skills_tokens,
        "rules": rules_tokens,
        "conversation": conv_tokens,
        "total": total,
        "window": window,
        "free": free,
    }
