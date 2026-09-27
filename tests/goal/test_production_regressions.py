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
from deepseek_tui.goal.workspace import workspace_digest
from deepseek_tui.protocol.responses import ToolCall
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
    service.record_tool_result(call_id, "exec_shell", {"command": command}, success=success)


def audit(service, evidence="pass"):
    return {
        "checks": [
            {
                "requirement_id": item["id"],
                "explanation": "Verified the required behavior",
                "evidence": [evidence],
            }
            for item in service.snapshot().requirements
        ]
    }


def request(service, evidence="pass", **extra):
    return {
        "status": "complete",
        "reason": "Verified",
        "evidence": [evidence],
        "audit": audit(service, evidence),
        **extra,
    }


@pytest.mark.asyncio
async def test_failure_cannot_hide_behind_unrelated_success(tmp_path):
    service, context = goal(tmp_path)
    record(service, "failed", success=False)
    record(service, "pwd", command="pwd")
    result = await UpdateGoalTool().execute(request(service, "pwd"), context)
    assert not result.success
    assert "failed" in result.content
    assert service.snapshot().status is GoalStatus.ACTIVE


@pytest.mark.asyncio
async def test_relevant_rerun_supersedes_failure(tmp_path):
    service, context = goal(tmp_path)
    record(service, "failed", success=False)
    record(service)
    assert (await UpdateGoalTool().execute(request(service), context)).success


@pytest.mark.asyncio
async def test_alternative_verification_requires_explaining_failure(tmp_path):
    service, context = goal(tmp_path)
    record(service, "failed", command="obsolete-test-runner", success=False)
    record(service)
    payload = request(service)
    payload["audit"]["failure_resolutions"] = [
        {
            "tool_call_id": "failed",
            "reason": "Old runner unavailable; pytest covers the same cases",
            "evidence": ["pass"],
        }
    ]
    assert (await UpdateGoalTool().execute(payload, context)).success
    assert service.snapshot().completion_audit == payload["audit"]


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
    record(service)
    payload = request(service)
    payload["audit"]["checks"] = payload["audit"]["checks"][:1]
    assert not (await UpdateGoalTool().execute(payload, context)).success
    assert len(service.snapshot().requirements) == 2


@pytest.mark.asyncio
async def test_cancelled_step_requires_explanation_even_with_requirement_coverage(tmp_path):
    service, context = goal(tmp_path)
    service.save_checklist([{"id": "1", "content": "Old test runner", "status": "cancelled"}])
    record(service)
    payload = request(service)
    assert not (await UpdateGoalTool().execute(payload, context)).success
    payload["audit"]["plan_adjustments"] = [
        {
            "item_id": "1",
            "reason": "Used pytest instead; all acceptance requirements still verified",
        }
    ]
    assert (await UpdateGoalTool().execute(payload, context)).success


@pytest.mark.asyncio
async def test_model_cannot_resume_or_increase_budget(tmp_path):
    service, context = goal(tmp_path)
    service.set_budget(token_budget=100)
    service.pause()
    assert not (await UpdateGoalTool().execute({"status": "active"}, context)).success
    assert not (await SetGoalBudgetTool().execute({"tokenBudget": 1000000}, context)).success
    assert service.snapshot().status is GoalStatus.PAUSED
    assert service.snapshot().budget.token_budget == 100


def test_service_has_no_unvalidated_completion_entry(tmp_path):
    service, _ = goal(tmp_path)
    with pytest.raises(GoalError):
        service.mark_complete("done")
    assert service.snapshot().status is GoalStatus.ACTIVE


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
def test_malformed_persisted_fields_do_not_crash_or_complete(tmp_path, field, value):
    service, _ = goal(tmp_path)
    data = service.dump().goal
    data[field] = value
    service.restore(data)
    assert service.snapshot().status is GoalStatus.PAUSED
    service.resume()
    with pytest.raises(GoalError):
        service.mark_complete("done", evidence=["missing"], audit=audit(service))


def test_unresolved_failure_survives_evidence_rollover_and_restore(tmp_path):
    service, _ = goal(tmp_path)
    record(service, "failed", success=False)
    for index in range(90):
        record(service, str(index), command=f"read-{index}")
    data = service.dump().goal
    service.restore(data)
    service.resume()
    record(service, "pass", command="other-check")
    with pytest.raises(GoalError, match="Unresolved tool failures"):
        service.mark_complete("done", evidence=["pass"], audit=audit(service))


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


