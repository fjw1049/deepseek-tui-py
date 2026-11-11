"""Keep protocol-valid context when a turn or a tool batch is interrupted."""

from __future__ import annotations

from deepseek_tui.protocol.messages import Message, Role, ToolResultBlock, ToolUseBlock


def complete_tool_prefix(messages: list[Message]) -> list[Message]:
    """Exclude an in-flight batch from a child's inherited context."""
    pending: set[str] = set()
    batch_start = len(messages)
    for index, message in enumerate(messages):
        calls = {block.id for block in message.content if isinstance(block, ToolUseBlock)}
        if calls:
            if pending:
                return messages[:batch_start]
            pending = calls
            batch_start = index
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                pending.discard(block.tool_use_id)
    return messages[:batch_start] if pending else list(messages)


def interrupted_turn_messages(
    messages: list[Message], completed: dict[str, Message]
) -> list[Message]:
    """Retain completed IO; represent unknown outcomes without inventing success."""
    output: list[Message] = []
    pending: list[str] = []

    def finish_batch() -> None:
        for call_id in pending:
            output.append(
                completed.get(call_id)
                or Message.tool_result(
                    call_id,
                    "Turn interrupted before a result was recorded. The operation may "
                    "have had side effects; inspect current state before retrying.",
                    is_error=True,
                )
            )
        pending.clear()

    for index, message in enumerate(messages):
        if message.role is not Role.TOOL:
            finish_batch()
        calls = [block.id for block in message.content if isinstance(block, ToolUseBlock)]
        if index == len(messages) - 1 and message.role is Role.ASSISTANT and not calls:
            continue
        output.append(message)
        pending.extend(calls)
        for block in message.content:
            if isinstance(block, ToolResultBlock) and block.tool_use_id in pending:
                pending.remove(block.tool_use_id)
    finish_batch()
    return output
