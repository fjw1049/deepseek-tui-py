"""Goal completion must use observed evidence and preserve unfinished work."""

from pathlib import Path

import pytest

from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.tools import UpdateGoalTool
from deepseek_tui.goal.types import GOAL_SERVICE_KEY, GOAL_TURN_ID_KEY, GoalStatus
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.todo import TodoItem


def observe(service, call_id="test-1", *, success=True, mutates=False):
    service.record_tool_result(
        call_id,
        "write_file" if mutates else "exec_shell",
        {"command": "pytest"},
        success=success,
        mutates=mutates,
    )


async def complete(service, **extra):
    context = ToolContext(
        working_directory=Path("."),
        metadata={
            GOAL_SERVICE_KEY: service,
            GOAL_TURN_ID_KEY: service.snapshot().goal_id,
        },
    )
    return await UpdateGoalTool().execute(
        {
            "status": "complete",
            "reason": "All requested behavior verified",
            "evidence": ["test-1"],
            "audit": {"checks": [
                {"requirement_id": item["id"], "explanation": "Verified current result",
                 "evidence": extra.get("evidence", ["test-1"])}
                for item in service.snapshot().requirements
            ]},
            **extra,
        },
        context,
    )


@pytest.mark.asyncio
async def test_no_evidence_cannot_complete():
    service = GoalService()
    service.create("Fix tests")
    result = await complete(service)
    assert not result.success
    assert service.snapshot().status is GoalStatus.ACTIVE


@pytest.mark.asyncio
async def test_failed_evidence_cannot_complete():
    service = GoalService()
    service.create("Fix tests")
    observe(service, success=False)
    assert not (await complete(service)).success
    assert service.snapshot().status is GoalStatus.ACTIVE


@pytest.mark.asyncio
async def test_open_goal_checklist_blocks_completion():
    service = GoalService()
    service.create("Implement and test")
    service.save_checklist([{"id": "1", "content": "Integration tests", "status": "pending"}])
    observe(service)
    result = await complete(service)
    assert not result.success
    assert "Integration tests" in result.content


@pytest.mark.asyncio
async def test_edit_invalidates_previous_evidence():
    service = GoalService()
    service.create("Fix tests")
    observe(service)
    observe(service, "edit-1", mutates=True)
    assert not (await complete(service)).success
    observe(service, "test-2")
    assert (await complete(service, evidence=["test-2"])).success


@pytest.mark.asyncio
async def test_new_failure_supersedes_earlier_pass():
    service = GoalService()
    service.create("Fix tests")
    observe(service)
    observe(service, "test-2", success=False)
    assert not (await complete(service)).success


@pytest.mark.asyncio
async def test_completion_is_retained_and_restored():
    service = GoalService()
    service.create("Fix tests")
    observe(service)
    assert (await complete(service)).success
    restored = GoalService()
    restored.restore(service.dump().goal)
    assert restored.snapshot().status is GoalStatus.COMPLETE
    assert restored.snapshot().completion_evidence == ("test-1",)
    assert not restored.peek_continuation().should_continue


def test_automatic_text_only_turn_pauses():
    service = GoalService()
    service.create("Fix tests")
    service.on_turn_started()
    assert not service.on_turn_ended(automatic=True).should_continue
    assert service.snapshot().status is GoalStatus.PAUSED
    service.resume()
    service.on_turn_started()
    observe(service)
    assert service.on_turn_ended(automatic=True).should_continue


def test_restore_preserves_checklist():
    service = GoalService()
    service.create("Fix tests")
    items = [{"id": "1", "content": "Still needed", "status": "pending"}]
    service.save_checklist(items)
    restored = GoalService()
    restored.restore(service.dump().goal)
    assert list(restored.snapshot().checklist) == items


@pytest.mark.asyncio
async def test_restore_requires_fresh_verification():
    service = GoalService()
    service.create("Fix tests")
    observe(service)
    restored = GoalService()
    restored.restore(service.dump().goal)
    restored.resume()
    assert not (await complete(restored)).success


@pytest.mark.asyncio
async def test_paused_goal_edits_invalidate_old_verification():
    service = GoalService()
    service.create("Fix tests")
    observe(service)
    service.pause()
    observe(service, "edit", mutates=True)
    service.resume()
    assert not (await complete(service)).success


@pytest.mark.asyncio
async def test_unrelated_paused_turn_does_not_replace_goal_checklist():
    from deepseek_tui.goal.tools import capture_goal_checklist, restore_goal_checklist

    service = GoalService()
    goal = service.create("Fix tests")
    service.save_checklist([{"id": "1", "content": "Original requirement", "status": "pending"}])
    service.pause()
    context = ToolContext(
        working_directory=Path("."),
        metadata={
            GOAL_SERVICE_KEY: service,
            GOAL_TURN_ID_KEY: goal.goal_id,
            "goal_turn_active": False,
            "todos": {"items": [TodoItem("1", "Unrelated question", "completed")], "next_id": 2},
        },
    )
    capture_goal_checklist(context)
    assert service.snapshot().checklist[0]["content"] == "Original requirement"
    service.resume()
    restore_goal_checklist(context)
    assert context.metadata["todos"]["items"][0].content == "Original requirement"


