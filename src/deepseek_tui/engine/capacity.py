"""Context compaction for long conversations.

Consolidates capacity.py, capacity_flow.py, compaction.py: ratio-based
compaction planning, summary creation, and L0 tool-result pruning.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.protocol.messages import Message

logger = logging.getLogger(__name__)

# Configuration constants
KEEP_RECENT_MESSAGES = 4
KEEP_RECENT_TOKENS = 20_000
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

# L0 mid-session tool-result prune (grok-style).
L0_KEEP_LAST_N_TURNS = 3
L0_SOFT_TRIM_THRESHOLD = 4_000
L0_SOFT_TRIM_HEAD = 1_500
L0_SOFT_TRIM_TAIL = 1_500
L0_HARD_CLEAR_AGE_TURNS = 10
# Default hard-clear body when no spillover path is recoverable. Prefer
# ``format_hard_clear_placeholder`` so spilled outputs keep a re-read pointer.
L0_HARD_CLEAR_PLACEHOLDER = "[Tool result omitted — too old]"
# Minimum chars a hard-clear pass must reclaim before it may run.
#
# A clear rewrites bodies that already sit in the provider's KV prefix, so the
# next request re-bills everything from that point at full price. Ages tick per
# user turn, so without a floor a single newly-aged result is enough to break
# the prefix every turn. Measured on a 25-turn tool-heavy session: clearing
# every turn held the cacheable prefix at ~27%; batching until this much is
# reclaimable lifted it to ~58% for ~7% more average payload, cutting effective
# input billing by roughly a third. Waiting costs nothing permanent — the
# bodies stay soft-trimmed and get cleared in one batch later.
L0_HARD_CLEAR_MIN_RECLAIM = 16_000


@dataclass
class CompactionConfig:
    """Ratio-based conversation compaction policy (relative to model window)."""

    enabled: bool = True
    model: str | None = None  # None = inherit main model
    auto_floor_ratio: float = 0.20
    rewrite_ratio: float = 0.75
    keep_recent_tokens: int = KEEP_RECENT_TOKENS
    l0_prune_ratio: float = 0.50
    l0_prune_enabled: bool = True


@dataclass
class ToolPruneConfig:
    """Deterministic mid-session pruning of old tool result bodies."""

    enabled: bool = True
    trigger_ratio: float = 0.50
    keep_last_n_turns: int = L0_KEEP_LAST_N_TURNS
    soft_trim_threshold: int = L0_SOFT_TRIM_THRESHOLD
    soft_trim_head: int = L0_SOFT_TRIM_HEAD
    soft_trim_tail: int = L0_SOFT_TRIM_TAIL
    hard_clear_age_turns: int = L0_HARD_CLEAR_AGE_TURNS
    # 0 = clear as soon as a body is old enough. Above 0, defer the clear until
    # the whole eligible batch reclaims this many chars, so the prefix break is
    # paid once per batch instead of once per turn.
    hard_clear_min_reclaim: int = 0


@dataclass
class SummaryInputLimits:
    """Input limits for summary based on model context window."""
    text_snippet_chars: int = SUMMARY_TEXT_SNIPPET_CHARS
    tool_result_snippet_chars: int = SUMMARY_TOOL_RESULT_SNIPPET_CHARS
    input_max_chars: int = SUMMARY_INPUT_MAX_CHARS
    input_head_chars: int = SUMMARY_INPUT_HEAD_CHARS
    input_tail_chars: int = SUMMARY_INPUT_TAIL_CHARS
    max_tokens: int = 1_536
    word_limit: int = 700


# Required headings in a structured compaction handoff (compact.md).
_REQUIRED_HANDOFF_HEADINGS = ("### Goal", "### Next step")


def validate_compaction_summary(summary: str) -> str | None:
    """Return an error reason if *summary* is not a usable handoff, else None."""
    text = (summary or "").strip()
    if not text:
        return "compaction summary came back empty"
    # Reject trivially short prose that cannot carry a structured handoff.
    if len(text) < 40:
        return "compaction summary too short to be a handoff"
    missing = [h for h in _REQUIRED_HANDOFF_HEADINGS if h not in text]
    if missing:
        return f"compaction summary missing required headings: {', '.join(missing)}"
    return None


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
    success: bool = False


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
            word_limit=1_200,
        )
    else:
        return SummaryInputLimits()



def _elide_middle(text: str, max_chars: int) -> str:
    """Trim *text* to *max_chars* keeping both ends, and say that you did.

    The summarizer's per-block limit used to be a silent head cut. Two things
    went wrong with that. A conclusion sits at the *end* of a message — "so
    I'll use X because Y", the assertion line of a traceback — so head-only
    keeps the exploration and drops the decision. And with no marker the
    summarizer cannot tell a complete short message from a severed long one,
    so it records half a decision as the whole decision. L0 prune already
    trims tool results head+tail for the same reason.
    """
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    marker_template = "\n[... {} characters omitted ...]\n"
    # Reserve room for the marker so the result honours max_chars.
    budget = max_chars - len(marker_template.format(len(text)))
    if budget < 2:
        return _truncate_chars(text, max_chars)
    head_chars = (budget * 2) // 3
    tail_chars = budget - head_chars
    omitted = len(text) - head_chars - tail_chars
    return (
        text[:head_chars]
        + marker_template.format(omitted)
        + text[len(text) - tail_chars :]
    )


_TOOL_ARG_VALUE_CHARS = 160
_TOOL_ARGS_TOTAL_CHARS = 480


def _render_tool_args(args: dict[str, Any]) -> str:
    """Say which action a tool call was, without reproducing its payload.

    ``[Used tool: edit_file]`` does not tell the summarizer which file was
    edited, so ``### Done`` cannot name the patches it is asked to name.

    Size separates the two kinds of argument on its own, which is why there
    is no per-tool table here: the ones that identify the action — path,
    command, pattern, url — are short, and the ones carrying a body —
    content, old_string, prompt — are not. A table would also have to be
    kept in step with every new tool and could never cover MCP tools
    registered at runtime. Oversized values collapse to their size, which
    still records that a body was there.
    """
    if not args:
        return ""
    parts: list[str] = []
    used = 0
    for key, value in args.items():
        rendered = value if isinstance(value, str) else repr(value)
        if len(rendered) > _TOOL_ARG_VALUE_CHARS:
            rendered = f"<{len(rendered)} chars>"
        part = f"{key}={rendered}"
        if used + len(part) > _TOOL_ARGS_TOTAL_CHARS:
            parts.append("...")
            break
        parts.append(part)
        used += len(part)
    return ", ".join(parts)


def _truncate_chars(text: str, max_chars: int) -> str:
    """Keep the first *max_chars* characters, respecting Unicode."""
    if max_chars == 0:
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


def _estimate_tokens_for_message(msg: Message, include_thinking: bool = True) -> int:
    """Estimate token count for a message (conservative)."""
    from deepseek_tui.engine.context import estimate_tokens

    parts: list[str] = []
    for block in msg.content:
        # Handle block as object (ContentBlock union types)
        if hasattr(block, "text"):
            parts.append(str(getattr(block, "text", "")))
        if hasattr(block, "input"):
            parts.append(str(getattr(block, "input", "")))
        if hasattr(block, "content"):
            parts.append(str(getattr(block, "content", "")))
        if hasattr(block, "thinking") and include_thinking:
            parts.append(str(getattr(block, "thinking", "")))

    return max(1, estimate_tokens("".join(parts)))


def plan_compaction(
    messages: list[Message],
    pinned_indices: set[int] | None = None,
    *,
    keep_recent_tokens: int = KEEP_RECENT_TOKENS,
) -> CompactionPlan:
    """Generate a compaction plan for messages.

    Pins a recent verbatim window sized by *keep_recent_tokens* (with a
    floor of :data:`KEEP_RECENT_MESSAGES`), walking back so the window
    never starts on a tool-result message.
    """
    if not messages:
        return CompactionPlan()

    plan = CompactionPlan()
    pinned_indices = pinned_indices or set()
    from deepseek_tui.protocol.messages import Role

    # Grow the keep window from the end until token budget is met (or we
    # hit the message floor, whichever needs more history).
    start = len(messages)
    accumulated = 0
    min_messages = KEEP_RECENT_MESSAGES
    while start > 0:
        need_more_msgs = (len(messages) - start) < min_messages
        need_more_tokens = accumulated < keep_recent_tokens
        if not need_more_msgs and not need_more_tokens:
            break
        start -= 1
        accumulated += _estimate_tokens_for_message(
            messages[start], include_thinking=False
        )

    while start > 0 and messages[start].role == Role.TOOL:
        start -= 1
    for i in range(start, len(messages)):
        plan.pinned_indices.add(i)

    plan.pinned_indices.update(pinned_indices)

    for i, _ in enumerate(messages):
        if i not in plan.pinned_indices:
            plan.summarize_indices.append(i)

    return plan


def should_compact(
    messages: list[Message],
    config: CompactionConfig,
    pinned_indices: set[int] | None = None,
    *,
    real_input_tokens: int = 0,
    model: str | None = None,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> bool:
    """Determine if messages should be rewrite-compacted.

    Primary signal is context-used *ratio* vs ``config.rewrite_ratio``
    (default 0.75). Below ``auto_floor_ratio`` (default 0.20) auto rewrite
    never fires — L0 pruning handles that band.

    Pass *system_prompt* and *tools* whenever available: on the estimate
    path they are a multi-thousand-token constant that the message list
    alone cannot see, so omitting them biases every threshold low.
    """
    if not config.enabled or not messages:
        return False

    from deepseek_tui.engine.context_pressure import measure_context_pressure

    pressure = measure_context_pressure(
        model or config.model or "deepseek-chat",
        messages,
        real_input_tokens=real_input_tokens,
        system_prompt=system_prompt,
        tools=tools,
    )
    if pressure.ratio < config.auto_floor_ratio:
        return False
    if pressure.ratio >= config.rewrite_ratio:
        # Still require enough unpinned material to be worth summarizing.
        plan = plan_compaction(
            messages,
            pinned_indices,
            keep_recent_tokens=config.keep_recent_tokens,
        )
        return len(plan.summarize_indices) >= MIN_SUMMARIZE_MESSAGES
    return False


async def compact_messages_safe(
    client: LLMClient,
    messages: list[Message],
    config: CompactionConfig,
    workspace: Path | None = None,
    pinned_indices: set[int] | None = None,
    working_set_paths: list[str] | None = None,
    model_override: str | None = None,
    previous_summary: str | None = None,
) -> CompactionResult:
    """Compact messages with retry and backoff for transient errors.

    On success, returned ``messages`` already include a leading **user**
    bridge carrying ``<archived_context>``. Callers must NOT inject the
    summary into the system prompt (that destroys the stable KV prefix).
    ``summary_prompt`` remains the bridge body for persistence / debugging.
    """
    if not messages or not config.enabled:
        return CompactionResult(messages=messages)

    from deepseek_tui.engine.context_pressure import (
        build_compaction_bridge_text,
        collect_user_requests,
        extract_compaction_bridge_text,
        find_last_real_user_query,
        is_compaction_bridge_message,
        prepend_compaction_bridge,
    )

    # Drop any prior bridge from the plan input; its text becomes previous_summary.
    prior_bridge = extract_compaction_bridge_text(messages)
    work_messages = [m for m in messages if not is_compaction_bridge_message(m)]
    if not work_messages:
        work_messages = list(messages)

    prev = previous_summary or prior_bridge
    last_real_query = find_last_real_user_query(work_messages)
    # Collected before the plan drops anything: after this point the only
    # copy of the older requests is the ledger we are about to render.
    prior_requests = collect_user_requests(messages)

    plan = plan_compaction(
        work_messages,
        pinned_indices,
        keep_recent_tokens=config.keep_recent_tokens,
    )

    if not plan.summarize_indices:
        return CompactionResult(messages=messages)

    messages_to_summarize = [
        work_messages[i] for i in plan.summarize_indices if i < len(work_messages)
    ]

    if len(messages_to_summarize) < MIN_SUMMARIZE_MESSAGES:
        return CompactionResult(messages=messages)

    effective_model = model_override or config.model or "deepseek-chat"

    max_retries = 3
    for attempt in range(max_retries):
        try:
            summary = await _create_summary(
                client,
                messages_to_summarize,
                effective_model,
                previous_summary=prev,
            )
            validation_error = validate_compaction_summary(summary)
            if validation_error:
                raise ValueError(validation_error)

            pinned_messages = [
                work_messages[i]
                for i in sorted(plan.pinned_indices)
                if i < len(work_messages)
            ]
            bridge_text = build_compaction_bridge_text(
                summary, working_set_paths=working_set_paths
            )
            compacted = prepend_compaction_bridge(
                pinned_messages,
                bridge_text,
                last_real_query=last_real_query,
                prior_requests=prior_requests,
            )

            return CompactionResult(
                messages=compacted,
                summary_prompt=bridge_text,
                removed_messages=messages_to_summarize,
                retries_used=attempt,
                success=True,
            )

        except Exception as exc:
            logger.warning(
                "compact_attempt_failed attempt=%d/%d error=%s",
                attempt + 1, max_retries, exc,
                exc_info=True,
            )
            if attempt < max_retries - 1:
                delay = 2**attempt
                await asyncio.sleep(delay)
                continue
            logger.warning(
                "compact_all_retries_exhausted retries=%d",
                max_retries,
                exc_info=True,
            )
            return CompactionResult(messages=messages, retries_used=attempt + 1)

    return CompactionResult(messages=messages)


async def _create_summary(
    client: LLMClient,
    messages: list[Message],
    model: str,
    *,
    previous_summary: str | None = None,
) -> str:
    """Create a structured compaction handoff using the compact.md contract."""
    from deepseek_tui.engine.context_pressure import is_synthetic_user_message

    limits = _summary_input_limits_for_model(model)

    # Format conversation for summarization
    conversation_text = ""
    for msg in messages:
        # Reminders and cycle seeds all ride the user role.
        # Labelling them "User" lets the summarizer attribute harness text to
        # the human, which then replays as a user constraint after compaction.
        if msg.role != "user":
            role = "Assistant"
        elif is_synthetic_user_message(msg):
            role = "Harness"
        else:
            role = "User"
        for block in msg.content:
            if hasattr(block, "text"):
                text = getattr(block, "text", "")
                snippet = _elide_middle(str(text), limits.text_snippet_chars)
                conversation_text += f"{role}: {snippet}\n\n"
            elif hasattr(block, "name"):
                name = getattr(block, "name", "unknown")
                args = _render_tool_args(getattr(block, "input", None) or {})
                conversation_text += f"{role}: [Used tool: {name}({args})]\n\n"
            elif hasattr(block, "content"):
                content = getattr(block, "content", "")
                snippet = _elide_middle(
                    str(content), limits.tool_result_snippet_chars
                )
                conversation_text += f"Tool result: {snippet}\n\n"

    # Truncate conversation if too long (head + tail pattern)
    conv_chars = len(conversation_text)
    if conv_chars > limits.input_max_chars:
        head = _truncate_chars(conversation_text, limits.input_head_chars)
        tail = _tail_chars(conversation_text, limits.input_tail_chars)
        omitted = max(0, conv_chars - len(head) - len(tail))
        conversation_text = f"{head}\n\n[... {omitted} characters omitted ...]\n\n{tail}"

    from deepseek_tui.engine.prompts import COMPACT_TEMPLATE
    from deepseek_tui.protocol.messages import MessageRequest

    handoff_contract = COMPACT_TEMPLATE().strip()
    system_prompt = (
        "You are the coding agent whose session is being compacted, writing a "
        "handoff note to your own next turn. Follow the contract. Prefer "
        "continuity and concrete detail over prose polish, and keep the shape "
        "the task calls for rather than filling every heading. Do not call "
        "tools. Lines labelled 'Harness:' are automated injections from the "
        "agent runtime, not the human — never record their wording as a user "
        "request or user constraint."
    )
    previous_block = ""
    if previous_summary and previous_summary.strip():
        previous_block = (
            "Your previous handoff note (authoritative; PRESERVE still-true "
            "facts, ADD new progress, UPDATE Next step):\n"
            f"<previous-summary>\n{previous_summary.strip()}\n</previous-summary>\n\n"
        )
    user_prompt = (
        f"{handoff_contract}\n\n"
        f"Keep the note under {limits.word_limit} words when possible; the two "
        "required headings and the detail needed to continue take priority over "
        "the word limit.\n\n"
        f"{previous_block}"
        "---\n\n"
        "Conversation to archive:\n\n"
        f"{conversation_text}"
    )

    request = MessageRequest(
        model=model,
        messages=[Message.user(user_prompt)],
        max_tokens=limits.max_tokens,
        system_prompt=system_prompt,
    )

    response = client.stream_chat_completion(request)

    summary = ""
    async for event in response:
        if hasattr(event, "text"):
            summary += event.text

    return summary.strip()



def _turn_index_from_end(messages: list[Message], idx: int) -> int:
    """Approximate turn age: how many user turns sit after *idx*."""
    from deepseek_tui.protocol.messages import Role

    turns = 0
    for i in range(idx + 1, len(messages)):
        if messages[i].role == Role.USER:
            turns += 1
    return turns


def _pending_hard_clear_reclaim(
    messages: list[Message], cfg: ToolPruneConfig, boundary: int
) -> int:
    """Chars a hard-clear pass would reclaim right now.

    Mirrors the eligibility checks in :func:`prune_old_tool_results` without
    mutating anything, so the caller can weigh the prefix break a clear costs
    against the window it buys. Bodies whose placeholder would be *longer* than
    the body contribute nothing rather than a negative.
    """
    from deepseek_tui.protocol.messages import Role, ToolResultBlock
    from deepseek_tui.tools.runtime import format_hard_clear_placeholder

    min_age = max(cfg.keep_last_n_turns, cfg.hard_clear_age_turns)
    reclaim = 0
    for i, msg in enumerate(messages):
        if i >= boundary or msg.role != Role.TOOL:
            continue
        if _turn_index_from_end(messages, i) < min_age:
            continue
        for block in msg.content:
            if not isinstance(block, ToolResultBlock):
                continue
            content = block.content or ""
            saved = len(content) - len(format_hard_clear_placeholder(content))
            reclaim += max(0, saved)
    return reclaim


def prune_old_tool_results(
    messages: list[Message],
    *,
    config: ToolPruneConfig | None = None,
    mutate_before_index: int | None = None,
) -> int:
    """Soft-trim / hard-clear old tool result bodies in place.

    Only mutates tool messages with index ``< mutate_before_index`` (defaults
    to everything except the last ``keep_last_n_turns``). Does not touch
    assistant tool_call structure. Returns the number of tool bodies changed.
    """
    cfg = config or ToolPruneConfig()
    if not cfg.enabled or not messages:
        return 0

    from deepseek_tui.protocol.messages import Role, ToolResultBlock

    boundary = (
        mutate_before_index
        if mutate_before_index is not None
        else len(messages)
    )
    allow_hard_clear = True
    if cfg.hard_clear_min_reclaim > 0:
        reclaim = _pending_hard_clear_reclaim(messages, cfg, boundary)
        allow_hard_clear = reclaim >= cfg.hard_clear_min_reclaim
        if not allow_hard_clear and reclaim:
            logger.debug(
                "l0_hard_clear_deferred reclaimable=%d threshold=%d",
                reclaim,
                cfg.hard_clear_min_reclaim,
            )
    changed = 0
    for i, msg in enumerate(messages):
        if i >= boundary or msg.role != Role.TOOL:
            continue
        age = _turn_index_from_end(messages, i)
        if age < cfg.keep_last_n_turns:
            continue
        new_blocks = []
        msg_changed = False
        for block in msg.content:
            if not isinstance(block, ToolResultBlock):
                new_blocks.append(block)
                continue
            content = block.content or ""
            if allow_hard_clear and age >= cfg.hard_clear_age_turns:
                from deepseek_tui.tools.runtime import format_hard_clear_placeholder

                cleared = format_hard_clear_placeholder(content)
                if cleared != content:
                    new_blocks.append(
                        block.model_copy(update={"content": cleared})
                    )
                    msg_changed = True
                else:
                    new_blocks.append(block)
                continue
            if len(content) > cfg.soft_trim_threshold:
                head = content[: cfg.soft_trim_head]
                tail = content[-cfg.soft_trim_tail :]
                trimmed = (
                    f"{head}\n\n[... tool output pruned for context ...]\n\n{tail}"
                )
                # Soft-trim keeps a tail slice; if that slice drops a spillover
                # footer, append a compact re-read pointer so the path survives.
                from deepseek_tui.tools.runtime import (
                    extract_spillover_path_from_text,
                )

                spill_path = extract_spillover_path_from_text(content)
                if (
                    spill_path is not None
                    and extract_spillover_path_from_text(trimmed) is None
                ):
                    trimmed = (
                        f"{trimmed.rstrip()}\n\n"
                        f"[Full output saved to {spill_path}. "
                        f'Use `read_file path="{spill_path}"` to inspect.]'
                    )
                if trimmed != content:
                    new_blocks.append(block.model_copy(update={"content": trimmed}))
                    msg_changed = True
                    continue
            new_blocks.append(block)
        if msg_changed:
            messages[i] = msg.model_copy(update={"content": new_blocks})
            changed += 1
    return changed


def should_l0_prune(
    *,
    model: str,
    messages: list[Message],
    real_input_tokens: int = 0,
    config: CompactionConfig | None = None,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    pressure: Any | None = None,
) -> bool:
    """True when context ratio warrants mid-session tool pruning.

    Pass ``pressure`` when the caller already measured it — the L0 call site
    needs the ratio anyway to decide how aggressively to prune, and measuring
    twice per round is pure waste on long histories.
    """
    cfg = config or CompactionConfig()
    if not cfg.l0_prune_enabled:
        return False
    if pressure is None:
        from deepseek_tui.engine.context_pressure import measure_context_pressure

        pressure = measure_context_pressure(
            model,
            messages,
            real_input_tokens=real_input_tokens,
            system_prompt=system_prompt,
            tools=tools,
        )
    return pressure.ratio >= cfg.l0_prune_ratio
