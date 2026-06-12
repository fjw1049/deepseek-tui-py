from __future__ import annotations

from deepseek_tui.integrations.goal import GoalStatus
from deepseek_tui.integrations.goal import GoalJournal
from deepseek_tui.integrations.goal import (
    apply_usage,
    clear_entry,
    create_goal,
    reconstruct_goal,
    set_entry,
    usage_entry,
)


def test_goal_replay_applies_usage_and_budget_limit() -> None:
    goal = create_goal("ship goal support", token_budget=1000)
    entries = [
        set_entry(goal),
        usage_entry(goal, tokens=600, active_seconds=2.5),
        usage_entry(goal, tokens=500, active_seconds=1.5),
    ]

    replayed = reconstruct_goal(entries)

    assert replayed is not None
    assert replayed.goal_id == goal.goal_id
    assert replayed.usage.tokens_used == 1100
    assert replayed.usage.active_seconds == 4.0
    assert replayed.status == GoalStatus.BUDGET_LIMITED


def test_goal_replay_clear_removes_goal() -> None:
    goal = create_goal("temporary")

    assert reconstruct_goal([set_entry(goal), clear_entry(goal)]) is None


def test_goal_journal_round_trips(tmp_path) -> None:
    journal = GoalJournal(tmp_path / "goal.jsonl")
    goal = apply_usage(create_goal("persist me"), 12, 3.0)

    journal.append(set_entry(goal))
    loaded = journal.load_goal()

    assert loaded is not None
    assert loaded.objective == "persist me"
    assert loaded.usage.tokens_used == 12
