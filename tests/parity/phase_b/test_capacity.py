"""Parity tests for engine/capacity.

Mirror of Rust `crates/tui/src/core/capacity.rs` capacity controller tests.
"""

from __future__ import annotations

from deepseek_tui.config.models import CapacityConfig
from deepseek_tui.engine.capacity import (
    CapacityController,
    CapacityControllerConfig,
    CapacityObservationInput,
    CapacitySnapshot,
    DynamicSlackProfile,
    GuardrailAction,
    RiskBand,
)


class TestCapacityConfig:
    """Tests for CapacityControllerConfig."""

    def test_config_defaults(self) -> None:
        """Config should have expected defaults (mirrors Rust defaults)."""
        config = CapacityControllerConfig()

        assert config.enabled is True
        assert config.low_risk_max == 0.50
        assert config.medium_risk_max == 0.62
        assert config.severe_min_slack == -0.25
        assert config.severe_violation_ratio == 0.40
        assert config.refresh_cooldown_turns == 6
        assert config.replan_cooldown_turns == 5
        assert config.min_turns_before_guardrail == 4
        assert config.profile_window == 8

    def test_config_from_app_config(self) -> None:
        """Config should load from CapacityConfig dict."""
        app_config = CapacityConfig(
            enabled=False,
            low_risk_max=0.45,
            profile_window=10,
        )
        config = CapacityControllerConfig.from_app_config(app_config)

        assert config.enabled is False
        assert config.low_risk_max == 0.45
        assert config.profile_window == 10
        assert config.medium_risk_max == 0.62  # unchanged


class TestGuardrailAction:
    """Tests for GuardrailAction enum."""

    def test_guardrail_actions_exist(self) -> None:
        """All four guardrail actions should exist."""
        assert GuardrailAction.NO_INTERVENTION.value == "no_intervention"
        assert GuardrailAction.TARGETED_CONTEXT_REFRESH.value == "targeted_context_refresh"
        assert GuardrailAction.VERIFY_WITH_TOOL_REPLAY.value == "verify_with_tool_replay"
        assert GuardrailAction.VERIFY_AND_REPLAN.value == "verify_and_replan"


class TestRiskBand:
    """Tests for RiskBand enum."""

    def test_risk_bands_exist(self) -> None:
        """All three risk bands should exist."""
        assert RiskBand.LOW.value == "low"
        assert RiskBand.MEDIUM.value == "medium"
        assert RiskBand.HIGH.value == "high"


