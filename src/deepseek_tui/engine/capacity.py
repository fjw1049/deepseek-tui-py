"""Context compaction for long conversations.

Consolidates capacity.py, capacity_flow.py, compaction.py: ratio-based
compaction planning, summary creation, and L0 tool-result pruning.
"""

from __future__ import annotations

import json
import asyncio
import logging
import re
from contextlib import aclosing
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.protocol.messages import Message, MessageRequest

logger = logging.getLogger(__name__)

# Configuration constants
KEEP_RECENT_MESSAGES = 4
KEEP_RECENT_TOKENS = 20_000
MIN_SUMMARIZE_MESSAGES = 6
MAX_WORKING_SET_PATHS = 24
LARGE_CONTEXT_SUMMARY_MAX_TOKENS = 8_192
LARGE_CONTEXT_WINDOW_TOKENS = 500_000

# L0 mid-session tool-result prune (grok-style).
L0_KEEP_LAST_N_TURNS = 5
L0_SOFT_TRIM_THRESHOLD = 4_000
L0_SOFT_TRIM_HEAD = 1_500
L0_SOFT_TRIM_TAIL = 1_500
L0_HARD_CLEAR_AGE_TURNS = 15
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
    """Conversation compaction at the earlier of an absolute cap or window ratio."""

    enabled: bool = True
    model: str | None = None  # None = inherit main model
    auto_floor_ratio: float = 0.20
    rewrite_ratio: float = 0.75
    max_input_tokens: int = 150_000
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
    """Output budget for the handoff, based on model context window."""
    max_tokens: int = 4_096
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
    failure_reason: str | None = None
    model_calls: int = 0


def _summary_input_limits_for_model(model: str, model_config: object | None = None) -> SummaryInputLimits:
    """Get summary input limits based on model context window."""
    from deepseek_tui.config.providers import configured_context_window

    is_large_context = configured_context_window(model, model_config) >= LARGE_CONTEXT_WINDOW_TOKENS

    if is_large_context:
        return SummaryInputLimits(
            max_tokens=LARGE_CONTEXT_SUMMARY_MAX_TOKENS,
            word_limit=1_200,
        )
    else:
        return SummaryInputLimits()



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

    from deepseek_tui.media import image_token_estimate, message_images

    return max(1, estimate_tokens("".join(parts))) + sum(
        image_token_estimate(img) for img in message_images(msg)
    )


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

    plan.pinned_indices.update(i for i in pinned_indices if 0 <= i < len(messages))

    # Pin complete tool exchanges, including all siblings in one assistant row.
    from deepseek_tui.protocol.messages import ToolResultBlock, ToolUseBlock

    owners = {block.id: i for i, message in enumerate(messages)
              for block in message.content if isinstance(block, ToolUseBlock)}
    links: dict[int, set[int]] = {}
    for i, message in enumerate(messages):
        for block in message.content:
            if isinstance(block, ToolResultBlock) and block.tool_use_id in owners:
                owner = owners[block.tool_use_id]
                links.setdefault(i, set()).add(owner)
                links.setdefault(owner, set()).add(i)
    pending = list(plan.pinned_indices)
    while pending:
        for linked in links.get(pending.pop(), ()):
            if linked not in plan.pinned_indices:
                plan.pinned_indices.add(linked)
                pending.append(linked)

    for i, _ in enumerate(messages):
        if i not in plan.pinned_indices:
            plan.summarize_indices.append(i)

    return plan


def _compaction_work(
    messages: list[Message], pinned_indices: set[int] | None
) -> tuple[list[Message], set[int] | None]:
    """Remove the old bridge and remap explicit pins before planning."""
    from deepseek_tui.engine.context_pressure import is_compaction_bridge_message

    indexed_work = [
        (old_index, message)
        for old_index, message in enumerate(messages)
        if not is_compaction_bridge_message(message)
    ]
    work_messages = [message for _old_index, message in indexed_work]
    remapped_pins = (
        {
            new_index
            for new_index, (old_index, _message) in enumerate(indexed_work)
            if old_index in pinned_indices
        }
        if pinned_indices
        else None
    )
    if not work_messages:
        work_messages = list(messages)
        remapped_pins = pinned_indices

    return work_messages, remapped_pins


