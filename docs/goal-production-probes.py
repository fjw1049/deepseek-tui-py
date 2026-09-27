"""Offline adversarial audit; observations are NOT measurements of real-model quality.

Run from the repository: PYTHONPATH=src .venv/bin/python docs/goal-production-probes.py
No model requests, shell commands, or user files are executed/modified by these probes.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from deepseek_tui.engine.orchestrator.core import Engine
from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.tools import SetGoalBudgetTool, UpdateGoalTool
from deepseek_tui.goal.types import GOAL_SERVICE_KEY, GOAL_TURN_ID_KEY
from deepseek_tui.tools.registry import ToolContext


def setup():
    service = GoalService()
    goal = service.create("Fix failing checkout tests and verify they pass")
    context = ToolContext(
        working_directory=Path("."),
        metadata={GOAL_SERVICE_KEY: service, GOAL_TURN_ID_KEY: goal.goal_id},
    )
    return service, context


def record(service, call_id, command, success=True):
    service.record_tool_result(call_id, "exec_shell", {"command": command}, success=success)


async def finish(context, evidence):
    service = context.metadata[GOAL_SERVICE_KEY]
    return await UpdateGoalTool().execute(
        {
            "status": "complete",
            "reason": "Everything is done",
            "evidence": evidence,
            "audit": {
                "checks": [
                    {
                        "requirement_id": item["id"],
                        "explanation": "Claimed done",
                        "evidence": evidence,
                    }
                    for item in service.snapshot().requirements
                ]
            },
        },
        context,
    )


async def main():
    findings = {}
    service, context = setup()
    record(service, "failure", "pytest tests/checkout", False)
    record(service, "unrelated", "pwd")
    result = await finish(context, ["unrelated"])
    findings["failed_tests_plus_unrelated_success"] = {
        "completion_accepted": result.success,
        "status": service.snapshot().status.value,
    }

    for disposition in ("delete", "cancel"):
        service, context = setup()
        item = {"id": "1", "content": "Fix checkout tests", "status": "pending"}
        service.save_checklist([item])
        service.save_checklist([] if disposition == "delete" else [{**item, "status": "cancelled"}])
        record(service, "unrelated", "pwd")
        findings[f"{disposition}_unfinished_checklist"] = {
            "completion_accepted": (await finish(context, ["unrelated"])).success
        }

    service, context = setup()
    service.pause("User paused")
    result = await UpdateGoalTool().execute({"status": "active"}, context)
    findings["model_resume_without_user_authorization_record"] = {
        "accepted": result.success,
        "status": service.snapshot().status.value,
    }

    service, context = setup()
    service.set_budget(token_budget=100)
    result = await SetGoalBudgetTool().execute({"tokenBudget": 1000000}, context)
    findings["model_budget_increase_without_user_authorization_record"] = {
        "accepted": result.success,
        "limit": service.snapshot().budget.token_budget,
    }

    service, context = setup()
    service.set_budget(wall_clock_budget_ms=1000)
    handle = SimpleNamespace(cancel=AsyncMock())
    task = asyncio.create_task(
        Engine._enforce_goal_wall_clock_deadline(
            SimpleNamespace(goal_service=service, handle=handle, tool_context=context)
        )
    )
    try:
        await asyncio.sleep(0)
        service.set_budget(wall_clock_budget_ms=60000)
        from dataclasses import replace

        service._state = replace(service.state, wall_clock_ms=2000)
        service.changed.set()
        await asyncio.sleep(0.01)
        snapshot = service.snapshot()
        findings["extended_deadline_uses_old_timer"] = {
            "status": snapshot.status.value,
            "remaining_ms": snapshot.budget.remaining_wall_clock_ms,
            "cancel_calls": handle.cancel.await_count,
        }
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    service, _ = setup()
    decisions = []
    for index in range(5):
        service.on_turn_started()
        record(service, f"noop-{index}", "pwd")
        decisions.append(service.on_turn_ended(automatic=True).should_continue)
    findings["identical_noop_in_five_automatic_turns"] = {"continues": decisions}

    for field, value in (("evidence", [{}]), ("checklist", None)):
        service, _ = setup()
        data = service.dump().goal
        data[field] = value
        try:
            service.restore(data)
            service.resume()
            service.validate_completion("Done", ["missing"])
        except Exception as exc:
            findings[f"malformed_persisted_{field}"] = {"exception": type(exc).__name__}

    service, _ = setup()
    try:
        service.mark_complete("No validation")
    except Exception:
        pass  # The observed status below must remain active.
    findings["direct_service_completion_bypasses_gate"] = {
        "status": service.snapshot().status.value,
        "evidence": list(service.snapshot().completion_evidence),
    }
    print(json.dumps(findings, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
