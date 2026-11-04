"""UI answers finish once; explicit questions still wait and resume."""

import asyncio

import pytest

from deepseek_tui.engine.events import TextDeltaEvent, UserInputRequiredEvent
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from tests.engine.test_ui_task_turns import desktop_engine, look, names


async def test_explicit_question_waits_and_resumes(tmp_path):
    question = ToolCall(
        id="ask",
        name="request_user_input",
        arguments={
            "kind": "information",
            "questions": [{"header": "目标", "id": "destination", "question": "保存到哪个目录？"}],
        },
    )
    engine, client = await desktop_engine(tmp_path, [look(), question, "已按你的选择处理。"])

    async def answer():
        async for event in engine.handle.events():
            if isinstance(event, UserInputRequiredEvent):
                break
        assert len(client.requests) == 2
        assert engine.handle.resolve_user_input("ask", {"answers": {"destination": "归档"}})

    responder = asyncio.create_task(answer())
    try:
        result = await asyncio.wait_for(
            engine._run_conversation([Message.user("保存这份报告")], "test", "sys", None), 5
        )
        await responder
        assert result.assistant_message.text_content() == "已按你的选择处理。"
        assert len(client.requests) == 3
        assert not engine.handle.pending_user_inputs
    finally:
        responder.cancel()
        await engine.shutdown_session()


@pytest.mark.parametrize(
    "final",
    [
        "任务已经完成。",
        "已核对所需信息。" * 40,
        "页面上有登录入口，但所需公开信息已读取。",
        "你已拒绝授权，无法继续，任务未完成。",
        "结果已保存；以后也可以导出另一种格式。",
        "仍然只用文字向你提问？",  # Prose does not authorize the runtime to invent a question.
    ],
)
@pytest.mark.parametrize("tool_rounds", [1, 5])
async def test_answer_streams_once_without_post_answer_review(tmp_path, final, tool_rounds):
    engine, client = await desktop_engine(
        tmp_path, [*[look(str(i)) for i in range(tool_rounds)], final]
    )
    try:
        result = await engine._run_conversation([Message.user("检查界面")], "test", "sys", None)
        assert result.assistant_message.text_content() == final
        assert len(client.requests) == tool_rounds + 1
        streamed = [e.text for e in engine.handle.drain_events() if isinstance(e, TextDeltaEvent)]
        assert streamed == [final]
        assert "request_user_input" in names(client.requests[-1])
        assert not engine.handle.pending_user_inputs
        assert not engine.tool_context.metadata["turn_facts"].assistance_requests
    finally:
        await engine.shutdown_session()


async def test_unavailable_question_tool_does_not_trigger_review(tmp_path):
    engine, client = await desktop_engine(
        tmp_path, [look(), "缺少权限。"], drop=("request_user_input",)
    )
    try:
        await engine._run_conversation([Message.user("检查界面")], "test", "sys", None)
        assert len(client.requests) == 2
    finally:
        await engine.shutdown_session()


async def test_unattended_explicit_request_is_saved_without_waiting(tmp_path):
    ask = ToolCall(
        id="ask",
        name="request_user_input",
        arguments={"kind": "action", "surface": "desktop", "reason": "请在系统权限面板完成授权。"},
    )
    engine, client = await desktop_engine(tmp_path, [look(), ask])
    engine.tool_context.metadata["unattended"] = True
    try:
        result = await asyncio.wait_for(
            engine._run_conversation([Message.user("检查界面")], "test", "sys", None), 5
        )
        assert result.task_outcome["status"] == "needs_assistance"
        assert result.task_outcome["requests"] == [ask.arguments]
        assert len(client.requests) == 2
    finally:
        await engine.shutdown_session()
