"""Goal Mode — structured autonomous objectives."""

from deepseek_tui.goal.commands import ParsedGoalCommand, parse_goal_command
from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.types import (
    GOAL_CONTROL_TOOL_NAMES,
    GOAL_SERVICE_KEY,
    GOAL_TOOL_NAMES,
    GoalError,
    GoalSnapshot,
    GoalStatus,
)

__all__ = [
    "GOAL_CONTROL_TOOL_NAMES",
    "GOAL_SERVICE_KEY",
    "GOAL_TOOL_NAMES",
    "GoalError",
    "GoalService",
    "GoalSnapshot",
    "GoalStatus",
    "ParsedGoalCommand",
    "parse_goal_command",
]