def should_compact(
    messages: list[Message],
    config: CompactionConfig,
    pinned_indices: set[int] | None = None,
    *,
    real_input_tokens: int = 0,
    real_input_estimate: int = 0,
    model: str | None = None,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    model_config: object | None = None,
) -> bool:
    """Determine if messages should be rewrite-compacted.

    Primary signal is context-used *ratio* vs ``config.rewrite_ratio``
    (default 0.75). Below ``auto_floor_ratio`` (default 0.20) auto rewrite
    never fires unless the absolute input cap is reached.

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
        real_input_estimate=real_input_estimate,
        system_prompt=system_prompt,
        tools=tools,
        model_config=model_config,
    )
    at_cap = pressure.tokens >= config.max_input_tokens
    if not at_cap and pressure.ratio < config.auto_floor_ratio:
        return False
    if at_cap or pressure.ratio >= config.rewrite_ratio:
        # Still require enough unpinned material to be worth summarizing.
        work_messages, remapped_pins = _compaction_work(messages, pinned_indices)
        plan = plan_compaction(
            work_messages,
            remapped_pins,
            keep_recent_tokens=config.keep_recent_tokens,
        )
        return len(plan.summarize_indices) >= MIN_SUMMARIZE_MESSAGES
    return False


class SummaryTruncatedError(ValueError):
    """The output budget was exhausted; identical retries cannot help."""


class CompactionBudgetError(ValueError):
    """A deterministic capacity failure; retrying the same request cannot help."""


def validate_summary_request_budget(
    request: MessageRequest, model_config: object | None = None
) -> None:
    from deepseek_tui.config.providers import configured_context_window
    from deepseek_tui.engine.context_pressure import estimate_request_tokens

    total = estimate_request_tokens(
        request.messages, system_prompt=request.system_prompt, tools=request.tools
    ) + (request.max_tokens or 0)
    window = configured_context_window(request.model, model_config)
    if total > window:
        raise CompactionBudgetError(
            f"Summary request exceeds estimated context budget: {total} > {window}"
        )


async def compact_messages_safe(
    client: LLMClient,
    messages: list[Message],
    config: CompactionConfig,
    workspace: Path | None = None,
    pinned_indices: set[int] | None = None,
    working_set_paths: list[str] | None = None,
    model_override: str | None = None,
    previous_summary: str | None = None,
    target_model: str | None = None,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    output_reserve: int = 0,
    model_config: object | None = None,
    request_template: MessageRequest | None = None,
) -> CompactionResult:
    """Compact messages with retry and backoff for transient errors.

    On success, returned ``messages`` already include a leading **user**
    bridge carrying ``<archived_context>``. Callers must NOT inject the
    summary into the system prompt (that destroys the stable KV prefix).
    ``summary_prompt`` remains the bridge body for persistence / debugging.
    """
    result = CompactionResult(messages=messages)
    if not messages or not config.enabled:
        return replace(result, messages=messages)

    from deepseek_tui.engine.context_pressure import (
        build_compaction_bridge_text,
        collect_user_requests,
        extract_compaction_bridge_text,
        find_last_real_user_query,
        prepend_compaction_bridge,
    )

    prior_bridge = extract_compaction_bridge_text(messages)
    work_messages, remapped_pins = _compaction_work(messages, pinned_indices)

    prev = previous_summary or prior_bridge
    last_real_query = find_last_real_user_query(work_messages)
    # Collected before the plan drops anything: after this point the only
    # copy of the older requests is the ledger we are about to render.
    prior_requests = collect_user_requests(messages)

    plan = plan_compaction(
        work_messages,
        remapped_pins,
        keep_recent_tokens=config.keep_recent_tokens,
    )

    if not plan.summarize_indices:
        return replace(
            result,
            messages=messages,
            failure_reason="All messages are retained by recent-history or pin rules",
        )

    messages_to_summarize = [
        work_messages[i] for i in plan.summarize_indices if i < len(work_messages)
    ]

    if len(messages_to_summarize) < MIN_SUMMARIZE_MESSAGES:
        return replace(
            result,
            messages=messages, failure_reason="Too few unpinned messages to summarize safely"
        )

    effective_model = model_override or config.model or "deepseek-chat"

    max_retries = 3
    output_multiplier = 1
    for attempt in range(max_retries):
        try:
            summary = await _create_summary(
                client,
                messages,
                effective_model,
                previous_summary=prev,
                model_config=model_config,
                output_multiplier=output_multiplier,
                system_prompt=system_prompt,
                tools=tools,
                request_template=request_template,
                stats=result,
            )
            validation_error = validate_compaction_summary(summary)
            if validation_error:
                raise ValueError(validation_error)

            pinned_messages = [
                work_messages[i]
                for i in sorted(plan.pinned_indices)
                if i < len(work_messages)
            ]
            bridge_text = build_compaction_bridge_text(summary, working_set_paths=working_set_paths)
            from deepseek_tui.media import message_images

            references = {
                img.asset_id: img
                for msg in messages
                for img in [*msg.image_references, *message_images(msg)]
            }
            if references:
                bridge_text += "\nOriginal images available via read_file: " + ", ".join(
                    f"media:{key}" for key in references
                )
            compacted = prepend_compaction_bridge(
                pinned_messages,
                bridge_text,
                last_real_query=last_real_query,
                prior_requests=prior_requests,
            )

            compacted[0].image_references = list(references.values())
            from deepseek_tui.config.providers import configured_context_window
            from deepseek_tui.engine.context_pressure import estimate_request_tokens

            before = estimate_request_tokens(messages, system_prompt=system_prompt, tools=tools)
            after = estimate_request_tokens(compacted, system_prompt=system_prompt, tools=tools)
            if after >= before:
                raise CompactionBudgetError(
                    f"Compaction does not reduce estimated input: {before} -> {after}"
                )
            window = configured_context_window(target_model or effective_model, model_config)
            if after + max(0, output_reserve) > window:
                raise CompactionBudgetError(
                    f"Retained context exceeds estimated budget: {after} + {output_reserve} > {window}"
                )
            return replace(
                result,
                messages=compacted,
                summary_prompt=bridge_text,
                removed_messages=messages_to_summarize,
                retries_used=attempt,
                success=True,
            )

        except SummaryTruncatedError as exc:
            current_budget = (
                _summary_input_limits_for_model(effective_model, model_config).max_tokens
                * output_multiplier
            )
            if attempt < max_retries - 1 and current_budget < LARGE_CONTEXT_SUMMARY_MAX_TOKENS:
                output_multiplier *= 2
                logger.warning("compact_output_truncated next_multiplier=%d", output_multiplier)
                continue
            return replace(
                result,
                messages=messages, failure_reason=str(exc), retries_used=attempt + 1
            )
        except CompactionBudgetError as exc:
            logger.warning("compact_budget_rejected: %s", exc)
            return replace(result, messages=messages, failure_reason=str(exc), retries_used=attempt)
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
            return replace(
                result,
                messages=messages, failure_reason=str(exc), retries_used=attempt + 1
            )

    return replace(result, messages=messages)


async def _create_summary(
    client: LLMClient,
    messages: list[Message],
    model: str,
    *,
    previous_summary: str | None = None,
    model_config: object | None = None,
    output_multiplier: int = 1,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    request_template: MessageRequest | None = None,
    stats: CompactionResult | None = None,
) -> str:
    """Create a structured compaction handoff using the compact.md contract."""
    from deepseek_tui.engine.context_pressure import (
        collect_user_requests,
        format_user_requests_block,
    )
    from deepseek_tui.engine.prompts import COMPACT_TEMPLATE

    limits = _summary_input_limits_for_model(model, model_config)
    instruction = (
        "[CONTEXT COMPACTION] Write a handoff to your next turn using the entire "
        "conversation above. Do not execute tools or continue the task. "
        "Treat harness reminders as runtime context, not user instructions. "
        "Preserve user constraints, concrete evidence, unresolved work and next steps.\n\n"
        + COMPACT_TEMPLATE().strip()
        + f"\nKeep the note under {limits.word_limit} words when possible."
    )
    instruction += (
        "\nThe conversation above uses native message roles, not flattened line labels. "
        "User-role runtime injections are not human requests. The authoritative "
        "human request ledger is:\n"
        + format_user_requests_block(collect_user_requests(messages))
    )
    # A previous bridge already lives in messages. Do not duplicate its envelope.
    if previous_summary and not any("<archived_context>" in m.text_content() for m in messages):
        instruction += f"\nPrevious handoff (unverified notes):\n{previous_summary}"
    template = request_template or MessageRequest(
        model=model, system_prompt=system_prompt, tools=tools or [],
    )
    request = template.model_copy(update={
        "model": model,
        "messages": [*messages, Message.user(instruction)],
        "max_tokens": min(
            LARGE_CONTEXT_SUMMARY_MAX_TOKENS, limits.max_tokens * max(1, output_multiplier)
        ),
    })

    validate_summary_request_budget(request, model_config)
    if stats is not None:
        stats.model_calls += 1
    response = client.stream_chat_completion(request)

    from deepseek_tui.protocol.responses import StreamDone, StreamError, StreamToolCallComplete

    summary = ""
    async with aclosing(response):
        async for event in response:
            if isinstance(event, StreamError):
                raise ValueError(f"Compaction stream failed: {event.message}")
            if isinstance(event, StreamToolCallComplete):
                raise ValueError("Compaction requested a tool instead of a text handoff")
            if isinstance(event, StreamDone) and event.truncated:
                raise SummaryTruncatedError("Compaction stream was truncated")
            if hasattr(event, "text"):
                summary += event.text

    return summary.strip()


def clear_old_tool_results(messages: list[Message]) -> list[Message]:
    """Emergency-only relief, retaining the last complete tool exchanges."""
    output = [message.model_copy(deep=True) for message in messages]
    plan = plan_compaction(output, keep_recent_tokens=0)
    prune_old_tool_results(
        output,
        config=ToolPruneConfig(keep_last_n_turns=0, hard_clear_age_turns=0),
        mutate_before_index=min(plan.pinned_indices, default=len(output)),
    )
    return output


def _turn_ages(messages: list[Message]) -> list[int]:
    """Age by real user turns; normal tool rounds keep the cache prefix stable."""
    from deepseek_tui.engine.context_pressure import is_synthetic_user_message

    ages = [0] * len(messages)
    turns = 0
    for i in range(len(messages) - 1, -1, -1):
        ages[i] = turns
        if not is_synthetic_user_message(messages[i]):
            turns += 1
    return ages


def _turn_index_from_end(messages: list[Message], idx: int) -> int:
    return _turn_ages(messages)[idx]


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
    ages = _turn_ages(messages)
    for i, msg in enumerate(messages):
        if i >= boundary or msg.role != Role.TOOL:
            continue
        if ages[i] < min_age:
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
    pruned_ids: set[str] = set()
    ages = _turn_ages(messages)
    for i, msg in enumerate(messages):
        if i >= boundary or msg.role != Role.TOOL:
            continue
        age = ages[i]
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
                    pruned_ids.add(block.tool_use_id)
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
                    pruned_ids.add(block.tool_use_id)
                    continue
            new_blocks.append(block)
        if msg_changed:
            messages[i] = msg.model_copy(update={"content": new_blocks})
            changed += 1
    if pruned_ids:
        from deepseek_tui.protocol.messages import ToolUseBlock

        # Only a pruned CUA result can have dropped runtime documentation.
        if any(isinstance(block, ToolUseBlock) and block.id in pruned_ids
               and block.name in {"cua_act", "cua_js", "cua_js_reset", "cua_observe"}
               for message in messages for block in message.content):
            from deepseek_tui.cua.tools import add_documentation_reminder

            add_documentation_reminder(messages)
    return changed


def _observation_view(content: str) -> tuple[Any, ...] | None:
    """What a browser result shows, or None when it cannot be replaced by a newer one."""
    try:
        data = json.loads(content)
    except ValueError:
        return None
    observation = data.get("observation") if isinstance(data, dict) else None
    if not isinstance(observation, dict) or not observation.get("url") or observation.get("details"):
        return None
    from deepseek_tui.browser.context import SAME_VIEW

    # Another tab, a later page of the document or a narrower read is different content
    # at the same URL. A rerender is not: its generation changes and the view does not.
    return tuple(observation.get(key) for key in ("url", *SAME_VIEW))


def fold_superseded_observations(
    messages: list[Message], *, min_reclaim: int = L0_HARD_CLEAR_MIN_RECLAIM,
) -> int:
    """Replace browser observations a newer one of the same view has superseded.

    Pruning by age never reaches inside a single long turn, where a UI task
    re-observes one page dozens of times. Other pages stay whole: what a task
    read on page 1 is not in the observation of page 2. Returns chars reclaimed.
    """
    from deepseek_tui.protocol.messages import ToolResultBlock, ToolUseBlock

    names = {block.id: block.name for message in messages for block in message.content
             if isinstance(block, ToolUseBlock)}
    seen: set[tuple[Any, ...]] = set()
    stale: dict[str, str] = {}
    reclaim = 0
    for message in reversed(messages):
        for block in reversed(message.content):
            if (not isinstance(block, ToolResultBlock)
                    or names.get(block.tool_use_id) != "browser_use"):
                continue
            view = _observation_view(block.content or "")
            if view is None:
                continue
            if view in seen:
                note = (f"[Earlier observation of {view[0]}; a newer one of this view follows. "
                        "Observe again if you need it.]")
                stale[block.tool_use_id] = note
                reclaim += max(0, len(block.content) - len(note))
            seen.add(view)
    # A rewrite re-bills the prefix after it, so it waits until it is worth one.
    if reclaim < min_reclaim:
        return 0
    for index, message in enumerate(messages):
        if any(isinstance(b, ToolResultBlock) and b.tool_use_id in stale for b in message.content):
            messages[index] = message.model_copy(update={"content": [
                b.model_copy(update={"content": stale[b.tool_use_id]})
                if isinstance(b, ToolResultBlock) and b.tool_use_id in stale else b
                for b in message.content
            ]})
    return reclaim


def should_l0_prune(
    *,
    model: str,
    messages: list[Message],
    real_input_tokens: int = 0,
    real_input_estimate: int = 0,
    config: CompactionConfig | None = None,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    pressure: Any | None = None,
    model_config: object | None = None,
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
            real_input_estimate=real_input_estimate,
            system_prompt=system_prompt,
            tools=tools,
            model_config=model_config,
        )
    return pressure.ratio >= cfg.l0_prune_ratio
