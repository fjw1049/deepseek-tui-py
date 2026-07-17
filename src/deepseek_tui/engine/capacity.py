"""Capacity control — token budget, rate limiting, compaction.

Consolidates capacity.py, capacity_flow.py, compaction.py.
Capacity-aware guardrail controller for context pressure management.
"""

from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field

from deepseek_tui.config.models import CapacityConfig
import logging
from typing import TYPE_CHECKING
import asyncio
import re
from pathlib import Path


class GuardrailAction(enum.Enum):
    """Guardrail intervention decision."""
    NO_INTERVENTION = "no_intervention"
    TARGETED_CONTEXT_REFRESH = "targeted_context_refresh"
    VERIFY_WITH_TOOL_REPLAY = "verify_with_tool_replay"
    VERIFY_AND_REPLAN = "verify_and_replan"


class RiskBand(enum.Enum):
    """Coarse failure risk classification."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class CapacityObservationInput:
    """Input for observing current turn pressure."""
    turn_index: int
    model: str
    action_count_this_turn: int
    tool_calls_recent_window: int
    unique_reference_ids_recent_window: int
    context_used_ratio: float


@dataclass
class DynamicSlackProfile:
    """Rolling slack profile metrics."""
    final_slack: float = 0.0
    min_slack: float = 0.0
    violation_ratio: float = 0.0
    slack_volatility: float = 0.0
    slack_drop: float = 0.0


@dataclass
class CapacitySnapshot:
    """Per-checkpoint capacity snapshot."""
    turn_index: int
    h_hat: float  # estimated context used (normalized 0-1)
    c_hat: float  # context budget scaled
    slack: float  # normalized slack = (budget - used) / budget
    profile: DynamicSlackProfile
    p_fail: float  # failure probability estimate
    risk_band: RiskBand
    severe: bool


@dataclass
class CapacityDecision:
    """Full controller decision with reason and cooldown."""
    action: GuardrailAction
    reason: str
    cooldown_blocked: bool = False


class CapacityControllerConfig:
    """Configuration for CapacityController."""

    def __init__(self) -> None:
        """Initialize with default thresholds."""
        self.enabled: bool = False
        self.low_risk_max: float = 0.50
        self.medium_risk_max: float = 0.62
        self.severe_min_slack: float = -0.25
        self.severe_violation_ratio: float = 0.40
        self.refresh_cooldown_turns: int = 6
        self.replan_cooldown_turns: int = 5
        self.max_replay_per_turn: int = 1
        self.min_turns_before_guardrail: int = 4
        self.profile_window: int = 8

        # Model-specific priors (failure probability scaling factors)
        self.model_priors: dict[str, float] = {
            "deepseek-chat": 3.8,
            "deepseek-reasoner": 4.1,
        }
        self.fallback_default: float = 3.8

    @staticmethod
    def from_app_config(config_dict: CapacityConfig) -> CapacityControllerConfig:
        """Build effective capacity config from app config dict."""
        out = CapacityControllerConfig()

        if config_dict.enabled is not None:
            out.enabled = config_dict.enabled
        if config_dict.low_risk_max is not None:
            out.low_risk_max = config_dict.low_risk_max
        if config_dict.medium_risk_max is not None:
            out.medium_risk_max = config_dict.medium_risk_max
        if config_dict.severe_min_slack is not None:
            out.severe_min_slack = config_dict.severe_min_slack
        if config_dict.severe_violation_ratio is not None:
            out.severe_violation_ratio = config_dict.severe_violation_ratio
        if config_dict.refresh_cooldown_turns is not None:
            out.refresh_cooldown_turns = config_dict.refresh_cooldown_turns
        if config_dict.replan_cooldown_turns is not None:
            out.replan_cooldown_turns = config_dict.replan_cooldown_turns
        if config_dict.max_replay_per_turn is not None:
            out.max_replay_per_turn = config_dict.max_replay_per_turn
        if config_dict.min_turns_before_guardrail is not None:
            out.min_turns_before_guardrail = config_dict.min_turns_before_guardrail
        if config_dict.profile_window is not None:
            out.profile_window = max(2, config_dict.profile_window)

        return out


@dataclass
class CapacityController:
    """Main capacity guardrail controller."""

    config: CapacityControllerConfig
    # Rolling history of slack values (for volatility tracking)
    slack_history: deque[float] = field(default_factory=lambda: deque(maxlen=8))
    # Last turn index where we emitted a guardrail decision
    last_guardrail_turn: int = 0
    # Cooldown state: which action was last applied
    last_action: GuardrailAction = GuardrailAction.NO_INTERVENTION
    # Number of consecutive turns without intervention (for cooldown)
    turns_since_action: int = 0

    def __post_init__(self) -> None:
        """Update maxlen of slack_history to match config."""
        self.slack_history = deque(maxlen=self.config.profile_window)

    def observe_pre_turn(self, obs: CapacityObservationInput) -> CapacitySnapshot | None:
        """Observe and snapshot capacity state before LLM request.

        Args:
            obs: Current observation input

        Returns:
            Capacity snapshot if observation was successful, None otherwise
        """
        if not self.config.enabled:
            return None

        # Normalize context usage to [0, 1]
        h_hat = min(1.0, max(0.0, obs.context_used_ratio))
        c_hat = 1.0  # Normalized budget

        # Calculate slack: (1 - used_ratio)
        slack = c_hat - h_hat

        # Track slack history for volatility
        self.slack_history.append(slack)

        # Calculate profile metrics from history
        profile = self._calculate_profile(self.slack_history)

        # Estimate failure probability using Poisson model
        # p_fail = 1 - exp(-λ * |slack|) when slack < 0
        prior = self.config.model_priors.get(
            obs.model, self.config.fallback_default
        )
        if slack < 0:
            import math

            p_fail = 1.0 - math.exp(-prior * abs(slack))
        else:
            p_fail = 0.0

        # Classify risk band
        risk_band = self._classify_risk(h_hat, profile)

        # Check if severe (high violation + negative slack)
        severe = (
            profile.violation_ratio > self.config.severe_violation_ratio
            and slack < self.config.severe_min_slack
        )

        snapshot = CapacitySnapshot(
            turn_index=obs.turn_index,
            h_hat=h_hat,
            c_hat=c_hat,
            slack=slack,
            profile=profile,
            p_fail=p_fail,
            risk_band=risk_band,
            severe=severe,
        )

        return snapshot

    def observe_post_tool(self, obs: CapacityObservationInput) -> CapacitySnapshot | None:
        """Observe capacity state after tool execution.

        For now, same as pre_turn. In full implementation, would incorporate
        tool error counts and adjust risk band accordingly.
        """
        return self.observe_pre_turn(obs)

    def decide(self, turn_index: int, snapshot: CapacitySnapshot | None) -> CapacityDecision:
        """Make guardrail decision based on snapshot.

        Args:
            turn_index: Current turn number
            snapshot: Capacity snapshot from observe_*

        Returns:
            Decision with action, reason, and cooldown status
        """
        if snapshot is None or not self.config.enabled:
            return CapacityDecision(
                action=GuardrailAction.NO_INTERVENTION,
                reason="capacity monitoring disabled",
            )

        # Enforce min turns before guardrail activates
        if turn_index < self.config.min_turns_before_guardrail:
            return CapacityDecision(
                action=GuardrailAction.NO_INTERVENTION,
                reason=f"min_turns_before_guardrail={self.config.min_turns_before_guardrail}",
            )

        # Check cooldown
        cooldown_blocked = False
        if self.last_action == GuardrailAction.TARGETED_CONTEXT_REFRESH:
            if self.turns_since_action < self.config.refresh_cooldown_turns:
                cooldown_blocked = True
        elif self.last_action == GuardrailAction.VERIFY_AND_REPLAN:
            if self.turns_since_action < self.config.replan_cooldown_turns:
                cooldown_blocked = True

        # If in cooldown, no intervention
        if cooldown_blocked:
            self.turns_since_action += 1
            return CapacityDecision(
                action=GuardrailAction.NO_INTERVENTION,
                reason=f"cooldown_blocked (turns_since={self.turns_since_action})",
                cooldown_blocked=True,
            )

        # Decision tree based on risk band and severity
        if snapshot.severe:
            action = GuardrailAction.VERIFY_AND_REPLAN
            reason = "severe: high violation ratio + negative slack"
        elif snapshot.risk_band == RiskBand.HIGH:
            if snapshot.slack < self.config.severe_min_slack:
                action = GuardrailAction.VERIFY_AND_REPLAN
                reason = "high risk + severe slack"
            else:
                action = GuardrailAction.VERIFY_WITH_TOOL_REPLAY
                reason = "high risk: tool replay verification"
        elif snapshot.risk_band == RiskBand.MEDIUM:
            action = GuardrailAction.TARGETED_CONTEXT_REFRESH
            reason = "medium risk: trigger context compaction"
        else:
            action = GuardrailAction.NO_INTERVENTION
            reason = "low risk: no intervention needed"

        # Update state
        self.last_action = action
        self.turns_since_action = 0

        return CapacityDecision(
            action=action,
            reason=reason,
            cooldown_blocked=False,
        )

    def _calculate_profile(
        self, history: deque[float]
    ) -> DynamicSlackProfile:
        """Calculate dynamic slack profile from history."""
        if not history:
            return DynamicSlackProfile()

        history_list = list(history)
        final_slack = history_list[-1] if history_list else 0.0
        min_slack = min(history_list)

        # Violation ratio: how many history points are < 0
        violations = sum(1 for s in history_list if s < 0)
        violation_ratio = violations / len(history_list) if history_list else 0.0

        # Slack volatility: std dev of history
        if len(history_list) > 1:
            mean = sum(history_list) / len(history_list)
            variance = sum((x - mean) ** 2 for x in history_list) / len(history_list)
            import math

            slack_volatility = math.sqrt(variance)
        else:
            slack_volatility = 0.0

        # Slack drop: steepest negative change in recent window
        slack_drop = 0.0
        for i in range(1, len(history_list)):
            drop = history_list[i - 1] - history_list[i]
            if drop > slack_drop:
                slack_drop = drop

        return DynamicSlackProfile(
            final_slack=final_slack,
            min_slack=min_slack,
            violation_ratio=violation_ratio,
            slack_volatility=slack_volatility,
            slack_drop=slack_drop,
        )

    def _classify_risk(self, h_hat: float, profile: DynamicSlackProfile) -> RiskBand:
        """Classify risk band based on context usage and profile."""
        if h_hat > self.config.medium_risk_max:
            return RiskBand.HIGH
        elif h_hat > self.config.low_risk_max:
            return RiskBand.MEDIUM
        else:
            return RiskBand.LOW


# Capacity checkpoint flow logic for the Engine.
# Implements the 3 checkpoint entry points that route to guardrail actions.
# Full tool-replay and canonical-state-rebuild logic is deferred (P1).



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

    from deepseek_tui.engine.context import estimate_tokens

    text_blob = "".join(
        str(getattr(b, attr, ""))
        for msg in messages
        for b in msg.content
        for attr in ("text", "content", "input")
        if hasattr(b, attr)
    )
    estimated_tokens = max(1, estimate_tokens(text_blob))
    # Use the model's actual context window, not a hardcoded 128K. The old
    # constant made context_used_ratio ~8x too low on V4 (1M window), so
    # the controller never saw "high pressure" even near the real limit.
    from deepseek_tui.config.providers import context_window_for_model

    context_limit = context_window_for_model(model)
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
) -> tuple[CapacityDecision, bool, str | None]:
    """Pre-request checkpoint: if TARGETED_CONTEXT_REFRESH, trigger compaction.

    Returns ``(decision, compacted, bridge_text)``. The bridge is already
    inside ``messages``; callers must not inject it into the system prompt.
    """
    obs = build_observation(turn_index, model, messages)
    snapshot: CapacitySnapshot | None = controller.observe_pre_turn(obs)
    decision = controller.decide(turn_index, snapshot)

    if decision.action == GuardrailAction.TARGETED_CONTEXT_REFRESH:
        if compact_fn is not None and callable(compact_fn):
            try:
                result = await compact_fn(messages)
                summary: str | None = None
                if isinstance(result, tuple):
                    messages[:] = result[0]
                    summary = result[1]
                else:
                    messages[:] = result
                logger.info("capacity: pre-request compaction triggered (turn %d)", turn_index)
                return decision, True, summary
            except Exception:
                logger.warning("capacity: pre-request compaction failed", exc_info=True)

    return decision, False, None


async def run_post_tool_checkpoint(
    controller: CapacityController,
    turn_index: int,
    model: str,
    messages: list[Message],
) -> CapacityDecision:
    """Post-tool checkpoint: observe and decide after tool execution.

    Full VERIFY_WITH_TOOL_REPLAY (re-running read-only tools) is deferred.
    For now, logs the decision and returns it for caller awareness.
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


