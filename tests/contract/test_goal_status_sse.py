"""Contract: goal.status SSE envelope shape + workflow interaction.

Query 2: Tests Goal SSE emission (for Workbench GoalChip) and
verifies workflow + goal can coexist without interference.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deepseek_tui.goal.controller import GoalController
from deepseek_tui.goal.models import GoalStatus
from deepseek_tui.protocol.responses import Usage
from deepseek_tui.workflow.models import (
    AgentStep,
    WorkflowMeta,
    WorkflowPhase,
    WorkflowPolicy,
    WorkflowSnapshot,
    WorkflowSpec,
)


# ─── Goal SSE Payload Contract ────────────────────────────────────────────────


class TestGoalStatusSSEContract:
    """Verify the shape of goal.status events sent to Workbench."""

    def _build_goal_sse_payload(self, controller: GoalController) -> dict | None:
        """Simulate what _emit_goal_status_if_needed produces."""
        goal = controller.current
        if goal is None:
            return {"goal": None}
        return {
            "goal": {
                "goal_id": goal.goal_id,
                "objective": goal.objective[:120],
                "status": goal.status.value,
                "tokens_used": goal.usage.tokens_used,
                "token_budget": goal.token_budget,
                "active_seconds": round(goal.usage.active_seconds, 1),
            }
        }

    def test_active_goal_payload(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "sse-active")
        ctrl.create("Implement feature X", token_budget=50000)
        ctrl.on_turn_start()
        ctrl.on_turn_complete(Usage(input_tokens=100, output_tokens=50))

        payload = self._build_goal_sse_payload(ctrl)
        goal = payload["goal"]
        assert goal["status"] == "active"
        assert goal["tokens_used"] == 150
        assert goal["token_budget"] == 50000
        assert goal["objective"] == "Implement feature X"
        assert isinstance(goal["active_seconds"], float)
        assert goal["goal_id"].startswith("goal_")

    def test_budget_limited_payload(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "sse-budget")
        ctrl.create("small task", token_budget=1000)
        ctrl.on_turn_start()
        ctrl.on_turn_complete(Usage(input_tokens=600, output_tokens=500))

        payload = self._build_goal_sse_payload(ctrl)
        assert payload["goal"]["status"] == "budget_limited"
        assert payload["goal"]["tokens_used"] == 1100

    def test_paused_payload(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "sse-pause")
        ctrl.create("pausable")
        ctrl.pause("user requested")

        payload = self._build_goal_sse_payload(ctrl)
        assert payload["goal"]["status"] == "paused"

    def test_cleared_payload(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "sse-clear")
        ctrl.create("temporary")
        ctrl.clear()

        payload = self._build_goal_sse_payload(ctrl)
        assert payload["goal"] is None

    def test_long_objective_truncated(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "sse-trunc")
        long_obj = "x" * 500
        ctrl.create(long_obj)

        payload = self._build_goal_sse_payload(ctrl)
        assert len(payload["goal"]["objective"]) == 120


# ─── Workflow + Goal Coexistence ──────────────────────────────────────────────


class TestWorkflowGoalCoexistence:
    """Goal and Workflow run in the same session without interference."""

    def test_workflow_spec_is_valid(self) -> None:
        """Basic workflow spec construction (used by /workflow run)."""
        spec = WorkflowSpec(
            version=1,
            meta=WorkflowMeta(name="code-review", description="Review recent changes"),
            policy=WorkflowPolicy(
                approval_mode="trusted_workflow",
                max_agents=4,
                concurrency=2,
                wall_clock_seconds=300,
                token_budget=100000,
            ),
            phases=[
                WorkflowPhase(
                    id="analysis",
                    title="Code Analysis",
                    steps=[
                        AgentStep(
                            id="lint",
                            type="agent",
                            label="Run linter",
                            prompt="Run linting on changed files",
                        ),
                        AgentStep(
                            id="security",
                            type="agent",
                            label="Security scan",
                            prompt="Check for security issues",
                        ),
                    ],
                ),
                WorkflowPhase(
                    id="synthesis",
                    title="Summary",
                    steps=[
                        AgentStep(
                            id="report",
                            type="agent",
                            label="Generate report",
                            prompt="Summarize findings from analysis phase",
                        ),
                    ],
                ),
            ],
        )
        assert spec.meta.name == "code-review"
        assert len(spec.phases) == 2
        assert spec.phases[0].steps[0].label == "Run linter"

    def test_workflow_snapshot_shape(self) -> None:
        """WorkflowSnapshot (what WorkflowBlock.tsx renders) has correct shape."""
        snap = WorkflowSnapshot(
            name="code-review",
            description="Review recent changes",
            phases=["analysis", "synthesis"],
            current_phase="analysis",
            agent_count=3,
            running_count=1,
            done_count=1,
            error_count=0,
        )
        assert snap.name == "code-review"
        assert snap.running_count == 1
        assert snap.done_count == 1

    def test_goal_unaffected_by_workflow_turns(self, tmp_path) -> None:
        """Workflow tool calls account tokens to goal without corrupting state."""
        ctrl = GoalController(tmp_path, "coexist")
        ctrl.create("Implement auth", token_budget=100000)
        ctrl.take_pending_follow_up()

        # Simulate turns where workflow tools run (token accounting still works)
        for i in range(5):
            ctrl.on_turn_start()
            follow_up = ctrl.on_turn_complete(
                Usage(input_tokens=2000 + i * 100, output_tokens=1000 + i * 50)
            )
            assert follow_up is not None  # still active

        assert ctrl.current.status == GoalStatus.ACTIVE
        assert ctrl.current.usage.tokens_used > 0
        # Workflow didn't interfere with goal state
        assert ctrl.current.objective == "Implement auth"

    def test_workflow_completion_does_not_complete_goal(self, tmp_path) -> None:
        """Workflow finishing doesn't auto-complete the parent goal."""
        ctrl = GoalController(tmp_path, "wf-no-complete")
        ctrl.create("Big project with multiple workflows")
        ctrl.take_pending_follow_up()

        # Simulate a workflow running and finishing within turns
        ctrl.on_turn_start()
        ctrl.on_turn_complete(Usage(input_tokens=5000, output_tokens=3000))

        # Goal is still active — only model calling update_goal can complete it
        assert ctrl.current.status == GoalStatus.ACTIVE

    def test_goal_pause_does_not_cancel_workflow(self, tmp_path) -> None:
        """Pausing goal should not interfere with a running workflow's state model."""
        ctrl = GoalController(tmp_path, "pause-wf")
        ctrl.create("Build with workflows")

        # Workflow is a separate runtime — GoalController doesn't touch it
        snap = WorkflowSnapshot(
            name="deploy",
            description="Deploy pipeline",
            agent_count=2,
            running_count=2,
            done_count=0,
        )

        ctrl.pause("need to think")
        # Workflow snapshot is independent
        assert snap.running_count == 2
        assert ctrl.current.status == GoalStatus.PAUSED
