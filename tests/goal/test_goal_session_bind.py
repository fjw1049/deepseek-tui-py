from __future__ import annotations

import uuid

from deepseek_tui.goal.controller import GoalController
from deepseek_tui.goal.models import GoalStatus
from deepseek_tui.goal.persistence import (
    GoalJournal,
    copy_goal_journal_for_fork,
    goal_journal_path,
    resolve_goal_thread_id,
)
from deepseek_tui.goal.state import create_goal, set_entry


def test_resolve_goal_thread_id_prefers_memory_thread_id(tmp_path) -> None:
    session_id = "session-abc123"
    journal = GoalJournal(goal_journal_path(tmp_path, session_id))
    journal.append(set_entry(create_goal("legacy goal")))

    resolved = resolve_goal_thread_id(
        {"memory_thread_id": session_id},
        fallback_id="current",
        workspace=tmp_path,
    )

    assert resolved == session_id


def test_resolve_goal_thread_id_uses_only_journal_when_metadata_generic(tmp_path) -> None:
    lone_id = "abc123deadbeef"
    GoalJournal(goal_journal_path(tmp_path, lone_id)).append(
        set_entry(create_goal("only journal"))
    )

    resolved = resolve_goal_thread_id({}, fallback_id="current", workspace=tmp_path)

    assert resolved == lone_id


def test_tui_fork_copies_journal_and_pauses_active_goal(tmp_path) -> None:
    source_id = "source-session"
    source = GoalJournal(goal_journal_path(tmp_path, source_id))
    source.append(set_entry(create_goal("fork me")))

    fork_id = uuid.uuid4().hex
    copy_goal_journal_for_fork(tmp_path, source_id, fork_id)

    source_goal = GoalJournal(goal_journal_path(tmp_path, source_id)).load_goal()
    fork_goal = GoalJournal(goal_journal_path(tmp_path, fork_id)).load_goal()

    assert source_goal is not None
    assert source_goal.status == GoalStatus.ACTIVE
    assert fork_goal is not None
    assert fork_goal.goal_id == source_goal.goal_id
    assert fork_goal.status == GoalStatus.PAUSED
    assert fork_goal.reason == "paused after thread fork"


def test_rebind_after_fork_uses_new_journal(tmp_path) -> None:
    source_id = "resume-source"
    GoalJournal(goal_journal_path(tmp_path, source_id)).append(
        set_entry(create_goal("branch"))
    )
    fork_id = uuid.uuid4().hex
    copy_goal_journal_for_fork(tmp_path, source_id, fork_id)

    controller = GoalController(tmp_path, fork_id)
    controller.rebind(thread_id=fork_id)

    assert controller.current is not None
    assert controller.current.status == GoalStatus.PAUSED
    assert controller.current.objective == "branch"
