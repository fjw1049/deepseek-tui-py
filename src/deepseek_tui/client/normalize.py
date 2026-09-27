"""Provider-independent message normalisation, applied by every projection.

Both wire shapes reject a ``tool_use`` with no paired ``tool_result`` (and the
reverse). Pairing can break without anyone writing a bug: compaction and L0
pruning pick messages by index, so a pinned ``assistant(tool_use)`` can survive
while the ``tool_result`` it belongs to is summarised away. The OpenAI chat
projection has always cleaned this up at the wire level; doing it here instead
means the Anthropic projection — and any provider added later — cannot miss it.
"""

from __future__ import annotations

import logging
from collections import Counter

from deepseek_tui.protocol.messages import Message, Role, ToolResultBlock, ToolUseBlock

logger = logging.getLogger(__name__)


def drop_orphaned_tool_blocks(messages: list[Message]) -> list[Message]:
    """Retain unambiguous adjacent tool pairs without reordering history.

    Invalid pairs are dropped together; ordinary text is preserved. A healthy
    history is returned unchanged. Internal tool results belong to Role.TOOL.
    """
    uses = Counter(b.id for m in messages for b in m.content if isinstance(b, ToolUseBlock))
    keep: set[tuple[int, int]] = set()
    for index, message in enumerate(messages):
        calls = [(i, b) for i, b in enumerate(message.content) if isinstance(b, ToolUseBlock)]
        if message.role is not Role.ASSISTANT or not calls:
            continue
        ids = {b.id for _, b in calls}
        results = []
        for next_index in range(index + 1, len(messages)):
            following = messages[next_index]
            if following.role is not Role.TOOL:
                break
            results.extend(
                (next_index, i, b)
                for i, b in enumerate(following.content)
                if isinstance(b, ToolResultBlock)
            )
        counts = Counter(b.tool_use_id for _, _, b in results)
        ids = {identity for identity in ids if uses[identity] == 1 and counts[identity] == 1}
        keep.update((index, i) for i, b in calls if b.id in ids)
        keep.update((mi, bi) for mi, bi, b in results if b.tool_use_id in ids)

    output = []
    dropped = 0
    for index, message in enumerate(messages):
        kept = [
            b
            for i, b in enumerate(message.content)
            if not isinstance(b, (ToolUseBlock, ToolResultBlock)) or (index, i) in keep
        ]
        dropped += len(message.content) - len(kept)
        if len(kept) == len(message.content):
            output.append(message)
        elif kept:
            output.append(message.model_copy(update={"content": kept}))
    if not dropped:
        return messages
    logger.warning("Dropped %d unpaired or ambiguous tool history blocks", dropped)
    return output
