"""Behavioral regressions for the systematic Goal audit."""


import pytest

from deepseek_tui.goal.commands import parse_goal_command
from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.types import GoalError


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


def complete(service):
    service.mark_complete("Checked")


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




def test_a_goal_saved_by_the_former_audit_still_loads():
    # Completed goals keep their record; a live goal's leftover audit state is simply ignored.
    audit = {"checks": [{"requirement_id": "objective", "explanation": "Passed", "evidence": ["a"]}]}
    service = GoalService()
    service.create("Verify regression")
    saved = service.dump().goal
    saved.update(completion_evidence=["a"], completion_audit=audit, work_revision=7,
                 evidence_overflow=True, evidence=[{"tool_call_id": "a"}])
    restored = GoalService()
    restored.restore(saved)
    snapshot = restored.snapshot()
    assert snapshot.completion_evidence == ("a",)
    assert snapshot.completion_audit == audit
    assert not hasattr(snapshot, "evidence_overflow")
    assert "completion_audit" not in snapshot.for_model()
    saved = restored.dump().goal
    saved["completion_audit"]["checks"][0]["explanation"] = "modified"
    assert snapshot.completion_audit["checks"][0]["explanation"] == "Passed"
