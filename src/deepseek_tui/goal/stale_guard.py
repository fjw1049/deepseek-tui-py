from __future__ import annotations

from deepseek_tui.goal.models import GoalStatus, ThreadGoal


def is_follow_up_stale(goal: ThreadGoal | None, goal_id: str) -> bool:
    return goal is None or goal.goal_id != goal_id or goal.status != GoalStatus.ACTIVE