class TestCapacityObservation:
    """Tests for capacity observation and snapshots."""

    def test_observation_input_creation(self) -> None:
        """Observation input should construct properly."""
        obs = CapacityObservationInput(
            turn_index=5,
            model="deepseek-chat",
            action_count_this_turn=3,
            tool_calls_recent_window=10,
            unique_reference_ids_recent_window=2,
            context_used_ratio=0.75,
        )

        assert obs.turn_index == 5
        assert obs.context_used_ratio == 0.75

    def test_capacity_controller_observe_pre_turn_disabled(self) -> None:
        """When disabled, observe should return None."""
        config = CapacityControllerConfig()
        config.enabled = False
        controller = CapacityController(config=config)

        obs = CapacityObservationInput(
            turn_index=1,
            model="deepseek-chat",
            action_count_this_turn=0,
            tool_calls_recent_window=0,
            unique_reference_ids_recent_window=0,
            context_used_ratio=0.5,
        )

        snapshot = controller.observe_pre_turn(obs)
        assert snapshot is None

    def test_capacity_controller_observe_pre_turn_low_usage(self) -> None:
        """Low context usage should produce LOW risk band."""
        config = CapacityControllerConfig()
        controller = CapacityController(config=config)

        obs = CapacityObservationInput(
            turn_index=1,
            model="deepseek-chat",
            action_count_this_turn=0,
            tool_calls_recent_window=0,
            unique_reference_ids_recent_window=0,
            context_used_ratio=0.30,
        )

        snapshot = controller.observe_pre_turn(obs)
        assert snapshot is not None
        assert snapshot.risk_band == RiskBand.LOW
        assert snapshot.h_hat == 0.30
        assert snapshot.slack == 0.70

    def test_capacity_controller_observe_pre_turn_medium_usage(self) -> None:
        """Medium context usage should produce MEDIUM risk band."""
        config = CapacityControllerConfig()
        controller = CapacityController(config=config)

        obs = CapacityObservationInput(
            turn_index=2,
            model="deepseek-chat",
            action_count_this_turn=1,
            tool_calls_recent_window=2,
            unique_reference_ids_recent_window=1,
            context_used_ratio=0.55,
        )

        snapshot = controller.observe_pre_turn(obs)
        assert snapshot is not None
        assert snapshot.risk_band == RiskBand.MEDIUM
        # slack = c_hat - h_hat = 1.0 - 0.55 = 0.45
        assert abs(snapshot.slack - 0.45) < 0.01

    def test_capacity_controller_observe_pre_turn_high_usage(self) -> None:
        """High context usage should produce HIGH risk band."""
        config = CapacityControllerConfig()
        controller = CapacityController(config=config)

        obs = CapacityObservationInput(
            turn_index=3,
            model="deepseek-chat",
            action_count_this_turn=2,
            tool_calls_recent_window=5,
            unique_reference_ids_recent_window=2,
            context_used_ratio=0.65,
        )

        snapshot = controller.observe_pre_turn(obs)
        assert snapshot is not None
        assert snapshot.risk_band == RiskBand.HIGH

    def test_capacity_controller_failure_probability(self) -> None:
        """Failure probability should increase as slack becomes negative."""
        config = CapacityControllerConfig()
        controller = CapacityController(config=config)

        # Negative slack (context_used_ratio clamped to 1.0, so slack = 0)
        obs = CapacityObservationInput(
            turn_index=1,
            model="deepseek-chat",
            action_count_this_turn=0,
            tool_calls_recent_window=0,
            unique_reference_ids_recent_window=0,
            context_used_ratio=1.1,  # Clamped to 1.0
        )

        snapshot = controller.observe_pre_turn(obs)
        assert snapshot is not None
        # When h_hat=1.0, slack=0, so p_fail=0 (no negative slack)
        assert snapshot.p_fail == 0.0
        assert snapshot.h_hat == 1.0

        # Positive slack
        obs2 = CapacityObservationInput(
            turn_index=2,
            model="deepseek-chat",
            action_count_this_turn=0,
            tool_calls_recent_window=0,
            unique_reference_ids_recent_window=0,
            context_used_ratio=0.5,
        )

        snapshot2 = controller.observe_pre_turn(obs2)
        assert snapshot2 is not None
        assert snapshot2.p_fail == 0.0


