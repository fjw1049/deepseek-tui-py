"""MultiToolUseParallelTool — expands a batch of read-only tool calls.

Mirrors `crates/tui/src/tools/parallel.rs`.

The model may emit a single ``multi_tool_use.parallel`` tool call whose
``tool_uses`` array contains multiple sub-calls.  The Engine intercepts
this name and fans out the sub-calls concurrently (read-only only).
The ToolSpec itself always raises — it must never be dispatched directly.
"""

from __future__ import annotations

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

MULTI_TOOL_PARALLEL_NAME = "multi_tool_use.parallel"


class MultiToolUseParallelTool(ToolSpec):
    def name(self) -> str:
        return MULTI_TOOL_PARALLEL_NAME

    def description(self) -> str:
        return (
            "Run multiple read-only tools in parallel. "
            "Must be handled by the engine — direct execution is an error."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "tool_uses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {"type": "string"},
                            "parameters": {"type": "object"},
                        },
                        "required": ["recipient_name", "parameters"],
                    },
                }
            },
            "required": ["tool_uses"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        raise ToolError("multi_tool_use.parallel must be handled by the engine")
