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


async def test_a_planned_step_after_few_rounds_is_taken(tmp_path):
    # Real stops users had to resume with 继续, well below the short-stop round count.
    result, client, reminded = await run(tmp_path, [
        *reads(2), "高德弹出了登录框挡住页面。我先关掉登录框，把搜索结果调出来看看。",
        *reads(1, "more"), REPORT,
    ])
    assert reminded == 1
    assert result.assistant_message.text_content() == REPORT


async def test_planned_steps_are_nudged_at_most_twice(tmp_path):
    result, _, reminded = await run(tmp_path, [
        *reads(1), "现在触发一次搜索。", "再看两家的评分。", "点开排第一的那家。",
    ])
    assert reminded == 2
    assert result.assistant_message.text_content() == "点开排第一的那家。"


async def test_answers_questions_and_offers_end_the_turn(tmp_path):
    for reply in ("页面标题是 Example Domain。", "要我继续查评分吗？", "如果需要，我再帮你查评分。"):
        _, _, reminded = await run(tmp_path, [*reads(1), reply])
        assert reminded == 0, reply


def test_next_step_announcements_from_real_stops():
    from deepseek_tui.engine.orchestrator.core import _announces_next_step

    for text in ("控制权有变化，先读状态。", "弹窗关掉了。现在触发一次搜索。",
                 "已按评分排序。点开排第一的那家看具体评分和详情。",
                 "百度接口需要验证码，拿不到评分。我换个数据源试试大众点评。",
                 "高德也弹出了滑块人机验证。我先试试滑块能否用键盘移动。",
                 "Let me check the results page."):
        assert _announces_next_step(text), text
    for text in ("页面标题是 Example Domain。", "已经播放七里香。", "要我继续吗？",
                 "如需更多推荐，我再帮你查。", "Done."):
        assert not _announces_next_step(text), text
