"""Adversarial completion and lifecycle cases from the production audit."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.orchestrator.core import Engine
from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.tools import SetGoalBudgetTool, UpdateGoalTool
from deepseek_tui.goal.types import GOAL_SERVICE_KEY, GOAL_TURN_ID_KEY, GoalError, GoalStatus
from deepseek_tui.tools.registry import ToolContext


def goal(tmp_path):
    service = GoalService()
    snapshot = service.create("Fix checkout and pass its regression tests")
    context = ToolContext(
        working_directory=tmp_path,
        metadata={
            GOAL_SERVICE_KEY: service,
            GOAL_TURN_ID_KEY: snapshot.goal_id,
        },
    )
    return service, context


def record(service, call_id="pass", command="pytest", success=True):
    service.record_work("exec_shell", {"command": command})


def request(service, **extra):
    return {"status": "complete", "reason": "Verified", **extra}


@pytest.mark.parametrize("disposition", ["delete", "cancel", "rename"])
@pytest.mark.asyncio
async def test_plan_edits_do_not_remove_acceptance_requirements(tmp_path, disposition):
    service, context = goal(tmp_path)
    service.add_requirements(["Wrong passwords must be rejected"])
    item = {"id": "1", "content": "Test wrong passwords", "status": "pending"}
    service.save_checklist([item])
    service.save_checklist(
        []
        if disposition == "delete"
        else [
            {**item, "status": "cancelled"}
            if disposition == "cancel"
            else {**item, "content": "Read README", "status": "completed"}
        ]
    )
    assert len(service.snapshot().requirements) == 2


@pytest.mark.asyncio
async def test_model_cannot_resume_or_increase_budget(tmp_path):
    service, context = goal(tmp_path)
    service.set_budget(token_budget=100)
    service.pause()
    assert not (await UpdateGoalTool().execute({"status": "active"}, context)).success
    assert not (await SetGoalBudgetTool().execute({"tokenBudget": 1000000}, context)).success
    assert service.snapshot().status is GoalStatus.PAUSED
    assert service.snapshot().budget.token_budget == 100


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence", [{}]),
        ("evidence", None),
        ("checklist", None),
        ("completion_evidence", 3),
        ("work_revision", "bad"),
        ("tokens_used", float("inf")),
    ],
)
def test_malformed_persisted_fields_do_not_crash(tmp_path, field, value):
    service, _ = goal(tmp_path)
    data = service.dump().goal
    data[field] = value
    service.restore(data)
    assert service.snapshot().status is GoalStatus.PAUSED


@pytest.mark.asyncio
async def test_attached_process_blocks_completion(tmp_path):
    service, context = goal(tmp_path)
    record(service)
    context.metadata["shell_processes"] = {"p": SimpleNamespace(returncode=None)}
    context.metadata["shell_process_detached"] = {"p": False}
    result = await UpdateGoalTool().execute(request(service), context)
    assert not result.success
    assert "shell work" in result.content


@pytest.mark.asyncio
async def test_dynamic_deadline_first_budget_extension_shortening_and_pause(tmp_path):
    service, context = goal(tmp_path)
    context.metadata["goal_turn_active"] = True
    handle = SimpleNamespace(cancel=AsyncMock())
    engine = SimpleNamespace(goal_service=service, tool_context=context, handle=handle)
    task = asyncio.create_task(Engine._enforce_goal_wall_clock_deadline(engine))
    try:
        await asyncio.sleep(0)  # Initially unlimited.
        service.set_budget(wall_clock_budget_ms=1000)
        await asyncio.sleep(0)
        service.set_budget(wall_clock_budget_ms=60000)
        # Advance accumulated time past the OLD budget, but below the new one.
        service._state = replace(service.state, wall_clock_ms=2000)
        service.changed.set()
        await asyncio.sleep(0.01)
        assert service.snapshot().status is GoalStatus.ACTIVE
        assert handle.cancel.await_count == 0
        service.pause()
        service.set_budget(wall_clock_budget_ms=1000)
        await asyncio.sleep(0.01)
        assert handle.cancel.await_count == 0
        service.resume()  # Still exhausted: cannot run and timer cancels this attached turn.
        await asyncio.wait_for(task, 1)
        assert service.snapshot().status is GoalStatus.BUDGET_LIMITED
        handle.cancel.assert_awaited_once()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_repeated_noop_tools_pause_but_pending_work_does_not(tmp_path):
    service, _ = goal(tmp_path)
    for index in range(4):
        service.on_turn_started()
        record(service, str(index), command="pwd")
        decision = service.on_turn_ended(automatic=True)
    assert not decision.should_continue
    assert service.snapshot().status is GoalStatus.PAUSED
    service.resume()
    for index in range(5):
        service.on_turn_started()
        service.record_work("exec_shell", {"process_id": "p"}, finished=False)
        assert service.on_turn_ended(automatic=True).should_continue


def test_changed_tool_output_is_progress(tmp_path):
    service, _ = goal(tmp_path)
    for index in range(5):
        service.on_turn_started()
        service.record_work("fetch_url", {"url": "job"}, output=f"Progress: {index}")
        assert service.on_turn_ended(automatic=True).should_continue


@pytest.mark.asyncio
async def test_old_model_call_cannot_complete_after_user_pause_and_resume(tmp_path):
    service, context = goal(tmp_path)
    context.metadata["goal_control_epoch"] = service.control_epoch
    record(service)
    service.pause()
    service.resume()
    result = await UpdateGoalTool().execute(request(service), context)
    assert not result.success
    assert "stale" in result.content
    assert service.snapshot().status is GoalStatus.ACTIVE


@pytest.mark.asyncio
async def test_late_cancellation_does_not_undo_user_resume(engine_ctx):
    engine, _ = engine_ctx
    service = engine.goal_service
    snapshot = service.create("Finish work")
    engine.tool_context.metadata.update(
        {
            GOAL_TURN_ID_KEY: snapshot.goal_id,
            "goal_control_epoch": service.control_epoch,
        }
    )
    service.pause()
    service.resume()
    engine.launch_goal_continuation = AsyncMock()
    await engine._finish_goal_turn(cancelled=True, failed=False, error_message=None)
    assert service.snapshot().status is GoalStatus.ACTIVE
    engine.launch_goal_continuation.assert_awaited_once()


def test_changing_budget_during_last_allowed_turn_does_not_end_it(tmp_path):
    service, _ = goal(tmp_path)
    service.set_budget(turn_budget=1)
    service.on_turn_started()
    service.set_budget(token_budget=100)
    assert service.snapshot().status is GoalStatus.ACTIVE
    record(service)
    service.mark_complete("Verified")
    assert service.snapshot().status is GoalStatus.COMPLETE


def test_completion_rechecks_actual_deadline(tmp_path):
    service, _ = goal(tmp_path)
    service.set_budget(wall_clock_budget_ms=1000)
    record(service)
    service._state = replace(service.state, wall_clock_ms=2000)
    with pytest.raises(GoalError):
        service.mark_complete("Verified")
    assert service.snapshot().status is GoalStatus.BUDGET_LIMITED


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pause", "replace"])
async def test_queued_continuation_is_rechecked_before_calling_model(engine_ctx, change):
    from deepseek_tui.engine.handle import SendMessageOp

    engine, _ = engine_ctx
    old = engine.goal_service.create("Old goal")
    if change == "pause":
        engine.goal_service.pause()
    else:
        engine.goal_service.create("New goal", replace=True)
    engine.turn_loop.run = AsyncMock()
    await engine._handle_send_message_inner(
        SendMessageOp(
            content="Continue",
            hidden=True,
            internal_kind="goal_continuation",
            expected_goal_id=old.goal_id,
        ),
        "late-turn",
    )
    engine.turn_loop.run.assert_not_awaited()


