"""The model hears about the round limit while it can still act on it."""

from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from tests.engine.test_truncated_rounds import _allow, engine_for

NOTICE = "rounds left"


def reads(count):
    return [
        ToolCall(id=f"r{i}", name="read_file", arguments={"path": "a.txt"}) for i in range(count)
    ]


async def run(tmp_path, limit, replies):
    (tmp_path / "a.txt").write_text("x")
    engine, client = await engine_for(tmp_path, replies)
    engine._handle_approval_flow = _allow
    engine.max_tool_round_trips = limit
    try:
        result = await engine._run_conversation([Message.user("Go")], "test", "sys", None)
    finally:
        await engine.shutdown_session()
    return result, client


def notices(client):
    return [
        index for index, request in enumerate(client.requests)
        if any(NOTICE in str(message.content) for message in request.messages[-1:])
    ]


async def test_notice_arrives_once_with_rounds_to_spare(tmp_path):
    report = "Stopped here: the parser is done, the exporter is not, and I'd try it next. " * 3
    result, client = await run(tmp_path, 25, [*reads(6), report])
    assert notices(client) == [5]
    assert result.assistant_message.text_content() == report


async def test_short_limits_get_no_notice(tmp_path):
    _, client = await run(tmp_path, 10, [*reads(3), "Done."])
    assert notices(client) == []
