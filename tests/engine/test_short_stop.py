"""A long turn that ends on one line gets one chance to carry on or report properly.

Measured on 345 real turns, every stop this catches had announced work it never did.
"""

from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from tests.engine.test_truncated_rounds import _allow, engine_for

NOTICES = ("brief for a turn", "announces a next step")
REPORT = "Finished the page and tested it in the browser. " * 6


def reads(count, prefix="r"):
    return [
        ToolCall(id=f"{prefix}{i}", name="read_file", arguments={"path": "a.txt"})
        for i in range(count)
    ]


async def run(tmp_path, replies):
    (tmp_path / "a.txt").write_text("x")
    engine, client = await engine_for(tmp_path, replies)
    engine._handle_approval_flow = _allow
    try:
        result = await engine._run_conversation([Message.user("Go")], "test", "sys", None)
    finally:
        await engine.shutdown_session()
    reminded = sum(any(n in str(request.messages[-1].content) for n in NOTICES)
                   for request in client.requests)
    return result, client, reminded


async def test_announced_step_is_taken_instead_of_ending_the_turn(tmp_path):
    result, client, reminded = await run(tmp_path, [
        *reads(5), "接着补前端的撤销面板。", *reads(1, "more"), REPORT,
    ])
    assert reminded == 1
    assert len(client.requests) == 8
    assert result.assistant_message.text_content() == REPORT


async def test_it_asks_once_and_then_the_turn_may_end(tmp_path):
    result, _, reminded = await run(tmp_path, [*reads(5), "接着补页面。", "没有别的了。"])
    assert reminded == 1
    assert result.assistant_message.text_content() == "没有别的了。"


async def test_a_short_turn_may_answer_briefly(tmp_path):
    _, client, reminded = await run(tmp_path, [*reads(4), "Done."])
    assert reminded == 0
    assert len(client.requests) == 5


async def test_a_full_report_ends_the_turn(tmp_path):
    _, client, reminded = await run(tmp_path, [*reads(5), REPORT])
    assert reminded == 0
    assert len(client.requests) == 6


async def test_completion_and_user_handoff_do_not_force_tools(tmp_path):
    for reply in ("我现在已经完成了修改。", "现在点击保存即可。", "下一步由你在手机上确认登录。"):
        result, client, reminded = await run(tmp_path, [*reads(1), reply])
        assert reminded == 0
        assert len(client.requests) == 2
        assert result.assistant_message.text_content() == reply
