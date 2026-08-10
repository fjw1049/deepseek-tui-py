"""Both wire projections must refuse to emit an unpaired tool call.

``plan_compaction`` tries not to split a tool round (see
``test_plan_compaction_does_not_orphan_tool_results``), but compaction, L0
pruning and pinning all select messages by index, so pairing can still break.
The OpenAI chat projection has always cleaned that up at the wire level; the
Anthropic projection had no equivalent and would send the orphan straight to an
API that rejects it. ``drop_orphaned_tool_blocks`` is the shared guarantee.
"""

from __future__ import annotations

from deepseek_tui.client.anthropic import _build_anthropic_messages
from deepseek_tui.client.chat_messages import build_chat_messages
from deepseek_tui.client.normalize import drop_orphaned_tool_blocks
from deepseek_tui.protocol.messages import (
    Message,
    Role,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

MODEL = "deepseek-chat"


def _paired() -> list[Message]:
    return [
        Message.user("read it"),
        Message.assistant_with_tools(
            [ToolUseBlock(id="call_1", name="read_file", input={"path": "a.py"})]
        ),
        Message.tool_result("call_1", "file body"),
        Message.assistant("here it is"),
    ]


def _anthropic_blocks(messages: list[Message]) -> list[dict]:
    _, out = _build_anthropic_messages(messages, system_prompt="sys")
    return [block for message in out for block in message["content"]]


def test_paired_history_is_returned_untouched() -> None:
    """The normal case must be free: same list object, no copies."""
    messages = _paired()
    assert drop_orphaned_tool_blocks(messages) is messages


def test_tool_use_without_its_result_is_dropped_by_both_projections() -> None:
    # Compaction kept the assistant's tool call and summarised the result away.
    messages = [
        Message.user("read it"),
        Message.assistant_with_tools(
            [ToolUseBlock(id="call_1", name="read_file", input={"path": "a.py"})]
        ),
        Message.user("never mind, carry on"),
    ]

    chat = build_chat_messages(messages, system_prompt="sys", model=MODEL)
    assert all("tool_calls" not in message for message in chat)

    blocks = _anthropic_blocks(messages)
    assert not any(block["type"] == "tool_use" for block in blocks)


def test_tool_result_without_its_call_is_dropped_by_both_projections() -> None:
    messages = [
        Message.user("read it"),
        Message.tool_result("call_gone", "file body"),
        Message.assistant("here it is"),
    ]

    chat = build_chat_messages(messages, system_prompt="sys", model=MODEL)
    assert all(message["role"] != "tool" for message in chat)

    blocks = _anthropic_blocks(messages)
    assert not any(block["type"] == "tool_result" for block in blocks)


def test_assistant_text_survives_losing_its_tool_call() -> None:
    """Dropping the orphan must not delete what the assistant said."""
    messages = [
        Message.user("read it"),
        Message(
            role=Role.ASSISTANT,
            content=[
                TextBlock(text="I'll read that file"),
                ToolUseBlock(id="call_1", name="read_file", input={}),
            ],
        ),
    ]

    chat = build_chat_messages(messages, system_prompt="sys", model=MODEL)
    assistants = [m for m in chat if m["role"] == "assistant"]
    assert len(assistants) == 1
    assert "I'll read that file" in assistants[0]["content"]
    assert "tool_calls" not in assistants[0]

    blocks = _anthropic_blocks(messages)
    assert any(
        block["type"] == "text" and "I'll read that file" in block["text"]
        for block in blocks
    )
    assert not any(block["type"] == "tool_use" for block in blocks)


def test_a_paired_round_is_preserved_on_both_projections() -> None:
    """The guard must not eat legitimate tool rounds."""
    messages = _paired()

    chat = build_chat_messages(messages, system_prompt="sys", model=MODEL)
    assert any(message.get("tool_calls") for message in chat)
    assert any(message["role"] == "tool" for message in chat)

    blocks = _anthropic_blocks(messages)
    kinds = {block["type"] for block in blocks}
    assert "tool_use" in kinds
    assert "tool_result" in kinds


def test_only_the_unpaired_half_of_a_batch_is_dropped() -> None:
    """A parallel tool batch keeps the calls that did come back."""
    messages = [
        Message.user("read both"),
        Message.assistant_with_tools(
            [
                ToolUseBlock(id="call_1", name="read_file", input={}),
                ToolUseBlock(id="call_2", name="read_file", input={}),
            ]
        ),
        Message.tool_result("call_1", "first body"),
    ]

    kept = drop_orphaned_tool_blocks(messages)
    use_ids = [
        block.id
        for message in kept
        for block in message.content
        if isinstance(block, ToolUseBlock)
    ]
    result_ids = [
        block.tool_use_id
        for message in kept
        for block in message.content
        if isinstance(block, ToolResultBlock)
    ]
    assert use_ids == ["call_1"]
    assert result_ids == ["call_1"]
