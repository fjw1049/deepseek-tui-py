"""The checklist write path must echo the whole list into the transcript.

The model's only other view of the checklist is its own earlier ``tool_call``
arguments — which L0 prune blanks at 50% window and rewrite compaction drops
at 75%. Meanwhile the long-session reminder keeps telling it to "keep the
checklist current", so a count-only result leaves it steering blind.

The leading ``N items written`` is load-bearing beyond prose: the Workbench
renderer matches it to detect writes (``extract-todos-from-blocks.ts``).
"""

from __future__ import annotations

import pytest

from deepseek_tui.tools.registry import ToolContext, build_default_registry

_CANONICAL_NAME = "checklist"


@pytest.mark.asyncio
async def test_write_result_echoes_full_checklist(tmp_path) -> None:
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)

    result = await registry.execute(
        _CANONICAL_NAME,
        {
            "todos": [
                {"content": "Audit reminder wiring", "status": "completed"},
                {"content": "Fix summarizer roles", "status": "in_progress"},
                {"content": "Add read registry", "status": "pending"},
            ]
        },
        context,
    )

    assert result.success
    assert "items written" in result.content, "Workbench write detection"
    for content in (
        "Audit reminder wiring",
        "Fix summarizer roles",
        "Add read registry",
    ):
        assert content in result.content
    assert "[x] 1: Audit reminder wiring" in result.content
    assert "[~] 2: Fix summarizer roles" in result.content
    assert "[ ] 3: Add read registry" in result.content


@pytest.mark.asyncio
async def test_write_and_read_render_identically(tmp_path) -> None:
    """A write echo and a subsequent read agree, so the model sees one shape."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)

    written = await registry.execute(
        _CANONICAL_NAME,
        {
            "todos": [
                {"content": "A", "status": "in_progress"},
                {"content": "B", "status": "pending"},
            ]
        },
        context,
    )
    listed = await registry.execute(_CANONICAL_NAME, {}, context)

    assert written.content.endswith(listed.content)
    assert listed.content


@pytest.mark.asyncio
async def test_clearing_the_checklist_keeps_the_count_header(tmp_path) -> None:
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)

    result = await registry.execute(_CANONICAL_NAME, {"todos": []}, context)

    assert result.success
    assert result.content == "0 items written"