# Context compaction for long conversations.


from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.seam import truncate_chars as _truncate_chars
from deepseek_tui.protocol.messages import Message

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
L0_HARD_CLEAR_PLACEHOLDER = "[Tool result omitted — too old]"


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
) -> bool:
    """Determine if messages should be rewrite-compacted.

    Primary signal is context-used *ratio* vs ``config.rewrite_ratio``
    (default 0.75). Below ``auto_floor_ratio`` (default 0.20) auto rewrite
    never fires — soft seams / L0 handle that band.
    """
    if not config.enabled or not messages:
        return False

    from deepseek_tui.engine.context_pressure import measure_context_pressure

    pressure = measure_context_pressure(
        model or config.model or "deepseek-chat",
        messages,
        real_input_tokens=real_input_tokens,
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

    from deepseek_tui.engine.prompts import COMPACT_TEMPLATE
    from deepseek_tui.protocol.messages import MessageRequest

    handoff_contract = COMPACT_TEMPLATE().strip()
    system_prompt = (
        "You write structured compaction handoffs for a coding agent. "
        "Follow the contract exactly. Prefer structure and continuity over "
        "prose polish. Do not call tools."
    )
    previous_block = ""
    if previous_summary and previous_summary.strip():
        previous_block = (
            "Previous compaction summary (authoritative; PRESERVE still-true "
            "facts, ADD new progress, UPDATE Next step):\n"
            f"<previous-summary>\n{previous_summary.strip()}\n</previous-summary>\n\n"
        )
    user_prompt = (
        f"{handoff_contract}\n\n"
        f"Keep the filled handoff under {limits.word_limit} words when possible; "
        "structure and required headings take priority over the word limit.\n\n"
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
            if age >= cfg.hard_clear_age_turns:
                if content != L0_HARD_CLEAR_PLACEHOLDER:
                    new_blocks.append(
                        block.model_copy(update={"content": L0_HARD_CLEAR_PLACEHOLDER})
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
) -> bool:
    """True when context ratio warrants mid-session tool pruning."""
    cfg = config or CompactionConfig()
    if not cfg.l0_prune_enabled:
        return False
    from deepseek_tui.engine.context_pressure import measure_context_pressure

    pressure = measure_context_pressure(
        model, messages, real_input_tokens=real_input_tokens
    )
    return pressure.ratio >= cfg.l0_prune_ratio
