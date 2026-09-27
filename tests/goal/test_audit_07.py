"""Behavioral regressions for the systematic Goal audit."""

from unittest.mock import patch

import pytest

from deepseek_tui.goal.commands import parse_goal_command
from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.types import GoalError, GoalStatus
from deepseek_tui.goal.workspace import workspace_digest


def complete(service):
    service.record_tool_result(
        "check", "exec_shell", {"command": "pytest regression.py"}, success=True, output="1 passed"
    )
    service.mark_complete(
        "Checked",
        evidence=["check"],
        audit={
            "checks": [
                {
                    "requirement_id": r["id"],
                    "explanation": "Regression passed",
                    "evidence": ["check"],
                }
                for r in service.snapshot().requirements
            ]
        },
    )


@pytest.mark.parametrize(
    "raw",
    [
        "next manage delete ²",
        "next manage move 1 ²",
        "budget tokens " + "9" * 5000,
        "budget tokens ０",
        "next manage delete 0",
    ],
)
def test_invalid_numeric_input_returns_error(raw):
    assert parse_goal_command(raw).kind == "error"


def test_executable_mode_changes_fingerprint(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o644)
    before = workspace_digest(tmp_path)
    script.chmod(0o755)
    assert workspace_digest(tmp_path) != before


def test_snapshot_dump_and_restore_do_not_share_audit_objects():
    service = GoalService()
    service.create("Verify regression")
    complete(service)
    snap = service.snapshot()
    snap.completion_audit["checks"][0]["explanation"] = "modified"
    dumped = service.dump()
    restored = GoalService()
    restored.restore(dumped.goal, dumped.queue)
    dumped.goal["completion_audit"]["checks"][0]["explanation"] = "also modified"
    assert service.snapshot().completion_audit["checks"][0]["explanation"] == "Regression passed"
    assert restored.snapshot().completion_audit["checks"][0]["explanation"] == "Regression passed"


@pytest.mark.parametrize("phase", ["completed", "created", "started"])
def test_promotion_crash_points_resume_without_duplicate(phase):
    service = GoalService()
    service.create("first")
    item = service.enqueue("next")
    complete(service)
    if phase != "completed":
        service.create(item.objective, queue_item_id=item.item_id)
    if phase == "started":
        service.on_turn_started()
    prior_id = service.snapshot().goal_id
    dumped = service.dump()
    restored = GoalService()
    restored.restore(dumped.goal, dumped.queue)
    assert not restored.peek_continuation().should_continue
    snapshot, decision = restored.resume()
    assert decision.should_continue
    assert snapshot.objective == "next"
    if phase != "completed":
        assert snapshot.goal_id == prior_id
    restored.on_turn_started()
    assert restored.queue_items() == []
    restored.acknowledge_promoted(item.item_id)
    assert restored.queue_items() == []


def test_environment_probe_cannot_complete_goal():
    service = GoalService()
    service.create("Fix checkout and pass regression tests")
    service.record_tool_result("pwd", "exec_shell", {"command": "pwd"}, success=True, output="/tmp")
    with pytest.raises(GoalError, match="not a stable verification"):
        service.mark_complete(
            "Done",
            evidence=["pwd"],
            audit={
                "checks": [
                    {
                        "requirement_id": "objective",
                        "explanation": "Claimed done",
                        "evidence": ["pwd"],
                    }
                ]
            },
        )
    assert service.snapshot().status is GoalStatus.ACTIVE
    assert service.snapshot().evidence[0]["output_excerpt"] == "/tmp"


def test_evidence_overflow_is_bounded_persisted_and_cannot_complete(monkeypatch):
    monkeypatch.setattr("deepseek_tui.goal.service.MAX_UNRESOLVED_FAILURES", 2)
    service = GoalService()
    service.create("Many failing checks")
    for i in range(100):
        service.record_tool_result(str(i), "exec_shell", {"command": f"check {i}"}, success=False)
    assert len(service.snapshot().evidence) <= 82
    assert service.snapshot().evidence_overflow
    assert service.snapshot().status is GoalStatus.PAUSED
    dumped = service.dump()
    restored = GoalService()
    restored.restore(dumped.goal, dumped.queue)
    with pytest.raises(GoalError, match="overflowed"):
        restored.resume()
    with pytest.raises(GoalError, match="exceeded capacity"):
        restored.mark_complete("Done", evidence=["check"])


async def test_get_goal_does_not_hash_entire_workspace(engine_ctx):
    from deepseek_tui.goal.tools import GetGoalTool
    from deepseek_tui.protocol.responses import ToolCall

    engine, context = engine_ctx
    engine.goal_service.create("work")
    tool = GetGoalTool()
    engine.tool_registry.register(tool)
    with patch("deepseek_tui.goal.workspace.workspace_digest") as digest:
        await engine._execute_single_tool(
            ToolCall(id="read-goal", name="GetGoal", arguments={}),
            engine.tool_registry.to_api_tools(),
            "deepseek-chat",
        )
    digest.assert_not_called()


def test_long_completion_criterion_is_rejected_without_truncation():
    service = GoalService()
    with pytest.raises(GoalError, match="cannot exceed"):
        service.create("goal", completion_criterion="x" * 4001)
    assert service.snapshot() is None


def test_queue_acknowledges_item_identity_after_reordering():
    service = GoalService()
    service.create("first")
    item = service.enqueue("second")
    remaining = service.enqueue("third")
    complete(service)
    service.create(item.objective, queue_item_id=item.item_id)
    service.queue_move(1, 2)
    service.on_turn_started()
    assert [item.item_id for item in service.queue_items()] == [remaining.item_id]


def test_read_evidence_remains_usable_for_document_goals():
    service = GoalService()
    service.create("Review the completed document")
    service.record_tool_result(
        "read",
        "read_file",
        {"path": "report.md"},
        success=True,
        output="Completed report with sources",
    )
    service.mark_complete(
        "Reviewed",
        evidence=["read"],
        audit={
            "checks": [
                {
                    "requirement_id": "objective",
                    "explanation": "Read the delivered report",
                    "evidence": ["read"],
                }
            ]
        },
    )
    assert service.snapshot().status is GoalStatus.COMPLETE