@pytest.mark.asyncio
async def test_goal_turn_end_does_not_cancel_checklist(engine_ctx):
    engine, _ = engine_ctx
    engine.goal_service.create("Implement and test")
    todo = TodoItem("1", "Tests", "in_progress")
    engine.tool_context.metadata["todos"] = {"items": [todo], "next_id": 2}
    await engine._emit_checklist_turn_end_reconcile()
    assert todo.status == "in_progress"


def test_user_can_reopen_complete_and_evidence_must_be_fresh(complete_goal):
    service = GoalService()
    service.create("Fix tests")
    observe(service)
    complete_goal(service)
    snapshot, decision = service.reopen()
    assert snapshot.status is GoalStatus.ACTIVE
    assert decision.should_continue
    assert not snapshot.evidence


def test_budget_exhaustion_has_distinct_status():
    service = GoalService()
    service.create("Fix tests")
    service.set_budget(turn_budget=1)
    service.on_turn_started()
    service.on_turn_ended()
    assert service.snapshot().status is GoalStatus.BUDGET_LIMITED
    assert not service.resume()[1].should_continue
    service.set_budget(turn_budget=2)
    assert service.resume()[1].should_continue


@pytest.mark.parametrize("action", ["cancel", "reopen"])
def test_user_action_cancels_pending_queue_promotion(action, complete_goal):
    service = GoalService()
    service.create("First")
    service.enqueue("Second")
    complete_goal(service)
    getattr(service, action)()
    assert service.consume_promoted() is None
    assert len(service.queue_items()) == 1


@pytest.mark.asyncio
async def test_unfinished_background_result_is_not_evidence():
    service = GoalService()
    service.create("Run tests")
    service.record_tool_result(
        "test-1", "exec_shell", {"command": "pytest"}, success=True, finished=False
    )
    assert not (await complete(service)).success


@pytest.mark.asyncio
async def test_engine_records_real_verification_and_finishes(engine_ctx, tmp_path):
    from deepseek_tui.protocol.responses import ToolCall

    engine, _ = engine_ctx
    (tmp_path / "report.txt").write_text("Research result with sources")
    goal = engine.goal_service.create("Write and inspect research report")
    engine.tool_context.metadata[GOAL_TURN_ID_KEY] = goal.goal_id
    await engine._execute_tool_calls(
        [ToolCall(id="inspect", name="read_file", arguments={"path": "report.txt"})]
    )
    evidence = engine.goal_service.snapshot().evidence
    assert evidence and evidence[0]["success"]
    await engine._execute_tool_calls(
        [
            ToolCall(
                id="finish",
                name="UpdateGoal",
                arguments={
                    "status": "complete",
                    "reason": "The report is present and inspected",
                    "evidence": ["inspect"],
                    "audit": {"checks": [{"requirement_id": "objective",
                        "explanation": "Report contents inspected", "evidence": ["inspect"]}]},
                },
            )
        ]
    )
    assert engine.goal_service.snapshot().status is GoalStatus.COMPLETE


@pytest.mark.asyncio
async def test_engine_restores_goal_checklist_before_next_turn(engine_ctx):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import SendMessageOp
    from deepseek_tui.engine.turn import TurnResult
    from deepseek_tui.goal.types import GOAL_CONTINUATION_KIND
    from deepseek_tui.protocol.messages import Message

    engine, _ = engine_ctx
    engine.goal_service.create("Implement and verify")
    engine.goal_service.save_checklist(
        [{"id": "1", "content": "Unfinished tests", "status": "pending"}]
    )
    engine.turn_loop.run = AsyncMock(
        return_value=TurnResult(
            assistant_message=Message.assistant("Need to continue"), tool_calls=[]
        )
    )
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)
    engine._handle_shell_process_turn_handoff = AsyncMock(return_value=False)
    engine.tool_context.metadata["runtime_thread_id"] = "test"
    await engine._handle_send_message_inner(
        SendMessageOp(content="Continue", hidden=True, internal_kind=GOAL_CONTINUATION_KIND),
        "next-turn",
    )
    assert engine.tool_context.metadata["todos"]["items"][0].status == "pending"
    assert engine.goal_service.snapshot().checklist[0]["status"] == "pending"
    assert engine.goal_service.snapshot().status is GoalStatus.PAUSED
    assert not engine.tool_context.metadata.get("goal_continue_pending")
