"""Tests for enter_plan_mode / exit_plan_mode helpers and catalog gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config import Config
from deepseek_tui.engine.dispatch import should_stop_after_plan_tool
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.plan_mode import (
    APPROVED_PLAN_MARKER,
    ENTER_APPROVE_VALUE,
    EXIT_ACCEPT_AGENT,
    EXIT_ACCEPT_YOLO,
    EXIT_LEAVE,
    EXIT_REVISE,
    parse_enter_plan_response,
    parse_exit_plan_response,
    plan_file_exists,
    resolve_plan_file_path,
    sync_approved_plan_reminder,
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


def test_plan_catalog_has_exit_not_enter() -> None:
    names = set(build_default_registry(Config(), mode="plan").names())
    assert "exit_plan_mode" in names
    assert "enter_plan_mode" not in names


def test_agent_catalog_has_enter() -> None:
    names = set(build_default_registry(Config(), mode="agent").names())
    assert "enter_plan_mode" in names
    assert "exit_plan_mode" in names


def test_tui_resolves_workspace_plan(tmp_path: Path) -> None:
    assert resolve_plan_file_path(tmp_path, {}) == tmp_path / ".deepseek" / "plan.md"


def test_thread_plan_does_not_fall_back_to_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deepseek_tui.config.paths import user_thread_plan_path

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    leftover = tmp_path / ".deepseek" / "plan.md"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("other thread leftover", encoding="utf-8")
    meta = {"runtime_thread_id": "thr_cccc3333"}
    assert resolve_plan_file_path(tmp_path, meta) == user_thread_plan_path(
        "thr_cccc3333"
    )
    assert plan_file_exists(tmp_path, meta) is False


def test_invalid_thread_id_does_not_use_workspace_plan(tmp_path: Path) -> None:
    leftover = tmp_path / ".deepseek" / "plan.md"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("nope", encoding="utf-8")
    meta = {"runtime_thread_id": "../evil"}
    assert resolve_plan_file_path(tmp_path, meta) is None
    assert plan_file_exists(tmp_path, meta) is False


@pytest.mark.asyncio
async def test_update_plan_isolates_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deepseek_tui.config.paths import user_thread_plan_path
    from deepseek_tui.tools.knowledge import PlanUpdateTool
    from deepseek_tui.tools.registry import ToolContext

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    tool = PlanUpdateTool()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx_a = ToolContext(
        working_directory=workspace,
        metadata={"runtime_thread_id": "thr_aaaa1111"},
    )
    ctx_b = ToolContext(
        working_directory=workspace,
        metadata={"runtime_thread_id": "thr_bbbb2222"},
    )
    await tool.execute({"plan": "plan A only"}, ctx_a)
    await tool.execute({"plan": "plan B only"}, ctx_b)
    assert user_thread_plan_path("thr_aaaa1111").read_text(encoding="utf-8") == (
        "plan A only"
    )
    assert user_thread_plan_path("thr_bbbb2222").read_text(encoding="utf-8") == (
        "plan B only"
    )
    assert not (workspace / ".deepseek" / "plan.md").exists()


def test_approved_plan_reminder_injects_path_not_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deepseek_tui.config.paths import user_thread_plan_path

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    path = user_thread_plan_path("thr_dddd4444")
    path.parent.mkdir(parents=True)
    path.write_text("SECRET PLAN BODY\n- do the thing", encoding="utf-8")
    messages: list[Message] = [Message.user("continue")]
    meta = {
        "runtime_thread_id": "thr_dddd4444",
        "approved_plan": True,
    }
    sync_approved_plan_reminder(
        messages, mode="agent", working_directory=tmp_path, metadata=meta
    )
    assert len(messages) == 2
    text = messages[-1].text_content()
    assert APPROVED_PLAN_MARKER in text
    assert str(path) in text
    assert "SECRET PLAN BODY" not in text
    sync_approved_plan_reminder(
        messages, mode="agent", working_directory=tmp_path, metadata=meta
    )
    assert len(messages) == 2


def test_approved_plan_reminder_skipped_when_unapproved_or_plan_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deepseek_tui.config.paths import user_thread_plan_path
    from deepseek_tui.engine import reminders
    from deepseek_tui.tools.plan_mode import build_approved_plan_reminder_body

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    path = user_thread_plan_path("thr_eeee5555")
    path.parent.mkdir(parents=True)
    path.write_text("body", encoding="utf-8")
    leftover = reminders.reminder_message(
        reminders.APPROVED_PLAN, build_approved_plan_reminder_body(path)
    )
    meta = {"runtime_thread_id": "thr_eeee5555", "approved_plan": False}
    messages = [Message.user("hi"), leftover]
    sync_approved_plan_reminder(
        messages, mode="agent", working_directory=tmp_path, metadata=meta
    )
    assert leftover not in messages

    messages = [Message.user("hi")]
    sync_approved_plan_reminder(
        messages,
        mode="plan",
        working_directory=tmp_path,
        metadata={**meta, "approved_plan": True},
    )
    assert all(APPROVED_PLAN_MARKER not in m.text_content() for m in messages)


def test_tui_does_not_inject_approved_plan_reminder(tmp_path: Path) -> None:
    plan = tmp_path / ".deepseek" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("tui plan", encoding="utf-8")
    messages = [Message.user("go")]
    sync_approved_plan_reminder(
        messages,
        mode="agent",
        working_directory=tmp_path,
        metadata={"approved_plan": True},
    )
    assert len(messages) == 1


def test_delete_thread_tree_removes_plan_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    from deepseek_tui.config.paths import user_thread_plan_path
    from deepseek_tui.server.data_inventory import delete_thread_tree
    from deepseek_tui.server.threads.models import ThreadRecord
    from deepseek_tui.server.threads.store import RuntimeThreadStore
    from deepseek_tui.workspace.turn_checkpoints import TurnCheckpointStore

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    store = RuntimeThreadStore(tmp_path / "store")
    checkpoints = TurnCheckpointStore(tmp_path / "checkpoints")
    tid = "thr_ffff6666"
    now = datetime.now(timezone.utc)
    store.save_thread(
        ThreadRecord(
            id=tid,
            created_at=now,
            updated_at=now,
            model="deepseek-chat",
            workspace=str(tmp_path),
        )
    )
    plan = user_thread_plan_path(tid)
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# plan\n", encoding="utf-8")
    delete_thread_tree(store, checkpoints, tid)
    assert not plan.exists()
