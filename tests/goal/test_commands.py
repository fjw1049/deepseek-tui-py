"""Shared /goal command grammar."""

from __future__ import annotations

from deepseek_tui.goal.commands import parse_goal_command


def test_status_and_controls() -> None:
    assert parse_goal_command("").kind == "status"
    assert parse_goal_command("status").kind == "status"
    assert parse_goal_command("pause").kind == "pause"
    assert parse_goal_command("resume").kind == "resume"
    assert parse_goal_command("cancel").kind == "cancel"
    assert parse_goal_command("reopen").kind == "reopen"


def test_budget_command() -> None:
    command = parse_goal_command("budget tokens 2000 turns 5 seconds 60")
    assert command.kind == "budget"
    assert command.token_budget == 2000
    assert command.turn_budget == 5
    assert command.wall_clock_budget_ms == 60000
    for text in ("budget", "budget tokens", "budget tokens 0", "budget turns nope"):
        assert parse_goal_command(text).kind == "error"


def test_create_and_replace() -> None:
    created = parse_goal_command("Ship feature X")
    assert created.kind == "create"
    assert created.objective == "Ship feature X"
    assert created.replace is False
    replaced = parse_goal_command("replace Ship feature Y")
    assert replaced.kind == "create"
    assert replaced.replace is True
    assert replaced.objective == "Ship feature Y"


def test_reserved_word_as_objective() -> None:
    parsed = parse_goal_command("-- pause this deploy")
    assert parsed.kind == "create"
    assert parsed.objective == "pause this deploy"


def test_next_queue_commands() -> None:
    added = parse_goal_command("next Write the docs")
    assert added.kind == "next-add"
    assert added.objective == "Write the docs"
    assert parse_goal_command("next manage").kind == "next-manage"
    deleted = parse_goal_command("next manage delete 2")
    assert deleted.kind == "next-delete"
    assert deleted.index == 2
    moved = parse_goal_command("next manage move 2 1")
    assert moved.kind == "next-move"
    assert moved.index == 2
    assert moved.dest == 1


def test_errors() -> None:
    empty = parse_goal_command("replace")
    assert empty.kind == "error"
    too_long = parse_goal_command("x" * 4001)
    assert too_long.kind == "error"
    assert parse_goal_command("next").kind == "error"
