"""Capacity control — token budget, rate limiting, compaction.

Consolidates capacity.py, capacity_flow.py, compaction.py.
"""

from __future__ import annotations



# ======================================================================
# From capacity.py
# ======================================================================

"""Capacity-aware guardrail controller for context pressure management.

Mirrors `crates/tui/src/core/capacity.rs:1-784`
         + `crates/tui/src/core/engine/capacity_flow.rs:1-975`
"""


import enum
from collections import deque
from dataclasses import dataclass, field

from deepseek_tui.config.models import CapacityConfig


class GuardrailAction(enum.Enum):
    """Guardrail intervention decision (mirrors Rust GuardrailAction)."""
    NO_INTERVENTION = "no_intervention"
    TARGETED_CONTEXT_REFRESH = "targeted_context_refresh"
    VERIFY_WITH_TOOL_REPLAY = "verify_with_tool_replay"
    VERIFY_AND_REPLAN = "verify_and_replan"


class RiskBand(enum.Enum):
    """Coarse failure risk classification (mirrors Rust RiskBand)."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class CapacityObservationInput:
    """Input for observing current turn pressure (mirrors Rust struct)."""
    turn_index: int
    model: str
    action_count_this_turn: int
    tool_calls_recent_window: int
    unique_reference_ids_recent_window: int
    context_used_ratio: float


@dataclass
class DynamicSlackProfile:
    """Rolling slack profile metrics (mirrors Rust struct)."""
    final_slack: float = 0.0
    min_slack: float = 0.0
    violation_ratio: float = 0.0
    slack_volatility: float = 0.0
    slack_drop: float = 0.0


@dataclass
class CapacitySnapshot:
    """Per-checkpoint capacity snapshot (mirrors Rust struct)."""
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
    """Full controller decision with reason and cooldown (mirrors Rust struct)."""
    action: GuardrailAction
    reason: str
    cooldown_blocked: bool = False


class CapacityControllerConfig:
    """Configuration for CapacityController (mirrors Rust CapacityControllerConfig)."""

    def __init__(self) -> None:
        """Initialize with Rust defaults."""
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
        """Build effective capacity config from app config dict (mirrors Rust method)."""
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
    """Main capacity guardrail controller (mirrors Rust CapacityController impl)."""

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


# ======================================================================
# From capacity_flow.py
# ======================================================================

"""Capacity checkpoint flow logic for the Engine.

Simplified port of `crates/tui/src/core/engine/capacity_flow.rs:1-975`.
Implements the 3 checkpoint entry points that route to guardrail actions.
Full tool-replay and canonical-state-rebuild logic is deferred (P1).
"""


import logging
from typing import TYPE_CHECKING


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


# ======================================================================
# From compaction.py
# ======================================================================

"""Context compaction for long conversations.