def test_workspace_identity_detects_content_changes_but_ignores_runtime_cache(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("before")
    before = workspace_digest(tmp_path)
    cache = tmp_path / ".deepseek"
    cache.mkdir()
    (cache / "state.json").write_text("updated state")
    assert workspace_digest(tmp_path) == before
    source.write_text("after")
    assert workspace_digest(tmp_path) != before


@pytest.mark.asyncio
async def test_external_or_shell_edit_invalidates_real_engine_evidence(engine_ctx, tmp_path):
    engine, _ = engine_ctx
    source = tmp_path / "report.txt"
    source.write_text("Verified report")
    snapshot = engine.goal_service.create("Write and verify report")
    engine.tool_context.metadata[GOAL_TURN_ID_KEY] = snapshot.goal_id
    await engine._execute_tool_calls(
        [ToolCall(id="read", name="read_file", arguments={"path": "report.txt"})]
    )
    # An external writer (or shell/subagent) bypasses all WRITES_FILES capabilities.
    source.write_text("Changed after verification")
    payload = request(engine.goal_service, "read")
    await engine._execute_tool_calls(
        [ToolCall(id="complete", name="UpdateGoal", arguments=payload)]
    )
    assert engine.goal_service.snapshot().status is GoalStatus.ACTIVE
    assert engine.goal_service.snapshot().work_revision > 0


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
        service.record_tool_result(
            str(index), "exec_shell", {"process_id": "p"}, success=True, finished=False
        )
        assert service.on_turn_ended(automatic=True).should_continue


def test_changed_tool_output_is_progress(tmp_path):
    service, _ = goal(tmp_path)
    for index in range(5):
        service.on_turn_started()
        service.record_tool_result(
            str(index), "fetch_url", {"url": "job"}, success=True, output=f"Progress: {index}"
        )
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
    service.mark_complete("Verified", evidence=["pass"], audit=audit(service))
    assert service.snapshot().status is GoalStatus.COMPLETE


def test_completion_rechecks_actual_deadline(tmp_path):
    service, _ = goal(tmp_path)
    service.set_budget(wall_clock_budget_ms=1000)
    record(service)
    service._state = replace(service.state, wall_clock_ms=2000)
    with pytest.raises(GoalError):
        service.mark_complete("Verified", evidence=["pass"], audit=audit(service))
    assert service.snapshot().status is GoalStatus.BUDGET_LIMITED


@pytest.mark.asyncio
async def test_real_shell_write_is_not_verification(engine_ctx, tmp_path, monkeypatch):
    engine, _ = engine_ctx
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch/report.txt").write_text("Original")
    snapshot = engine.goal_service.create("Update and inspect report")
    engine.tool_context.metadata[GOAL_TURN_ID_KEY] = snapshot.goal_id

    async def execute_registered(call, _catalog, _model):
        # This fixture authorizes only tools executing within pytest's temporary workspace.
        return await engine.tool_registry.execute(call.name, call.arguments, engine.tool_context)

    monkeypatch.setattr(engine, "_execute_single_tool_impl", execute_registered)
    shell_results = await engine._execute_tool_calls(
        [
            ToolCall(
                id="write",
                name="exec_shell",
                arguments={
                    "command": "printf changed > scratch/report.txt",
                    "timeout_ms": 1000,
                },
            )
        ]
    )
    assert (tmp_path / "scratch/report.txt").read_text() == "changed", shell_results
    evidence = engine.goal_service.snapshot().evidence[-1]
    assert evidence["success"] and evidence["finished"]
    assert not evidence["verification"]
    await engine._execute_tool_calls(
        [
            ToolCall(
                id="finish-write",
                name="UpdateGoal",
                arguments=request(engine.goal_service, "write"),
            )
        ]
    )
    assert engine.goal_service.snapshot().status is GoalStatus.ACTIVE
    await engine._execute_tool_calls(
        [ToolCall(id="read-new", name="read_file", arguments={"path": "scratch/report.txt"})]
    )
    await engine._execute_tool_calls(
        [
            ToolCall(
                id="finish-read",
                name="UpdateGoal",
                arguments=request(engine.goal_service, "read-new"),
            )
        ]
    )
    assert engine.goal_service.snapshot().status is GoalStatus.COMPLETE


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


@pytest.mark.asyncio
async def test_unreadable_workspace_blocks_completion_but_can_report_blocker(
    engine_ctx, monkeypatch
):
    engine, _ = engine_ctx
    snapshot = engine.goal_service.create("Inspect workspace")
    engine.tool_context.metadata[GOAL_TURN_ID_KEY] = snapshot.goal_id
    monkeypatch.setattr("deepseek_tui.goal.workspace.workspace_digest", lambda _root: None)
    await engine._execute_tool_calls(
        [ToolCall(id="complete", name="UpdateGoal", arguments=request(engine.goal_service))]
    )
    assert engine.goal_service.snapshot().status is GoalStatus.ACTIVE
    await engine._execute_tool_calls(
        [
            ToolCall(
                id="blocked",
                name="UpdateGoal",
                arguments={
                    "status": "blocked",
                    "reason": "Workspace unavailable after repeated attempts",
                },
            )
        ]
    )
    assert engine.goal_service.snapshot().status is GoalStatus.BLOCKED
