"""Tests for enter_plan_mode / exit_plan_mode helpers and catalog gates."""

from __future__ import annotations

from deepseek_tui.config import Config
from deepseek_tui.engine.dispatch import should_stop_after_plan_tool
from deepseek_tui.engine.tools import should_default_defer_tool
from deepseek_tui.tools.plan_mode import (
    ENTER_APPROVE_VALUE,
    EXIT_ACCEPT_AGENT,
    EXIT_ACCEPT_YOLO,
    EXIT_LEAVE,
    EXIT_REVISE,
    parse_enter_plan_response,
    parse_exit_plan_response,
)
from deepseek_tui.tools.registry import build_default_registry


def test_parse_enter_plan_response() -> None:
    assert (
        parse_enter_plan_response(
            {"answers": [{"question_id": "enter_plan", "value": ENTER_APPROVE_VALUE}]}
        )
        is True
    )
    assert (
        parse_enter_plan_response(
            {"answers": [{"question_id": "enter_plan", "value": "Stay in agent"}]}
        )
        is False
    )
    assert (
        parse_enter_plan_response(
            {"answers": [{"question_id": "enter_plan", "label": "进入规划模式"}]}
        )
        is True
    )
    assert parse_enter_plan_response({"answers": []}) is None


def test_parse_exit_plan_response() -> None:
    assert (
        parse_exit_plan_response(
            {"answers": [{"question_id": "exit_plan", "value": EXIT_ACCEPT_AGENT}]}
        )
        == EXIT_ACCEPT_AGENT
    )
    assert (
        parse_exit_plan_response(
            {
                "answers": [
                    {"question_id": "exit_plan", "label": "Accept plan (YOLO)"}
                ]
            }
        )
        == EXIT_ACCEPT_YOLO
    )
    assert (
        parse_exit_plan_response(
            {"answers": [{"question_id": "exit_plan", "value": EXIT_REVISE}]}
        )
        == EXIT_REVISE
    )
    assert (
        parse_exit_plan_response(
            {"answers": [{"question_id": "exit_plan", "value": EXIT_LEAVE}]}
        )
        == EXIT_LEAVE
    )
    assert (
        parse_exit_plan_response(
            {"answers": [{"question_id": "exit_plan", "label": "修改计划"}]}
        )
        == EXIT_REVISE
    )


def test_questions_follow_locale() -> None:
    from deepseek_tui.tools.plan_mode import enter_plan_questions, exit_plan_questions

    zh_enter = enter_plan_questions("zh")[0]
    en_enter = enter_plan_questions("en")[0]
    assert "规划" in str(zh_enter["header"])
    assert "Plan" in str(en_enter["header"])
    zh_exit = exit_plan_questions("zh")[0]
    assert "计划" in str(zh_exit["header"])
    assert zh_exit["options"][0]["value"] == EXIT_ACCEPT_AGENT


def test_update_plan_no_longer_stops_turn() -> None:
    assert should_stop_after_plan_tool("plan", "update_plan", True) is False
    assert should_stop_after_plan_tool("plan", "exit_plan_mode", True) is False


def test_enter_exit_always_active() -> None:
    assert should_default_defer_tool("enter_plan_mode", "agent") is False
    assert should_default_defer_tool("exit_plan_mode", "plan") is False


def test_plan_catalog_has_exit_not_enter() -> None:
    names = set(build_default_registry(Config(), mode="plan").names())
    assert "exit_plan_mode" in names
    assert "enter_plan_mode" not in names


def test_agent_catalog_has_enter() -> None:
    names = set(build_default_registry(Config(), mode="agent").names())
    assert "enter_plan_mode" in names
    assert "exit_plan_mode" in names