class TestCapacityDecision:
    """Tests for capacity decision making."""

    def test_decide_no_intervention_when_disabled(self) -> None:
        """When disabled, decide should return NO_INTERVENTION."""
        config = CapacityControllerConfig()
        config.enabled = False
        controller = CapacityController(config=config)

        decision = controller.decide(5, None)
        assert decision.action == GuardrailAction.NO_INTERVENTION

    def test_decide_no_intervention_early_turn(self) -> None:
        """Decision should be NO_INTERVENTION before min_turns_before_guardrail."""
        config = CapacityControllerConfig()
        config.min_turns_before_guardrail = 4
        controller = CapacityController(config=config)

        snapshot = CapacitySnapshot(
            turn_index=2,
            h_hat=0.8,
            c_hat=1.0,
            slack=-0.2,
            profile=DynamicSlackProfile(),
            p_fail=0.5,
            risk_band=RiskBand.HIGH,
            severe=True,
        )

        decision = controller.decide(2, snapshot)
        assert decision.action == GuardrailAction.NO_INTERVENTION

    def test_decide_low_risk(self) -> None:
        """Low risk band should produce NO_INTERVENTION."""
        config = CapacityControllerConfig()
        controller = CapacityController(config=config)

        snapshot = CapacitySnapshot(
            turn_index=5,
            h_hat=0.30,
            c_hat=1.0,
            slack=0.70,
            profile=DynamicSlackProfile(),
            p_fail=0.0,
            risk_band=RiskBand.LOW,
            severe=False,
        )

        decision = controller.decide(5, snapshot)
        assert decision.action == GuardrailAction.NO_INTERVENTION

    def test_decide_medium_risk(self) -> None:
        """Medium risk band should trigger TARGETED_CONTEXT_REFRESH."""
        config = CapacityControllerConfig()
        controller = CapacityController(config=config)

        snapshot = CapacitySnapshot(
            turn_index=5,
            h_hat=0.55,
            c_hat=1.0,
            slack=0.45,
            profile=DynamicSlackProfile(),
            p_fail=0.1,
            risk_band=RiskBand.MEDIUM,
            severe=False,
        )

        decision = controller.decide(5, snapshot)
        assert decision.action == GuardrailAction.TARGETED_CONTEXT_REFRESH

    def test_decide_high_risk(self) -> None:
        """High risk with positive slack should trigger VERIFY_WITH_TOOL_REPLAY."""
        config = CapacityControllerConfig()
        controller = CapacityController(config=config)

        snapshot = CapacitySnapshot(
            turn_index=5,
            h_hat=0.65,
            c_hat=1.0,
            slack=0.35,
            profile=DynamicSlackProfile(),
            p_fail=0.3,
            risk_band=RiskBand.HIGH,
            severe=False,
        )

        decision = controller.decide(5, snapshot)
        assert decision.action == GuardrailAction.VERIFY_WITH_TOOL_REPLAY

    def test_decide_severe(self) -> None:
        """Severe condition should trigger VERIFY_AND_REPLAN."""
        config = CapacityControllerConfig()
        controller = CapacityController(config=config)

        snapshot = CapacitySnapshot(
            turn_index=5,
            h_hat=0.9,
            c_hat=1.0,
            slack=-0.3,
            profile=DynamicSlackProfile(violation_ratio=0.5),
            p_fail=0.8,
            risk_band=RiskBand.HIGH,
            severe=True,
        )

        decision = controller.decide(5, snapshot)
        assert decision.action == GuardrailAction.VERIFY_AND_REPLAN

    def test_decide_refresh_cooldown(self) -> None:
        """After TARGETED_CONTEXT_REFRESH, cooldown should block next decision."""
        config = CapacityControllerConfig()
        config.refresh_cooldown_turns = 3
        controller = CapacityController(config=config)

        # First decision triggers refresh
        snapshot1 = CapacitySnapshot(
            turn_index=5,
            h_hat=0.55,
            c_hat=1.0,
            slack=0.45,
            profile=DynamicSlackProfile(),
            p_fail=0.1,
            risk_band=RiskBand.MEDIUM,
            severe=False,
        )
        decision1 = controller.decide(5, snapshot1)
        assert decision1.action == GuardrailAction.TARGETED_CONTEXT_REFRESH

        # Immediately next turn: should be blocked by cooldown
        snapshot2 = CapacitySnapshot(
            turn_index=6,
            h_hat=0.55,
            c_hat=1.0,
            slack=0.45,
            profile=DynamicSlackProfile(),
            p_fail=0.1,
            risk_band=RiskBand.MEDIUM,
            severe=False,
        )
        decision2 = controller.decide(6, snapshot2)
        assert decision2.action == GuardrailAction.NO_INTERVENTION
        assert decision2.cooldown_blocked is True

        # After cooldown expires: should allow decision again
        for i in range(7, 9):  # Skip to turn 9
            snapshot = CapacitySnapshot(
                turn_index=i,
                h_hat=0.30,
                c_hat=1.0,
                slack=0.70,
                profile=DynamicSlackProfile(),
                p_fail=0.0,
                risk_band=RiskBand.LOW,
                severe=False,
            )
            controller.decide(i, snapshot)

        snapshot_after_cooldown = CapacitySnapshot(
            turn_index=9,
            h_hat=0.55,
            c_hat=1.0,
            slack=0.45,
            profile=DynamicSlackProfile(),
            p_fail=0.1,
            risk_band=RiskBand.MEDIUM,
            severe=False,
        )
        decision_after = controller.decide(9, snapshot_after_cooldown)
        assert decision_after.cooldown_blocked is False
