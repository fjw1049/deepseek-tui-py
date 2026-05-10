"""Sub-agent card parity tests.

Mirror Rust tests in ``crates/tui/src/tui/widgets/agent_card.rs``
(agent_card.rs:475-672).
"""

from __future__ import annotations

from deepseek_tui.tools.subagent.mailbox import MailboxMessage
from deepseek_tui.tui.widgets.agent_card import (
    DELEGATE_MAX_ACTIONS,
    AgentLifecycle,
    DelegateCard,
    FanoutCard,
    apply_to_delegate,
    apply_to_fanout,
)

# ---------------------------------------------------------------------------
# DelegateCard
# ---------------------------------------------------------------------------


def test_delegate_truncates_to_last_three_actions_with_ellipsis() -> None:
    card = DelegateCard(agent_id="agent_001", agent_type="general")
    card.push_action("read README.md")
    card.push_action("grep TODO")
    card.push_action("edit src/lib.rs")
    assert not card.truncated
    assert len(card.actions) == DELEGATE_MAX_ACTIONS

    card.push_action("write tests")
    card.push_action("run cargo test")
    assert card.truncated
    assert len(card.actions) == DELEGATE_MAX_ACTIONS

    rendered = card.render_lines()
    assert any("…" in line for line in rendered)
    assert not any("read README.md" in line for line in rendered)
    assert any("run cargo test" in line for line in rendered)
    assert any("write tests" in line for line in rendered)
    assert any("edit src/lib.rs" in line for line in rendered)


def test_delegate_terminal_status_renders_summary_row() -> None:
    card = DelegateCard(agent_id="agent_002", agent_type="explore")
    card.push_action("listing files")
    msg = MailboxMessage.completed("agent_002", "scanned 42 files, no TODOs found")
    assert apply_to_delegate(card, msg)
    assert card.status == AgentLifecycle.COMPLETED
    rendered = card.render_lines()
    assert any("scanned 42 files" in line for line in rendered)


def test_delegate_ignores_envelopes_for_other_agents() -> None:
    card = DelegateCard(agent_id="agent_a", agent_type="general")
    other = MailboxMessage.progress("agent_b", "noise")
    assert not apply_to_delegate(card, other)
    assert len(card.actions) == 0


def test_delegate_progress_pushes_action_and_marks_running() -> None:
    card = DelegateCard(agent_id="agent_x", agent_type="general")
    msg = MailboxMessage.progress("agent_x", "scanning files")
    assert apply_to_delegate(card, msg)
    assert card.status == AgentLifecycle.RUNNING
    assert card.actions == ["scanning files"]


def test_delegate_failed_sets_summary_to_error() -> None:
    card = DelegateCard(agent_id="agent_x", agent_type="general")
    msg = MailboxMessage.failed("agent_x", "boom")
    assert apply_to_delegate(card, msg)
    assert card.status == AgentLifecycle.FAILED
    assert card.summary == "boom"


# ---------------------------------------------------------------------------
# FanoutCard
# ---------------------------------------------------------------------------


def test_fanout_dot_grid_renders_stateful_worker_slots() -> None:
    card = FanoutCard(kind="fanout").with_workers(
        ["w_1", "w_2", "w_3", "w_4", "w_5", "w_6", "w_7"]
    )
    card.upsert_worker("w_1", AgentLifecycle.COMPLETED)
    card.upsert_worker("w_2", AgentLifecycle.COMPLETED)
    card.upsert_worker("w_3", AgentLifecycle.RUNNING)
    card.upsert_worker("w_4", AgentLifecycle.FAILED)
    assert card.dot_grid() == "●●◐×○○○"


def test_fanout_aggregate_counts_match_dot_grid() -> None:
    card = FanoutCard(kind="rlm").with_workers(["w_1", "w_2", "w_3", "w_4"])
    card.upsert_worker("w_1", AgentLifecycle.COMPLETED)
    card.upsert_worker("w_2", AgentLifecycle.COMPLETED)
    card.upsert_worker("w_3", AgentLifecycle.COMPLETED)
    card.upsert_worker("w_4", AgentLifecycle.FAILED)
    rendered = card.render_lines()
    stats = next(line for line in rendered if "running" in line and "pending" in line)
    assert "3 done" in stats
    assert "1 failed" in stats
    assert "0 running" in stats
    assert "0 pending" in stats


def test_fanout_apply_inserts_unknown_worker_via_child_spawned() -> None:
    card = FanoutCard(kind="fanout")
    msg = MailboxMessage.child_spawned("root", "agent_late")
    assert apply_to_fanout(card, msg)
    assert len(card.workers) == 1
    assert card.workers[0].agent_id == "agent_late"
    assert card.workers[0].status == AgentLifecycle.PENDING


def test_fanout_started_claims_pending_slot() -> None:
    card = FanoutCard(kind="fanout").with_workers(["task:a", "task:b"])
    started = MailboxMessage.started("agent_live", "general")
    assert apply_to_fanout(card, started)
    assert len(card.workers) == 2
    assert card.workers[0].agent_id == "agent_live"
    assert card.workers[0].status == AgentLifecycle.RUNNING
    assert card.workers[1].agent_id == "task:b"
    assert card.workers[1].status == AgentLifecycle.PENDING


def test_fanout_lifecycle_transitions() -> None:
    card = FanoutCard(kind="fanout").with_workers(["w_1"])
    apply_to_fanout(card, MailboxMessage.started("w_1", "general"))
    assert card.workers[0].status == AgentLifecycle.RUNNING
    apply_to_fanout(card, MailboxMessage.completed("w_1", "ok"))
    assert card.workers[0].status == AgentLifecycle.COMPLETED


def test_fanout_dot_grid_arithmetic_for_various_n() -> None:
    cases = [
        (1, 0, "○"),
        (1, 1, "●"),
        (3, 2, "●●○"),
        (7, 3, "●●●○○○○"),
    ]
    for total, done, expected in cases:
        ids = [f"w_{i}" for i in range(total)]
        card = FanoutCard(kind="fanout").with_workers(ids)
        for i in range(done):
            card.upsert_worker(ids[i], AgentLifecycle.COMPLETED)
        assert card.dot_grid() == expected, f"total={total} done={done}"


def test_fanout_aggregate_status_running_when_pending() -> None:
    card = FanoutCard(kind="fanout").with_workers(["a", "b"])
    assert card.aggregate_status() == AgentLifecycle.RUNNING


def test_fanout_aggregate_status_failed_when_only_failures() -> None:
    card = FanoutCard(kind="fanout").with_workers(["a"])
    card.upsert_worker("a", AgentLifecycle.FAILED)
    assert card.aggregate_status() == AgentLifecycle.FAILED


def test_fanout_aggregate_status_completed_when_done_and_no_failures() -> None:
    card = FanoutCard(kind="fanout").with_workers(["a"])
    card.upsert_worker("a", AgentLifecycle.COMPLETED)
    assert card.aggregate_status() == AgentLifecycle.COMPLETED
