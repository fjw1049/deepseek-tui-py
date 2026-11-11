"""A sub-agent tool call's success comes from the tool, not from its text."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deepseek_tui.tools.registry import (
    ToolCapability,
    ToolContext,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.subagent.loop import _run_subagent_tool


class _EchoTool(ToolSpec):
    def __init__(self, content: str, success: bool) -> None:
        self._content = content
        self._success = success

    def name(self) -> str:
        return "echo"

    def description(self) -> str:
        return "echo"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(success=self._success, content=self._content)


async def _run(content: str, success: bool, tmp_path) -> tuple[bool, str]:
    registry = ToolRegistry()
    registry.register(_EchoTool(content, success))
    runtime = SimpleNamespace(config=SimpleNamespace(approval_policy="auto"))
    return await _run_subagent_tool(
        registry, ToolContext(working_directory=tmp_path), tool_name="echo",
        tool_input={}, auto_approve=True, tool_call_id="t1",
        runtime=runtime,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_successful_output_that_starts_with_error_is_still_success(tmp_path) -> None:
    ok, text = await _run("Error: line 3 of the log you asked for", True, tmp_path)
    assert ok is True
    assert "line 3 of the log" in text


@pytest.mark.asyncio
async def test_failed_tool_is_failure(tmp_path) -> None:
    ok, text = await _run("permission denied", False, tmp_path)
    assert ok is False
    assert text == "Error: permission denied"
