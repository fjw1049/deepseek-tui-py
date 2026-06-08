from __future__ import annotations

from deepseek_tui.goal.models import ThreadGoal

CONTINUATION_MARKER = "<deepseek_goal_continuation"


def continuation_prompt(goal: ThreadGoal) -> str:
    return (
        f'{CONTINUATION_MARKER} goal_id="{goal.goal_id}">\n'
        "Continue working on the active goal below. First audit whether it is "
        "already genuinely complete. If it is complete, call update_goal with "
        'status="complete". Otherwise continue the next useful step.\n\n'
        "<goal_objective>\n"
        f"{goal.objective}\n"
        "</goal_objective>\n"
        "</deepseek_goal_continuation>"
    )


def budget_limited_message(goal: ThreadGoal) -> str:
    return (
        "The active goal has reached its token budget. Pause autonomous work "
        "and summarize the current state for the user."
    )
