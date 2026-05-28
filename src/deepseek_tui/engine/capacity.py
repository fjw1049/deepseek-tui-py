"""Capacity-aware guardrail controller for context pressure management.

Mirrors `crates/tui/src/core/capacity.rs:1-784`
         + `crates/tui/src/core/engine/capacity_flow.rs:1-975`
"""

from __future__ import annotations

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
