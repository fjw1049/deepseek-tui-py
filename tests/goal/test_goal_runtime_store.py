from __future__ import annotations

from deepseek_tui.app_server.runtime_threads import RuntimeThreadStore
from deepseek_tui.goal.models import GoalStatus
from deepseek_tui.goal.persistence import GoalJournal
from deepseek_tui.goal.state import create_goal, set_entry


def test_runtime_store_copies_goal_journal_for_fork_and_pauses_active_goal(tmp_path) -> None:
    store = RuntimeThreadStore(tmp_path)
    source = GoalJournal(store.goal_journal_path("source"))
    source_goal = create_goal("branch carefully")
    source.append(set_entry(source_goal))

    store.copy_goal_journal_for_fork("source", "target")

    copied = GoalJournal(store.goal_journal_path("target")).load_goal()
    assert copied is not None
    assert copied.goal_id == source_goal.goal_id
    assert copied.objective == source_goal.objective
    assert copied.status == GoalStatus.PAUSED
