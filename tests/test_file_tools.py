from __future__ import annotations

import pytest

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.file import ReadFileTool


@pytest.mark.asyncio
async def test_read_file_respects_offset_and_limit(tmp_path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = await ReadFileTool().execute(
        {"path": "sample.txt", "offset": 2, "limit": 2},
        ToolContext(working_directory=tmp_path),
    )

    assert result.success is True
    assert result.content == "two\nthree\n"
    assert result.metadata["line_offset"] == 2
    assert result.metadata["line_limit"] == 2
    assert result.metadata["total_lines"] == 4
