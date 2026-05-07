"""Context compaction for long conversations.

Mirrors `crates/tui/src/compaction.rs:1-2008`
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.protocol.messages import Message

# Configuration constants (mirrors Rust)
KEEP_RECENT_MESSAGES = 4
MIN_SUMMARIZE_MESSAGES = 6
MAX_WORKING_SET_PATHS = 24
SUMMARY_TEXT_SNIPPET_CHARS = 800
SUMMARY_TOOL_RESULT_SNIPPET_CHARS = 240
SUMMARY_INPUT_MAX_CHARS = 24_000
SUMMARY_INPUT_HEAD_CHARS = 14_000
SUMMARY_INPUT_TAIL_CHARS = 6_000
LARGE_CONTEXT_SUMMARY_TEXT_SNIPPET_CHARS = 2_000
LARGE_CONTEXT_SUMMARY_TOOL_RESULT_SNIPPET_CHARS = 4_000
LARGE_CONTEXT_SUMMARY_INPUT_MAX_CHARS = 120_000
LARGE_CONTEXT_SUMMARY_INPUT_HEAD_CHARS = 72_000
LARGE_CONTEXT_SUMMARY_INPUT_TAIL_CHARS = 36_000
LARGE_CONTEXT_SUMMARY_MAX_TOKENS = 2_048
LARGE_CONTEXT_WINDOW_TOKENS = 500_000


@dataclass
class CompactionConfig:
    """Configuration for conversation compaction behavior."""
    enabled: bool = True
    token_threshold: int = 50_000
    message_threshold: int = 50
    model: str = "deepseek-chat"
    cache_summary: bool = True


@dataclass
class SummaryInputLimits:
    """Input limits for summary based on model context window."""
    text_snippet_chars: int = SUMMARY_TEXT_SNIPPET_CHARS
    tool_result_snippet_chars: int = SUMMARY_TOOL_RESULT_SNIPPET_CHARS
    input_max_chars: int = SUMMARY_INPUT_MAX_CHARS
    input_head_chars: int = SUMMARY_INPUT_HEAD_CHARS
    input_tail_chars: int = SUMMARY_INPUT_TAIL_CHARS
    max_tokens: int = 1_024
    word_limit: int = 500


@dataclass
class CompactionPlan:
    """Plan for which messages to pin vs summarize."""
    pinned_indices: set[int] = field(default_factory=set)
    summarize_indices: list[int] = field(default_factory=list)


@dataclass
class CompactionResult:
    """Result of a compaction operation with metadata."""
    messages: list[Message]
    summary_prompt: str | None = None
    removed_messages: list[Message] = field(default_factory=list)
    retries_used: int = 0


def _summary_input_limits_for_model(model: str) -> SummaryInputLimits:
    """Get summary input limits based on model context window."""
    # Simplified: assume deepseek models have large context
    is_large_context = "reasoner" in model or model in [
        "deepseek-chat",
        "deepseek-v4-pro",
    ]

    if is_large_context:
        return SummaryInputLimits(
            text_snippet_chars=LARGE_CONTEXT_SUMMARY_TEXT_SNIPPET_CHARS,
            tool_result_snippet_chars=LARGE_CONTEXT_SUMMARY_TOOL_RESULT_SNIPPET_CHARS,
            input_max_chars=LARGE_CONTEXT_SUMMARY_INPUT_MAX_CHARS,
            input_head_chars=LARGE_CONTEXT_SUMMARY_INPUT_HEAD_CHARS,
            input_tail_chars=LARGE_CONTEXT_SUMMARY_INPUT_TAIL_CHARS,
            max_tokens=LARGE_CONTEXT_SUMMARY_MAX_TOKENS,
            word_limit=900,
        )
    else:
        return SummaryInputLimits()


def _truncate_chars(text: str, max_chars: int) -> str:
    """Truncate text to max character count."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _tail_chars(text: str, max_chars: int) -> str:
    """Extract last max_chars characters from text."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _extract_paths_from_text(text: str, workspace: Path | None = None) -> list[str]:
    """Extract file paths from text using regex patterns."""
    paths: list[str] = []
    if not text:
        return paths

    # Match common file patterns: .py, .rs, .toml, .json, .md, etc.
    pattern = (
        r"(?:^|\s|[\[\(\'\"])([./\-\w]+\.(?:py|rs|toml|json|yaml|md|txt|"
        r"sh|sql|js|ts|tsx|jsx))"
    )
    for match in re.finditer(pattern, text, re.MULTILINE):
        candidate = match.group(1).strip("'\"")
        normalized = _normalize_path_candidate(candidate, workspace)
        if normalized and normalized not in paths:
            paths.append(normalized)

    return paths


def _normalize_path_candidate(path: str, workspace: Path | None = None) -> str | None:
    """Normalize a path candidate, returning None if invalid."""
    if not path or len(path) < 2 or len(path) > 500:
        return None

    try:
        # Try to parse as Path
        p = Path(path)
        return str(p)
    except (ValueError, OSError):
        return None


def _extract_paths_from_tool_input(
    input_data: Any, workspace: Path | None = None
) -> list[str]:
    """Extract file paths from tool input (dict/JSON)."""
    paths: list[str] = []
    if not isinstance(input_data, dict):
        return paths

    # Check single path keys
    for key in ["path", "file", "target", "cwd"]:
        if key in input_data and isinstance(input_data[key], str):
            candidate = input_data[key]
            normalized = _normalize_path_candidate(candidate, workspace)
            if normalized:
                paths.append(normalized)

    # Check list path keys
    for key in ["paths", "files", "targets"]:
        if key in input_data and isinstance(input_data[key], list):
            for item in input_data[key]:
                if isinstance(item, str):
                    normalized = _normalize_path_candidate(item, workspace)
                    if normalized:
                        paths.append(normalized)

    return paths


def _estimate_tokens_for_message(msg: Message, include_thinking: bool = True) -> int:
    """Estimate token count for a message (conservative)."""
    total_chars = 0

    for block in msg.content:
        # Handle block as object (ContentBlock union types)
        if hasattr(block, "text"):
            total_chars += len(str(getattr(block, "text", "")))
        if hasattr(block, "input"):
            total_chars += len(str(getattr(block, "input", "")))
        if hasattr(block, "content"):
            total_chars += len(str(getattr(block, "content", "")))
        if hasattr(block, "thinking") and include_thinking:
            total_chars += len(str(getattr(block, "thinking", "")))

    # Conservative estimate: ~4 characters per token
    return max(1, total_chars // 4)


def plan_compaction(
    messages: list[Message],
    pinned_indices: set[int] | None = None,
) -> CompactionPlan:
    """Generate a compaction plan for messages.

    Args:
        messages: Message history
        pinned_indices: Indices of messages to always keep

    Returns:
        Compaction plan with pinned and summarize indices
    """
    if not messages:
        return CompactionPlan()

    plan = CompactionPlan()
    pinned_indices = pinned_indices or set()

    # Always pin last KEEP_RECENT_MESSAGES messages
    for i in range(max(0, len(messages) - KEEP_RECENT_MESSAGES), len(messages)):
        plan.pinned_indices.add(i)

    # Always pin explicitly pinned indices
    plan.pinned_indices.update(pinned_indices)

    # Collect messages to summarize (not pinned)
    for i, _ in enumerate(messages):
        if i not in plan.pinned_indices:
            plan.summarize_indices.append(i)

    return plan


def should_compact(
    messages: list[Message],
    config: CompactionConfig,
    pinned_indices: set[int] | None = None,
) -> bool:
    """Determine if messages should be compacted.

    Args:
        messages: Current message history
        config: Compaction configuration
        pinned_indices: Explicitly pinned message indices

    Returns:
        True if compaction should trigger
    """
    if not config.enabled or not messages:
        return False

    plan = plan_compaction(messages, pinned_indices)

    # Count pinned messages and tokens
    pinned_count = len(plan.pinned_indices)
    pinned_tokens = sum(
        _estimate_tokens_for_message(messages[i], include_thinking=True)
        for i in plan.pinned_indices
        if i < len(messages)
    )

    # Estimate tokens to summarize
    token_estimate = sum(
        _estimate_tokens_for_message(messages[i], include_thinking=False)
        for i in plan.summarize_indices
        if i < len(messages)
    )
    message_count = len(plan.summarize_indices)

    # Adjust thresholds based on pinned messages
    effective_token_threshold = max(0, config.token_threshold - pinned_tokens)
    effective_message_threshold = max(0, config.message_threshold - pinned_count)

    # Always compact if token threshold exceeded
    if token_estimate > effective_token_threshold and effective_token_threshold > 0:
        return True

    # Need enough unpinned messages to justify compaction
    enough_unpinned = (
        message_count >= MIN_SUMMARIZE_MESSAGES
        or effective_token_threshold == 0
        or effective_message_threshold == 0
    )
    if not enough_unpinned:
        return False

    return token_estimate > effective_token_threshold or message_count > effective_message_threshold


async def compact_messages_safe(
    client: LLMClient,
    messages: list[Message],
    config: CompactionConfig,
    workspace: Path | None = None,
    pinned_indices: set[int] | None = None,
    working_set_paths: list[str] | None = None,
) -> CompactionResult:
    """Compact messages with retry and backoff for transient errors.

    Args:
        client: LLM client for summary generation
        messages: Message history to compact
        config: Compaction configuration
        workspace: Workspace directory (for path normalization)
        pinned_indices: Explicitly pinned message indices
        working_set_paths: Working set file paths for reference

    Returns:
        Compaction result with compacted messages and summary
    """
    if not messages or not config.enabled:
        return CompactionResult(messages=messages)

    # Generate compaction plan
    plan = plan_compaction(messages, pinned_indices)

    if not plan.summarize_indices:
        return CompactionResult(messages=messages)

    # Collect messages to summarize
    messages_to_summarize = [messages[i] for i in plan.summarize_indices if i < len(messages)]

    if len(messages_to_summarize) < MIN_SUMMARIZE_MESSAGES:
        return CompactionResult(messages=messages)

    # Generate summary with retries
    max_retries = 3
    for attempt in range(max_retries):
        try:
            summary = await _create_summary(client, messages_to_summarize, config.model)

            # Build result with pinned + summary
            pinned_messages = [
                messages[i] for i in sorted(plan.pinned_indices) if i < len(messages)
            ]
            removed_messages = messages_to_summarize

            # Create system block with summary
            summary_prompt = _build_summary_system_prompt(summary, working_set_paths)

            return CompactionResult(
                messages=pinned_messages,
                summary_prompt=summary_prompt,
                removed_messages=removed_messages,
                retries_used=attempt,
            )

        except Exception:
            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s
                delay = (2 ** attempt)
                await asyncio.sleep(delay)
                continue
            # Final attempt failed, return original messages
            return CompactionResult(messages=messages, retries_used=attempt + 1)

    return CompactionResult(messages=messages)


async def _create_summary(client: LLMClient, messages: list[Message], model: str) -> str:
    """Create a summary of messages using LLM."""
    limits = _summary_input_limits_for_model(model)

    # Format conversation for summarization
    conversation_text = ""
    for msg in messages:
        role = "User" if msg.role == "user" else "Assistant"
        for block in msg.content:
            if hasattr(block, "text"):
                text = getattr(block, "text", "")
                snippet = _truncate_chars(str(text), limits.text_snippet_chars)
                conversation_text += f"{role}: {snippet}\n\n"
            elif hasattr(block, "name"):
                name = getattr(block, "name", "unknown")
                conversation_text += f"{role}: [Used tool: {name}]\n\n"
            elif hasattr(block, "content"):
                content = getattr(block, "content", "")
                snippet = _truncate_chars(str(content), limits.tool_result_snippet_chars)
                conversation_text += f"Tool result: {snippet}\n\n"

    # Truncate conversation if too long (head + tail pattern)
    conv_chars = len(conversation_text)
    if conv_chars > limits.input_max_chars:
        head = _truncate_chars(conversation_text, limits.input_head_chars)
        tail = _tail_chars(conversation_text, limits.input_tail_chars)
        omitted = max(0, conv_chars - len(head) - len(tail))
        conversation_text = f"{head}\n\n[... {omitted} characters omitted ...]\n\n{tail}"

    # Call LLM for summary
    from deepseek_tui.protocol.requests import MessageRequest

    summary_prompt = (
        "Summarize the following conversation in a concise but comprehensive way. "
        "Preserve key information, decisions made, exact file paths, commands, "
        "errors, and tool-result facts needed to continue the work. "
        "Tool outputs may be abbreviated only when repetitive. "
        f"Keep it under {limits.word_limit} words.\n\n---\n\n{conversation_text}"
    )

    request = MessageRequest(
        model=model,
        messages=[Message.user(summary_prompt)],
        max_tokens=limits.max_tokens,
        system_prompt="You are a helpful assistant that creates concise conversation summaries.",
        stream=False,
    )

    response = client.stream_chat_completion(request)

    # Extract text from response (simplified - just get first text block)
    summary = ""
    async for event in response:
        if hasattr(event, "text"):
            summary += event.text

    return summary.strip()



def _build_summary_system_prompt(summary: str, working_set_paths: list[str] | None = None) -> str:
    """Build system prompt block with summary and working set context."""
    prompt = f"<archived_context>\n{summary}\n</archived_context>"

    if working_set_paths:
        prompt += "\n\n**Working Set Files:**\n"
        for path in working_set_paths[:10]:
            prompt += f"- {path}\n"

    return prompt
