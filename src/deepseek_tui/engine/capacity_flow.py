"""Capacity checkpoint flow logic for the Engine.

Simplified port of `crates/tui/src/core/engine/capacity_flow.rs:1-975`.
Implements the 3 checkpoint entry points that route to guardrail actions.
Full tool-replay and canonical-state-rebuild logic is deferred (P1).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from deepseek_tui.engine.capacity import (
    CapacityController,
    CapacityDecision,
    CapacityObservationInput,
    CapacitySnapshot,
    GuardrailAction,
)

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message

logger = logging.getLogger(__name__)


def build_observation(
    turn_index: int,
    model: str,
    messages: list[Message],
    action_count: int = 1,
) -> CapacityObservationInput:
    """Build a capacity observation from current conversation state."""
    tool_calls_count = 0
    unique_refs: set[str] = set()
    window = min(len(messages), 24)
    for msg in messages[-window:]:
        for block in msg.content:
            if hasattr(block, "name"):
                tool_calls_count += 1
            if hasattr(block, "id"):
                unique_refs.add(str(block.id))

    total_chars = sum(
        sum(
            len(str(getattr(b, attr, "")))
            for attr in ("text", "content", "input")
            if hasattr(b, attr)
        )
        for msg in messages
        for b in msg.content
    )
    estimated_tokens = max(1, total_chars // 4)
    context_limit = 128_000
    context_used_ratio = min(1.0, estimated_tokens / context_limit)

    return CapacityObservationInput(
        turn_index=turn_index,
        model=model,
        action_count_this_turn=action_count,
        tool_calls_recent_window=tool_calls_count,
        unique_reference_ids_recent_window=len(unique_refs),
        context_used_ratio=context_used_ratio,
    )


async def run_pre_request_checkpoint(
    controller: CapacityController,
    turn_index: int,
    model: str,
    messages: list[Message],
    compact_fn: object | None = None,
) -> tuple[CapacityDecision, bool]:
    """Pre-request checkpoint: if TARGETED_CONTEXT_REFRESH, trigger compaction.

    Returns (decision, compacted) where compacted is True if messages were modified.
    Mirrors capacity_flow.rs:13-34.
    """
    obs = build_observation(turn_index, model, messages)
    snapshot: CapacitySnapshot | None = controller.observe_pre_turn(obs)
    decision = controller.decide(turn_index, snapshot)

    if decision.action == GuardrailAction.TARGETED_CONTEXT_REFRESH:
        if compact_fn is not None and callable(compact_fn):
            try:
                result = await compact_fn(messages)
                messages[:] = result
                logger.info("capacity: pre-request compaction triggered (turn %d)", turn_index)
                return decision, True
            except Exception:
                logger.warning("capacity: pre-request compaction failed", exc_info=True)

    return decision, False


async def run_post_tool_checkpoint(
    controller: CapacityController,
    turn_index: int,
    model: str,
    messages: list[Message],
) -> CapacityDecision:
    """Post-tool checkpoint: observe and decide after tool execution.

    Full VERIFY_WITH_TOOL_REPLAY (re-running read-only tools) is deferred.
    For now, logs the decision and returns it for caller awareness.
    Mirrors capacity_flow.rs:37-76.
    """
    obs = build_observation(turn_index, model, messages)
    snapshot = controller.observe_post_tool(obs)
    decision = controller.decide(turn_index, snapshot)

    if decision.action != GuardrailAction.NO_INTERVENTION:
        logger.info(
            "capacity: post-tool checkpoint action=%s reason=%s (turn %d)",
            decision.action.value,
            decision.reason,
            turn_index,
        )

    return decision


async def run_error_escalation_checkpoint(
    controller: CapacityController,
    turn_index: int,
    model: str,
    messages: list[Message],
    step_error_count: int = 0,
    consecutive_tool_error_steps: int = 0,
) -> CapacityDecision:
    """Error escalation checkpoint: evaluate if errors warrant intervention.

    Full VERIFY_AND_REPLAN (canonical state rebuild) is deferred.
    For now, logs escalation decisions for caller awareness.
    Mirrors capacity_flow.rs:78-151.
    """
    if step_error_count == 0 and consecutive_tool_error_steps < 2:
        return CapacityDecision(
            action=GuardrailAction.NO_INTERVENTION,
            reason="error counts below escalation threshold",
        )

    obs = build_observation(turn_index, model, messages, action_count=step_error_count + 1)
    snapshot = controller.observe_pre_turn(obs)
    decision = controller.decide(turn_index, snapshot)

    if decision.action != GuardrailAction.NO_INTERVENTION:
        logger.warning(
            "capacity: error escalation action=%s reason=%s errors=%d consecutive=%d (turn %d)",
            decision.action.value,
            decision.reason,
            step_error_count,
            consecutive_tool_error_steps,
            turn_index,
        )

    return decision
