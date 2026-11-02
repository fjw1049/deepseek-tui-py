"""A UI turn re-observes one page dozens of times; only the latest view needs to stay."""

import json

from deepseek_tui.engine.capacity import fold_superseded_observations
from deepseek_tui.protocol.messages import Message, Role, ToolResultBlock, ToolUseBlock


def observation(url="file:///w/index.html", text="x" * 2000, **fields):
    return json.dumps({"success": True, "observation": {
        "observation_id": "o", "url": url, "text": text, "elements": [], **fields}})


def history(*results, tool="browser_use"):
    messages = [Message.user("go")]
    for index, content in enumerate(results):
        messages.append(Message(role=Role.ASSISTANT, content=[
            ToolUseBlock(id=f"c{index}", name=tool, input={})]))
        messages.append(Message.tool_result(f"c{index}", content))
    return messages


def bodies(messages):
    return [b.content for m in messages for b in m.content if isinstance(b, ToolResultBlock)]


def test_only_the_latest_view_of_a_page_stays():
    messages = history(observation(), observation(), observation(text="latest"))
    assert fold_superseded_observations(messages, min_reclaim=0) > 0
    first, second, last = bodies(messages)
    assert first.startswith("[Earlier observation of file:///w/index.html")
    assert second.startswith("[Earlier observation")
    assert json.loads(last)["observation"]["text"] == "latest"


def test_another_page_keeps_what_was_read_there():
    messages = history(observation("http://x/1"), observation("http://x/2"))
    assert fold_superseded_observations(messages, min_reclaim=0) == 0


def test_pages_of_one_document_and_scoped_reads_are_different_views():
    messages = history(
        observation(text_offset=0), observation(text_offset=2000),
        observation(scope_selector="#list"), observation(frame_id="f1"),
    )
    assert fold_superseded_observations(messages, min_reclaim=0) == 0


def test_the_same_url_in_another_tab_is_another_view():
    # Two tabs of one app can hold different unsaved state.
    messages = history(observation(tab_id="a"), observation(tab_id="b", text="short"))
    assert fold_superseded_observations(messages, min_reclaim=0) == 0


def test_a_narrower_read_does_not_replace_a_fuller_one():
    messages = history(observation(level="full"), observation(level="interactive", text="short"))
    assert fold_superseded_observations(messages, min_reclaim=0) == 0


def test_a_rerender_of_the_same_page_is_still_superseded():
    messages = history(observation(tab_id="a", control_generation=1),
                       observation(tab_id="a", control_generation=2))
    assert fold_superseded_observations(messages, min_reclaim=0) > 0


def test_an_element_detail_is_not_replaced_by_a_later_observation():
    messages = history(observation(details=True), observation())
    assert fold_superseded_observations(messages, min_reclaim=0) == 0


def test_other_tools_and_non_json_results_are_left_alone():
    messages = history(observation(), observation(), tool="read_file")
    assert fold_superseded_observations(messages, min_reclaim=0) == 0
    messages = history("plain failure", observation())
    assert fold_superseded_observations(messages, min_reclaim=0) == 0


def test_small_savings_wait_so_the_prefix_cache_is_not_broken_for_them():
    messages = history(observation(), observation())
    assert fold_superseded_observations(messages) == 0
    assert bodies(messages)[0].startswith("{")
    many = history(*[observation() for _ in range(12)])
    assert fold_superseded_observations(many) >= 16_000


def test_a_folded_body_is_not_counted_twice():
    messages = history(*[observation() for _ in range(12)])
    assert fold_superseded_observations(messages) > 0
    assert fold_superseded_observations(messages, min_reclaim=0) == 0


def test_tool_call_pairing_survives():
    messages = history(observation(), observation())
    fold_superseded_observations(messages, min_reclaim=0)
    assert [m.role for m in messages].count(Role.TOOL) == 2
    assert [b.tool_use_id for m in messages for b in m.content
            if isinstance(b, ToolResultBlock)] == ["c0", "c1"]
