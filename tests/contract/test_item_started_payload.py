"""``item.started`` for tool calls must include ``tool.input``.

Workbench provider renders ``request_user_input`` interactive blocks live by
reading ``payload.tool.input`` from the SSE frame; if the runtime drops that
field the questions only appear after the turn completes (via ThreadDetail
reload). Lock the contract at source level — there's no cheap way to drive a
real ToolCallEvent through the manager in a contract test.
"""

from __future__ import annotations

from pathlib import Path


def test_item_started_emits_tool_input() -> None:
    src = Path("src/deepseek_tui/server/threads.py").read_text(
        encoding="utf-8"
    )
    # Find the item.started emit for ToolCallEvent and assert it carries input.
    marker = '"item.started"'
    assert marker in src
    # Search for the surrounding payload literal — it must mention tc.arguments
    # under a "tool" key with both "name" and "input".
    idx = src.index('"tool": {')
    snippet = src[idx : idx + 200]
    assert '"name": tc.name' in snippet
    assert '"input": tc.arguments' in snippet, (
        "item.started payload missing tool.input — Workbench provider needs it "
        "to render request_user_input live (see deepseek-runtime.ts:752-762)."
    )
