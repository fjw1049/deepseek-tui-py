"""Wire schemas keep no top-level composition keywords.

OpenAI rejects ``oneOf``/``anyOf``/``allOf``/``enum``/``const``/``not`` at
the top of a function's parameters (Anthropic rejects the composition ones).
The registry still validates calls against the tool's original schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.tools.encoding import sanitize
from deepseek_tui.tools.registry import (
    ToolCapability,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.user_input import RequestUserInputTool

FORBIDDEN = {"oneOf", "anyOf", "allOf", "enum", "const", "not"}

# The LCU ``js`` tool's schema, as the runtime lists it (descriptions trimmed).
LCU_JS_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "completion_summary": {"type": "string", "minLength": 1, "maxLength": 80},
        "timeout_ms": {"type": "integer", "minimum": 1},
        "title": {"type": "string", "minLength": 1, "maxLength": 80},
    },
    "additionalProperties": False,
    "oneOf": [
        {"type": "object", "additionalProperties": False, "required": ["code"],
         "properties": {"code": {"type": "string"}, "timeout_ms": {"type": "integer"},
                        "title": {"type": "string"}}},
        {"type": "object", "additionalProperties": False, "required": ["completion_summary"],
         "properties": {"completion_summary": {"type": "string"}}},
    ],
}


class _SchemaTool(ToolSpec):
    def __init__(self, name: str, schema: dict[str, Any]):
        self._name, self._schema = name, schema

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return "test"

    def input_schema(self) -> dict[str, Any]:
        return self._schema

    def capabilities(self) -> list[ToolCapability]:
        return []

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(success=True, content="ok")


def _observe_schema() -> dict[str, Any]:
    from deepseek_tui.cua.tools import CuaObserveTool

    return CuaObserveTool.input_schema(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("schema_factory", [
    lambda: LCU_JS_SCHEMA,
    _observe_schema,
    lambda: RequestUserInputTool().input_schema(),
])
def test_wire_schema_has_no_top_level_composition(schema_factory) -> None:
    original = schema_factory()
    registry = ToolRegistry()
    registry.register(_SchemaTool("t", original))
    params = registry.to_api_tools()[0]["function"]["parameters"]
    assert params["type"] == "object"
    assert not FORBIDDEN & params.keys()
    assert params["properties"].keys() == original["properties"].keys()
    assert FORBIDDEN & original.keys(), "the tool's own schema is left untouched"


def test_properties_only_in_variants_reach_the_wire() -> None:
    schema = sanitize({"type": "object", "anyOf": [
        {"properties": {"a": {"type": "string"}}, "required": ["a"]},
        {"properties": {"b": {"type": "integer"}}, "required": ["b"]},
    ]})
    assert schema == {"type": "object",
                      "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}


async def test_original_one_of_is_still_enforced_locally() -> None:
    registry = ToolRegistry()
    registry.register(_SchemaTool("cua_js", LCU_JS_SCHEMA))
    context = ToolContext(working_directory=Path("."))
    assert (await registry.execute("cua_js", {"code": "1"}, context)).content == "ok"
    with pytest.raises(ToolError, match="invalid arguments"):
        await registry.execute("cua_js", {"title": "only a title"}, context)
