"""Provider-independent message normalisation, applied by every projection.

Both wire shapes reject a ``tool_use`` with no paired ``tool_result`` (and the
reverse). Pairing can break without anyone writing a bug: compaction and L0
pruning pick messages by index, so a pinned ``assistant(tool_use)`` can survive
while the ``tool_result`` it belongs to is summarised away. The OpenAI chat
projection has always cleaned this up at the wire level; doing it here instead
means the Anthropic projection — and any provider added later — cannot miss it.
"""

from __future__ import annotations

from deepseek_tui.protocol.messages import Message, ToolResultBlock, ToolUseBlock


def drop_orphaned_tool_blocks(messages: list[Message]) -> list[Message]:
    """Drop tool_use / tool_result blocks whose counterpart is missing.

    A message left with no blocks at all is dropped; one that still has text
    keeps it, which is how an assistant turn survives losing its tool call.
    Order is preserved, inputs are never mutated, and a fully paired history
    (the normal case) is returned unchanged.
    """
    use_ids: set[str] = set()
    result_ids: set[str] = set()
    for message in messages:
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                use_ids.add(block.id)
            elif isinstance(block, ToolResultBlock):
                result_ids.add(block.tool_use_id)

    if use_ids == result_ids:
        return messages

    output: list[Message] = []
    for message in messages:
        kept = [
            block
            for block in message.content
            if not (
                (isinstance(block, ToolUseBlock) and block.id not in result_ids)
                or (
                    isinstance(block, ToolResultBlock)
                    and block.tool_use_id not in use_ids
                )
            )
        ]
        if len(kept) == len(message.content):
            output.append(message)
        elif kept:
            output.append(message.model_copy(update={"content": kept}))
    return output