Mirrors `crates/tui/src/compaction.rs:1-2008`
"""


import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.seam import truncate_chars as _truncate_chars
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

# Rust v0.8.11: hard floor for automatic compaction. Below this,
# should_compact() returns false regardless of config. Tuned for V4's
# 1M window with real-input-token semantics (last_real_input_tokens):
# 200K = 20% of window. Below this the prefix cache is still healthy
# (hit rate >85% in production logs) and compaction's cache-destroying
# cost outweighs its benefit. Manual /compact bypasses this floor.
MINIMUM_AUTO_COMPACTION_TOKENS = 200_000


@dataclass
class CompactionConfig:
    """Configuration for conversation compaction behavior.

    Mirrors Rust CompactionConfig (compaction.rs:29). Key difference from
    prior Python: ``model`` defaults to None which means "use the same
    model as the main conversation" (Rust behavior). The old default of
    "deepseek-chat" silently routed compaction to v4-flash.
    """
    enabled: bool = True
    token_threshold: int = 400_000  # Trigger compaction at ~40% of V4 1M window
    message_threshold: int = 500  # Rust uses token-based, not message-based
    model: str | None = None  # None = inherit main model (Rust behavior)
    cache_summary: bool = True
    auto_floor_tokens: int = MINIMUM_AUTO_COMPACTION_TOKENS


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
            word_limit=900,
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

    # Always pin last KEEP_RECENT_MESSAGES messages. Extend the window
    # backwards while it would start on a tool-result message: the API
    # requires every tool message to directly follow the assistant message
    # carrying the matching tool_calls, so summarizing that parent away
    # would produce an illegal (orphaned) sequence.
    start = max(0, len(messages) - KEEP_RECENT_MESSAGES)
    from deepseek_tui.protocol.messages import Role

    while start > 0 and messages[start].role == Role.TOOL:
        start -= 1
    for i in range(start, len(messages)):
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
    *,
    real_input_tokens: int = 0,
) -> bool:
    """Determine if messages should be compacted.

    Args:
        messages: Current message history
        config: Compaction configuration
        pinned_indices: Explicitly pinned message indices
        real_input_tokens: Last real ``input_tokens`` reported by the
            provider (from the previous turn's final stream). When > 0,
            used as the primary pressure signal — it is the exact billed
            input, zero estimation error. When 0 (first turn, or provider
            didn't report), falls back to the char-based estimate.

    Returns:
        True if compaction should trigger
    """
    if not config.enabled or not messages:
        return False

    # Prefer the provider's real input_tokens when available. The
    # char-based estimate undercounts by ~6x in practice (it omits system
    # prompt, tool schemas, framing, reasoning), which made the old
    # auto-floor effectively unreachable. The real number has no such bias.
    if real_input_tokens > 0:
        if real_input_tokens < config.auto_floor_tokens:
            return False
        # Real input already accounts for system prompt, tools, framing —
        # no need to add pinned_tokens adjustment (that was compensating
        # for the estimate's blind spots). Compare directly.
        return real_input_tokens >= config.token_threshold

    # Fallback: char-based estimate (first turn, or provider reported no usage).
    # Rust v0.8.11: hard floor — don't auto-compact below this token count.
    # V4 prefix-cache economics: compaction rewrites the stable prefix,
    # destroying KV cache. At low token counts the cache is healthy and
    # compaction's cost dwarfs its benefit.
    total_tokens = sum(
        _estimate_tokens_for_message(m, include_thinking=False)
        for m in messages
    )
    if total_tokens < config.auto_floor_tokens:
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
    model_override: str | None = None,
) -> CompactionResult:
    """Compact messages with retry and backoff for transient errors.

    Args:
        client: LLM client for summary generation
        messages: Message history to compact
        config: Compaction configuration
        workspace: Workspace directory (for path normalization)
        pinned_indices: Explicitly pinned message indices
        working_set_paths: Working set file paths for reference
        model_override: Model to use for summary (overrides config.model)

    Returns:
        Compaction result with compacted messages and summary
    """
    if not messages or not config.enabled:
        return CompactionResult(messages=messages)

    # # 最近4条消息 plan 不动，其余送去摘要
    plan = plan_compaction(messages, pinned_indices)

    if not plan.summarize_indices:
        return CompactionResult(messages=messages)

    # Collect messages to summarize
    messages_to_summarize = [messages[i] for i in plan.summarize_indices if i < len(messages)]

    if len(messages_to_summarize) < MIN_SUMMARIZE_MESSAGES:
        return CompactionResult(messages=messages)

    # Resolve model: explicit override > config.model > fallback
    effective_model = model_override or config.model or "deepseek-chat"

    # Generate summary with retries
    max_retries = 3
    for attempt in range(max_retries):
        try:
            summary = await _create_summary(client, messages_to_summarize, effective_model)
            if not summary:
                # Replacing history with an empty summary would silently
                # delete it. Treat as a failed attempt (retried, then the
                # original messages are returned unchanged).
                raise ValueError("compaction summary came back empty")

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
                success=True,
            )

        except Exception as exc:
            logger.warning(
                "compact_attempt_failed attempt=%d/%d error=%s",
                attempt + 1, max_retries, exc,
                exc_info=True,
            )
            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s
                delay = (2 ** attempt)
                await asyncio.sleep(delay)
                continue
            # Final attempt failed, return original messages
            logger.warning(
                "compact_all_retries_exhausted retries=%d",
                max_retries,
                exc_info=True,
            )
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
    from deepseek_tui.protocol.messages import MessageRequest

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
