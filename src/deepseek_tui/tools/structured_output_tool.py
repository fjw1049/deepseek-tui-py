"""Terminating structured-output tool for sub-agent workflows."""

from __future__ import annotations

from typing import Any

from deepseek_tui.tools.base import ToolCapability, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

STRUCTURED_OUTPUT_TOOL_NAME = "structured_output"


def _schema_to_tool_input(schema: dict[str, Any]) -> dict[str, object]:
    """Wrap JSON Schema as tool parameters object."""
    if schema.get("type") == "object" and "properties" in schema:
        out: dict[str, object] = {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }
        if "additionalProperties" in schema:
            out["additionalProperties"] = schema["additionalProperties"]
        return out
    return {
        "type": "object",
        "properties": {"output": schema},
        "required": ["output"],
    }


class StructuredOutputTool(ToolSpec):
    """Capture validated params as the sub-agent final answer and stop the loop."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    def name(self) -> str:
        return STRUCTURED_OUTPUT_TOOL_NAME

    def description(self) -> str:
        return (
            "Return the final machine-readable result for this sub-agent task. "
            "Call exactly once when finished."
        )

    def input_schema(self) -> dict[str, object]:
        return _schema_to_tool_input(self._schema)

    def _unwrap_input(self, input_data: dict[str, Any]) -> Any:
        if self._schema.get("type") == "object" and "properties" in self._schema:
            return input_data
        return input_data.get("output")

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        del context
        value = self._unwrap_input(input_data)
        try:
            import jsonschema

            jsonschema.validate(instance=value, schema=self._schema)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                content=f"structured_output validation failed: {exc}",
            )
        return ToolResult(
            success=True,
            content="Structured output received.",
            metadata={
                "value": value,
                "terminate_subagent": True,
            },
        )
