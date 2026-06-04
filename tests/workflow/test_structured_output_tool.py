"""Structured output tool contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.structured_output_tool import StructuredOutputTool


@pytest.mark.asyncio
async def test_non_object_schema_validates_unwrapped_output() -> None:
    tool = StructuredOutputTool({"type": "array", "items": {"type": "string"}})
    result = await tool.execute(
        {"output": ["a", "b"]},
        ToolContext(working_directory=Path(".")),
    )

    assert result.success is True
    assert result.metadata["value"] == ["a", "b"]


@pytest.mark.asyncio
async def test_object_schema_preserves_arguments_as_value() -> None:
    tool = StructuredOutputTool(
        {
            "type": "object",
            "properties": {"verdict": {"type": "string"}},
            "required": ["verdict"],
        }
    )
    result = await tool.execute(
        {"verdict": "ok"},
        ToolContext(working_directory=Path(".")),
    )

    assert result.success is True
    assert result.metadata["value"] == {"verdict": "ok"}
