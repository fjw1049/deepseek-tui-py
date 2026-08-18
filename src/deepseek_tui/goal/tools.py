"""Goal tools — CreateGoal / GetGoal / UpdateGoal / SetGoalBudget."""

from __future__ import annotations

import json
from typing import Any

from deepseek_tui.goal.injection import blocked_reason_prompt, completion_summary_prompt
from deepseek_tui.goal.types import (
    CREATE_GOAL_NAME,
    GET_GOAL_NAME,
    GOAL_SERVICE_KEY,
    GOAL_TURN_ID_KEY,
    SET_GOAL_BUDGET_NAME,
    STALE_GOAL_TOOL_MESSAGE,
    UPDATE_GOAL_NAME,
    GoalActor,
    GoalError,
)
from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
)


def goal_service_from_context(context: ToolContext) -> Any:
    service = context.metadata.get(GOAL_SERVICE_KEY)
    if service is None:
        raise ToolError("Goal service is not available in this session")
    return service


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


class CreateGoalTool(ToolSpec):
    def name(self) -> str:
        return CREATE_GOAL_NAME

    def description(self) -> str:
        return (
            "Create a durable, structured goal that the runtime will pursue across multiple turns. "
            "Call only when the user explicitly asks you to start a goal or work autonomously "
            "toward an outcome. Do not create a goal for greetings, ordinary questions, or vague "
            "requests that lack a verifiable completion condition. Creating a goal fails if one "
            "already exists, unless replace is true and the user asked to abandon the current goal."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": "The objective to pursue. Must have a verifiable end state.",
                },
                "completionCriterion": {
                    "type": "string",
                    "description": (
                        "How to verify the goal is complete. Include when the "
                        "user provides one."
                    ),
                },
                "replace": {
                    "type": "boolean",
                    "description": "Replace an existing goal instead of failing.",
                },
            },
            "required": ["objective"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.REQUIRES_APPROVAL]

    def supports_parallel(self) -> bool:
        return False

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        service = goal_service_from_context(context)
        stale = _stale_goal_result(service, context)
        if stale is not None:
            return stale
        try:
            snapshot = service.create(
                str(input_data.get("objective") or ""),
                completion_criterion=_opt_str(input_data.get("completionCriterion")),
                replace=bool(input_data.get("replace")),
                actor=GoalActor.MODEL,
                mode=str(context.metadata.get("engine_mode") or "agent"),
            )
        except GoalError as exc:
            return ToolResult(success=False, content=exc.message)
        context.metadata[GOAL_TURN_ID_KEY] = snapshot.goal_id
        adopted = service.adopt_current_turn()
        return ToolResult(
            success=True,
            content=_json({"goal": (adopted or snapshot).for_model()}),
        )


class GetGoalTool(ToolSpec):
    def name(self) -> str:
        return GET_GOAL_NAME

    def description(self) -> str:
        return (
            "Read the current goal snapshot (status, objective, progress, "
            "budget). Returns null when none exists."
        )

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        del input_data
        service = goal_service_from_context(context)
        snapshot = service.snapshot()
        payload = None if snapshot is None else snapshot.for_model()
        return ToolResult(success=True, content=_json({"goal": payload}))


class UpdateGoalTool(ToolSpec):
    def name(self) -> str:
        return UPDATE_GOAL_NAME

    def description(self) -> str:
        return (
            "Set the status of the current goal. This is how you resume, complete, or block "
            "an autonomous goal. Most active goal turns should not call this tool. "
            "`complete` — the objective is satisfied and any stated validation has passed. "
            "`blocked` — a genuine impasse; for non-terminal blockers the same condition must "
            "repeat for at least 3 consecutive goal turns. `active` — resume a paused or blocked "
            "goal when the user explicitly asks. Users pause from the host UI, not this tool."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "blocked", "complete"],
                },
                "reason": {"type": "string"},
            },
            "required": ["status"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        service = goal_service_from_context(context)
        stale = _stale_goal_result(service, context)
        if stale is not None:
            return stale
        status = str(input_data.get("status") or "").strip()
        reason = _opt_str(input_data.get("reason"))
        try:
            if status == "complete":
                snapshot, _promoted = service.mark_complete(reason, GoalActor.MODEL)
                return ToolResult(success=True, content=completion_summary_prompt(snapshot))
            if status == "blocked":
                snapshot = service.mark_blocked(reason, GoalActor.MODEL)
                return ToolResult(success=True, content=blocked_reason_prompt(snapshot))
            if status == "active":
                snapshot, _decision = service.resume(
                    reason,
                    GoalActor.MODEL,
                    mode=str(context.metadata.get("engine_mode") or "agent"),
                    launch=False,
                )
            else:
                raise GoalError("status_invalid", f"Unknown goal status \"{status}\"")
        except GoalError as exc:
            return ToolResult(success=False, content=exc.message)
        return ToolResult(success=True, content=_json({"goal": snapshot.for_model()}))


class SetGoalBudgetTool(ToolSpec):
    def name(self) -> str:
        return SET_GOAL_BUDGET_NAME

    def description(self) -> str:
        return (
            "Set a hard turn, token, or wall-clock budget on the current goal. "
            "Only call this when the user stated an explicit numeric limit. "
            "Do not invent budgets from vague language like \"quickly\"."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "turnBudget": {"type": "integer", "minimum": 1},
                "tokenBudget": {"type": "integer", "minimum": 1},
                "wallClockBudgetMs": {"type": "integer", "minimum": 1000},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        service = goal_service_from_context(context)
        stale = _stale_goal_result(service, context)
        if stale is not None:
            return stale
        try:
            snapshot = service.set_budget(
                token_budget=_opt_int(input_data.get("tokenBudget")),
                turn_budget=_opt_int(input_data.get("turnBudget")),
                wall_clock_budget_ms=_opt_int(input_data.get("wallClockBudgetMs")),
                actor=GoalActor.MODEL,
            )
        except GoalError as exc:
            return ToolResult(success=False, content=exc.message)
        return ToolResult(success=True, content=_json({"goal": snapshot.for_model()}))


def goal_tools() -> list[ToolSpec]:
    return [CreateGoalTool(), GetGoalTool(), UpdateGoalTool(), SetGoalBudgetTool()]


def _stale_goal_result(service: Any, context: ToolContext) -> ToolResult | None:
    if GOAL_TURN_ID_KEY not in context.metadata:
        return None
    expected = context.metadata.get(GOAL_TURN_ID_KEY)
    snapshot = service.snapshot()
    current_id = None if snapshot is None else snapshot.goal_id
    if current_id != expected:
        return ToolResult(success=False, content=STALE_GOAL_TOOL_MESSAGE)
    return None


def _opt_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _opt_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
