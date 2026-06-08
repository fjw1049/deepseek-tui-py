from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.goal.models import GoalStatus, ThreadGoal
from deepseek_tui.goal.prompts import continuation_prompt


@dataclass(slots=True)
class GoalFollowUp:
    goal_id: str
    content: str


def plan_follow_up(goal: ThreadGoal | None) -> GoalFollowUp | None:
    if goal is None or goal.status != GoalStatus.ACTIVE:
        return None
    return GoalFollowUp(goal_id=goal.goal_id, content=continuation_prompt(goal))
