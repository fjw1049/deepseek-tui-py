from __future__ import annotations

import json
from typing import Any

from deepseek_tui.goal.controller import GoalController
from deepseek_tui.tools.base import ToolCapability, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

GOAL_CONTROLLER_KEY = "goal_controller"


def goal_controller_from_context(context: ToolContext) -> GoalController:
    controller = context.metadata.get(GOAL_CONTROLLER_KEY)
    if not isinstance(controller, GoalController):
        raise RuntimeError("goal runtime is not attached")
    return controller


class GetGoalTool(ToolSpec):
    def name(self) -> str:
        return "get_goal"

    def description(self) -> str:
        return "Get the current thread goal, status, token budget, and usage."

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        snapshot = goal_controller_from_context(context).snapshot()
        return ToolResult(True, json.dumps(snapshot, ensure_ascii=False))


class CreateGoalTool(ToolSpec):
    def name(self) -> str:
        return "create_goal"

    def description(self) -> str:
        return (
            "Create a thread goal with an optional token budget. "
            "Fails if an active goal already exists unless replace_existing=true."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "token_budget": {"type": "integer", "minimum": 1000},
                "replace_existing": {"type": "boolean", "default": False},
            },
            "required": ["objective"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return []

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            budget = (
                int(input_data["token_budget"])
                if input_data.get("token_budget") is not None
                else None
            )
            replace = bool(input_data.get("replace_existing", False))
            goal = goal_controller_from_context(context).create(
                str(input_data.get("objective") or ""),
                budget,
                replace_existing=replace,
            )
        except ValueError as exc:
            return ToolResult(False, str(exc))
        return ToolResult(True, json.dumps(goal.to_json(), ensure_ascii=False))


class UpdateGoalTool(ToolSpec):
    def name(self) -> str:
        return "update_goal"

    def description(self) -> str:
        return "Mark the current goal complete after verifying the objective is genuinely done."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["complete"]},
                "reason": {"type": "string"},
            },
            "required": ["status"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return []

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        if input_data.get("status") != "complete":
            return ToolResult(False, "model may only set goal status to complete")
        goal = goal_controller_from_context(context).complete(
            str(input_data.get("reason") or "verified complete")
        )
        if goal is None:
            return ToolResult(False, "no active goal")
        return ToolResult(True, json.dumps(goal.to_json(), ensure_ascii=False))


def goal_tools() -> list[ToolSpec]:
    return [GetGoalTool(), CreateGoalTool(), UpdateGoalTool()]
