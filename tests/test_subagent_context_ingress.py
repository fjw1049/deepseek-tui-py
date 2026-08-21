"""Regression: one oversized tool result must not blow up a sub-agent's context.

Observed root cause of the deterministic sub-agent stalls (2026-08-22 log,
turn ffbe8a7e): ``file_search pattern='' path='.'`` returned 7 714 paths
(~320k tokens). The parent orchestrator compacts tool results on ingress,
but the sub-agent loop appended ``result.content`` raw — from round 2 on the
child carried a 320-415k token transcript and the model degraded into
27-36-token no-tool replies, which then surfaced as the "final summary".

Two independent guards, both exercised here:
1. ``file_search`` caps its own listing (like ``grep_files`` always has).
2. The sub-agent tool path applies the same ingress compaction as the parent.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.tools.registry import ToolContext, ToolRegistry, ToolResult
from deepseek_tui.tools.search import _MAX_FILE_RESULTS, FileSearchTool
from deepseek_tui.tools.subagent.loop import _execute_subagent_tool


@pytest.mark.asyncio
async def test_file_search_caps_huge_listings(tmp_path: Path) -> None:
    for i in range(_MAX_FILE_RESULTS + 20):
        (tmp_path / f"f{i:04d}.py").touch()
    context = ToolContext(working_directory=tmp_path)

    result = await FileSearchTool().execute({"pattern": "", "path": "."}, context)

    lines = result.content.splitlines()
    # Capped listing plus one truncation notice; true count kept in metadata.
    assert len(lines) == _MAX_FILE_RESULTS + 1
    assert "showing 500 of 520 files" in lines[-1]
    assert result.metadata["count"] == _MAX_FILE_RESULTS + 20


@pytest.mark.asyncio
async def test_file_search_below_cap_is_untouched(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"f{i}.py").touch()
    context = ToolContext(working_directory=tmp_path)

    result = await FileSearchTool().execute({"pattern": "", "path": "."}, context)

    assert len(result.content.splitlines()) == 3
    assert "showing" not in result.content


@pytest.mark.asyncio
async def test_subagent_tool_output_is_compacted() -> None:
    raw = "\n".join(f"/repo/some/long/path/file_{i:05d}.py" for i in range(20_000))
    registry = ToolRegistry()
    registry.execute = AsyncMock(  # type: ignore[method-assign]
        return_value=ToolResult(success=True, content=raw, metadata={})
    )
    registry.contains = lambda name: True  # type: ignore[method-assign]
    registry.get = lambda name: SimpleNamespace()  # type: ignore[method-assign]

    out = await _execute_subagent_tool(
        registry,
        SimpleNamespace(metadata={}),
        tool_name="file_search",
        tool_input={"pattern": "", "path": "."},
        auto_approve=True,
        model="deepseek-v4-flash",
    )

    # The parent's ingress compaction applies: a ~700k-char result must
    # come back as a bounded snippet, not enter the transcript whole.
    assert len(out) < len(raw) / 4
