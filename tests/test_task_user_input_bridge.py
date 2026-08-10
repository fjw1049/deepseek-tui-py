"""Background task user-input bridge + auto-approve for plan gates."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deepseek_tui.engine.dispatch import (
    bridge_background_user_input,
    synthetic_plan_user_input_response,
    task_auto_approves_user_input,
)
from deepseek_tui.engine.events import UserInputRequiredEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.server.approval import PendingUserInputRecord, UserInputBridge
from deepseek_tui.tools.plan_mode import (
    ENTER_APPROVE_VALUE,
    ENTER_PLAN_MODE_NAME,
    ENTER_QUESTION_ID,
    EXIT_ACCEPT_YOLO,
    EXIT_PLAN_MODE_NAME,
    EXIT_QUESTION_ID,
)
from deepseek_tui.tools.task.models import ExecutionTask


def _task(**kwargs: Any) -> ExecutionTask:
    base = dict(
        id="task_1",
        prompt="do something",
        model="deepseek-chat",
        workspace="/tmp",
        mode_label="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=False,
        thread_id="thread_1",
    )
    base.update(kwargs)
    return ExecutionTask(**base)


def test_synthetic_enter_and_exit_plan_answers() -> None:
    enter = synthetic_plan_user_input_response(ENTER_PLAN_MODE_NAME)
    assert enter == {
        "answers": [{"question_id": ENTER_QUESTION_ID, "value": ENTER_APPROVE_VALUE}]
    }
    exit_resp = synthetic_plan_user_input_response(EXIT_PLAN_MODE_NAME)
    assert exit_resp == {
        "answers": [{"question_id": EXIT_QUESTION_ID, "value": EXIT_ACCEPT_YOLO}]
    }
    assert synthetic_plan_user_input_response(None) is None
    assert synthetic_plan_user_input_response("request_user_input") is None


def test_task_auto_approves_user_input() -> None:
    assert task_auto_approves_user_input(_task(auto_approve=True)) is True
    assert task_auto_approves_user_input(_task(mode_label="yolo")) is True
    assert task_auto_approves_user_input(_task()) is False


@pytest.mark.asyncio
async def test_bridge_auto_approves_enter_plan() -> None:
    handle = EngineHandle()
    fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    handle.pending_user_inputs["call_1"] = fut
    event = UserInputRequiredEvent(
        tool_call_id="call_1",
        questions=[{"id": ENTER_QUESTION_ID, "header": "Plan", "question": "?", "options": []}],
        purpose=ENTER_PLAN_MODE_NAME,
    )
    await bridge_background_user_input(
        event, task=_task(auto_approve=True), handle=handle
    )
    assert fut.done()
    assert fut.result()["answers"][0]["value"] == ENTER_APPROVE_VALUE


@pytest.mark.asyncio
async def test_bridge_surfaces_to_origin_thread() -> None:
    bridge = UserInputBridge()
    emitted: list[dict[str, Any]] = []

    class FakeThreadManager:
        async def emit_bridged_user_input(
            self,
            thread_id: str,
            request_id: str,
            questions: list[dict[str, object]],
            *,
            purpose: str | None = None,
            task_id: str | None = None,
        ) -> None:
            emitted.append(
                {
                    "thread_id": thread_id,
                    "request_id": request_id,
                    "questions": questions,
                    "purpose": purpose,
                    "task_id": task_id,
                }
            )

    mgr = SimpleNamespace(
        user_input_bridge=bridge, thread_manager=FakeThreadManager()
    )
    task = _task(task_manager=mgr)
    handle = EngineHandle()
    fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    handle.pending_user_inputs["call_2"] = fut
    questions = [
        {
            "id": ENTER_QUESTION_ID,
            "header": "规划模式",
            "question": "进入？",
            "options": [{"label": "进入", "value": "enter"}],
        }
    ]
    event = UserInputRequiredEvent(
        tool_call_id="call_2",
        questions=questions,
        purpose=ENTER_PLAN_MODE_NAME,
    )
    await bridge_background_user_input(event, task=task, handle=handle)
    assert not fut.done()
    assert len(emitted) == 1
    assert emitted[0]["thread_id"] == "thread_1"
    assert emitted[0]["task_id"] == "task_1"
    pending = bridge.list_pending(thread_id="thread_1")
    assert len(pending) == 1
    assert pending[0]["request_id"] == "call_2"

    assert bridge.resolve(
        "call_2",
        answers=[{"question_id": ENTER_QUESTION_ID, "value": ENTER_APPROVE_VALUE}],
    )
    await asyncio.sleep(0)
    assert fut.done()
    assert fut.result()["answers"][0]["value"] == ENTER_APPROVE_VALUE


@pytest.mark.asyncio
async def test_bridge_errors_without_origin_thread() -> None:
    handle = EngineHandle()
    fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    handle.pending_user_inputs["call_3"] = fut
    event = UserInputRequiredEvent(
        tool_call_id="call_3",
        questions=[{"id": "q", "header": "h", "question": "?", "options": []}],
        purpose=ENTER_PLAN_MODE_NAME,
    )
    await bridge_background_user_input(
        event, task=_task(thread_id=None, auto_approve=False), handle=handle
    )
    assert fut.done()
    assert "no origin thread" in fut.result()["error"]


def test_user_input_bridge_cancel_for_thread() -> None:
    async def _run() -> None:
        bridge = UserInputBridge()
        fut = bridge.register(
            "req_a",
            meta=PendingUserInputRecord(
                thread_id="t1",
                questions=[],
                purpose=ENTER_PLAN_MODE_NAME,
                task_id="task_a",
            ),
        )
        bridge.cancel_for_thread("t1")
        assert fut.done()
        assert fut.result() == {"cancelled": True}

    asyncio.run(_run())
