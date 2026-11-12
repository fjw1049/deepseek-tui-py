from types import SimpleNamespace

import pytest

from deepseek_tui.engine.capacity import (
    CompactionConfig,
    _create_summary,
    prune_old_tool_results,
    should_compact,
)
from deepseek_tui.engine.cycle import CycleConfig, produce_briefing, should_advance_cycle
from deepseek_tui.engine.prefix_probe import fingerprint_request, first_divergence
from deepseek_tui.protocol.messages import Message, ToolUseBlock
from deepseek_tui.protocol.responses import StreamTextDelta
from deepseek_tui.tools.subagent.loop import _compact_subagent_messages


@pytest.mark.parametrize("operation", ["summary", "cycle"])
async def test_summary_preserves_request_prefix_and_disables_tool_calls(operation):
    messages = [Message.user("constraint"), Message.assistant("head " + "middle" * 10000 + " tail")]
    tools = [{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}]
    captured = []

    async def stream(request):
        captured.append(request)
        yield StreamTextDelta(text="### Goal\nKeep constraint\n### Next step\nVerify it")

    client = SimpleNamespace(stream_chat_completion=stream)
    if operation == "summary":
        await _create_summary(
            client, messages, "deepseek-flash", system_prompt="stable", tools=tools
        )
    else:
        await produce_briefing(
            client, "deepseek-flash", messages, 3000, system_prompt="stable", tools=tools
        )
    request = captured[0]
    assert request.messages[:-1] == messages
    assert request.tool_choice == "none"
    assert (
        first_divergence(
            fingerprint_request("stable", messages, tools),
            fingerprint_request(request.system_prompt, request.messages, request.tools),
        )
        is None
    )


def test_absolute_caps_override_ratio_floor():
    messages = [Message.assistant("bulk " * 1000) for _ in range(15)]
    config = CompactionConfig(keep_recent_tokens=0)
    assert should_compact(messages, config, real_input_tokens=150000, model="deepseek-flash")
    assert not should_compact(messages, config, real_input_tokens=100000, model="deepseek-flash")
    assert should_advance_cycle(250000, "deepseek-flash", CycleConfig(), False)
    assert not should_advance_cycle(250000, "deepseek-flash", CycleConfig(), True)


def single_user_history():
    messages = [Message.user("Investigate; keep config.toml unchanged")]
    for i in range(15):
        messages += [
            Message.assistant_with_tools(
                [ToolUseBlock(id=str(i), name="read_file", input={"path": "x"})]
            ),
            Message.tool_result(str(i), "body " * 2000),
        ]
    return messages


async def test_single_user_child_overflow_reclaims_old_bodies():
    messages = single_user_history()
    tail = [m.model_dump() for m in messages[-4:]]
    before = len(str(messages))
    result = await _compact_subagent_messages(messages)
    assert len(str(result)) < before
    assert [m.model_dump() for m in result[-4:]] == tail
    assert result[0].text_content() == "Investigate; keep config.toml unchanged"


def test_single_user_l0_preserves_tool_round_prefix():
    messages = single_user_history()
    assert prune_old_tool_results(messages) == 0


@pytest.mark.parametrize("operation", ["summary", "cycle"])
async def test_summary_rejects_tool_calls(operation):
    from deepseek_tui.protocol.responses import StreamToolCallComplete, ToolCall

    async def stream(request):
        yield StreamToolCallComplete(tool_call=ToolCall(id="bad", name="read_file", input={}))

    client = SimpleNamespace(stream_chat_completion=stream)
    with pytest.raises(ValueError, match="requested a tool"):
        if operation == "summary":
            await _create_summary(client, [Message.user("goal")], "deepseek-flash")
        else:
            await produce_briefing(client, "deepseek-flash", [Message.user("goal")], 3000)
