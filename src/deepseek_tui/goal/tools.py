"""Model goal tools and the rejected legacy budget-tool compatibility entry."""

from __future__ import annotations

import json
from typing import Any

from deepseek_tui.goal.injection import blocked_reason_prompt, completion_summary_prompt
from deepseek_tui.goal.persist import _opt_int
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
    GoalStatus,
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


def capture_goal_checklist(context: ToolContext) -> None:
    service = context.metadata.get(GOAL_SERVICE_KEY)
    store = context.metadata.get("todos")
    if service is None or not isinstance(store, dict):
        return
    snapshot = service.snapshot()
    if snapshot is None or (
        GOAL_TURN_ID_KEY in context.metadata
        and context.metadata[GOAL_TURN_ID_KEY] != snapshot.goal_id
    ):
        return
    if snapshot.status is not GoalStatus.ACTIVE and not context.metadata.get("goal_turn_active"):
        return
    from deepseek_tui.tools.todo import TodoItem

    service.save_checklist(
        [
            {"id": item.id, "content": item.content, "status": item.status}
            for item in store.get("items", [])
            if isinstance(item, TodoItem)
        ]
    )


def restore_goal_checklist(context: ToolContext) -> None:
    service = context.metadata.get(GOAL_SERVICE_KEY)
    snapshot = None if service is None else service.snapshot()
    if snapshot is None or snapshot.status is not GoalStatus.ACTIVE:
        return
    from deepseek_tui.tools.todo import TodoItem, _coerce_status

    items = [
        TodoItem(item["id"], item["content"], _coerce_status(item["status"]))
        for item in snapshot.checklist
    ]
    context.metadata["todos"] = {
        "items": items,
        "next_id": 1 + max((int(item.id) for item in items if item.id.isdigit()), default=0),
    }


class CreateGoalTool(ToolSpec):
    def name(self) -> str:
        return CREATE_GOAL_NAME

    def description(self) -> str:
        return (
            "Create a durable, structured goal that the runtime will pursue across multiple turns. "
            "Call only when the user explicitly asks you to start a goal or work autonomously "
            "toward an outcome. Do not create a goal for greetings, ordinary questions, or vague "
            "requests that lack a verifiable completion condition. Creating a goal fails if an "
            "unfinished goal exists, unless replace is true and the user asked to abandon it."
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
                        "How to verify the goal is complete. Include when the user provides one."
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
        context.metadata["goal_control_epoch"] = service.control_epoch
        context.metadata["goal_turn_active"] = True
        capture_goal_checklist(context)
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
            "Define acceptance requirements, complete, or block the current goal. "
            "an autonomous goal. Most active goal turns should not call this tool. "
            "`complete` — the objective is satisfied and any stated validation has passed. "
            "Provide a requirement-by-requirement audit in reason and cite actual successful "
            "verification tool call IDs in evidence (inspect GetGoal). Edits alone are not "
            "verification. Do not omit required scope or cancel unfinished checklist items. "
            "`blocked` — a genuine impasse; for non-terminal blockers the same condition must "
            "repeat for at least 3 consecutive goal turns. `requirements` adds acceptance criteria "
            "from the user request before working. Existing requirements cannot be removed. "
            "Supply audit.checks covering every GetGoal requirement with an explanation "
            "and evidence IDs, failure_resolutions for unsuperseded failures, and plan_adjustments "
            "explaining cancelled plan steps without dropping user requirements. "
            "Only the user can resume a goal or adjust its budget using /goal controls."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["requirements", "blocked", "complete"],
                },
                "requirements": {"type": "array", "items": {"type": "string"}},
                "audit": {
                    "type": "object",
                    "properties": {
                        "checks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "requirement_id": {"type": "string"},
                                    "explanation": {"type": "string"},
                                    "evidence": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["requirement_id", "explanation", "evidence"],
                            },
                        },
                        "failure_resolutions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "tool_call_id": {"type": "string"},
                                    "reason": {"type": "string"},
                                    "evidence": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["tool_call_id", "reason", "evidence"],
                            },
                        },
                        "plan_adjustments": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "item_id": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["item_id", "reason"],
                            },
                        },
                    },
                    "required": ["checks"],
                },
                "reason": {"type": "string"},
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For complete: tool call IDs proving the current result. "
                    "Must be successful, finished, and after the latest file edit.",
                },
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
                capture_goal_checklist(context)
                from deepseek_tui.tools.shell import running_attached_count

                if running_attached_count(context):
                    raise GoalError(
                        "work_pending", "Wait for attached shell work before completing."
                    )
                if (
                    context.subagent_manager is not None
                    and context.subagent_manager.running_count()
                ):
                    raise GoalError("work_pending", "Wait for running subagents before completing.")
                snapshot, _promoted = service.mark_complete(
                    reason,
                    GoalActor.MODEL,
                    evidence=input_data.get("evidence"),
                    audit=input_data.get("audit"),
                )
                return ToolResult(success=True, content=completion_summary_prompt(snapshot))
            if status == "blocked":
                snapshot = service.mark_blocked(reason, GoalActor.MODEL)
                return ToolResult(success=True, content=blocked_reason_prompt(snapshot))
            if status == "requirements":
                snapshot = service.add_requirements(input_data.get("requirements"))
            else:
                raise GoalError("status_invalid", f'Unknown goal status "{status}"')
        except GoalError as exc:
            return ToolResult(success=False, content=exc.message)
        return ToolResult(success=True, content=_json({"goal": snapshot.for_model()}))


class SetGoalBudgetTool(ToolSpec):
    def name(self) -> str:
        return SET_GOAL_BUDGET_NAME

    def description(self) -> str:
        return (
            "Set a turn, output-token, or wall-clock budget on the current goal. "
            "Only call this when the user stated an explicit numeric limit. "
            'Do not invent budgets from vague language like "quickly".'
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
    return [CreateGoalTool(), GetGoalTool(), UpdateGoalTool()]


def _stale_goal_result(service: Any, context: ToolContext) -> ToolResult | None:
    if GOAL_TURN_ID_KEY not in context.metadata:
        return None
    expected = context.metadata.get(GOAL_TURN_ID_KEY)
    snapshot = service.snapshot()
    current_id = None if snapshot is None else snapshot.goal_id
    expected_epoch = context.metadata.get("goal_control_epoch", service.control_epoch)
    if current_id != expected or expected_epoch != service.control_epoch:
        return ToolResult(success=False, content=STALE_GOAL_TOOL_MESSAGE)
    return None


def _opt_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
