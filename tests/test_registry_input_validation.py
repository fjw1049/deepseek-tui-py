"""Registry-level JSON Schema validation of tool arguments.

``ToolRegistry.execute`` validates ``input_data`` against the tool's
``input_schema()`` before dispatching (required / types / enums only —
extra properties are allowed because the execution layer tolerates legacy
alias parameters).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.tools.git import GitTool
from deepseek_tui.tools.registry import (
    ToolCapability,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.task import TaskOutputTool
from deepseek_tui.tools.web import WebSearchTool


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(working_directory=Path("."))


def _registry_with(*tools: ToolSpec) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_all(list(tools))
    return registry


class TestMissingRequired:
    async def test_git_missing_command(self, context: ToolContext) -> None:
        registry = _registry_with(GitTool())
        with pytest.raises(ToolError) as exc_info:
            await registry.execute("git", {}, context)
        assert "command" in str(exc_info.value)
        assert "invalid arguments" in str(exc_info.value)

    async def test_web_search_missing_query(self, context: ToolContext) -> None:
        registry = _registry_with(WebSearchTool())
        with pytest.raises(ToolError) as exc_info:
            await registry.execute("web_search", {}, context)
        assert "query" in str(exc_info.value)


class TestTypeViolations:
    async def test_integer_field_given_string(self, context: ToolContext) -> None:
        registry = _registry_with(WebSearchTool())
        with pytest.raises(ToolError) as exc_info:
            await registry.execute("web_search", {"query": "x", "max_results": "8"}, context)
        message = str(exc_info.value)
        assert "invalid arguments" in message
        assert "max_results" in message  # json_path points at the bad field


class TestEnumViolations:
    async def test_git_unknown_command(self, context: ToolContext) -> None:
        registry = _registry_with(GitTool())
        with pytest.raises(ToolError) as exc_info:
            await registry.execute("git", {"command": "bogus"}, context)
        assert "bogus" in str(exc_info.value)


class TestExtraPropertiesAllowed:
    async def test_legacy_alias_not_rejected_by_validation(self, context: ToolContext) -> None:
        """``task_output`` accepts the legacy ``id`` alias at the execution
        layer, so validation must let it through even though the schema
        only declares ``task_id``. The call then fails on a *business*
        error (no TaskManager attached), not a validation error."""
        registry = _registry_with(TaskOutputTool())
        with pytest.raises(ToolError) as exc_info:
            await registry.execute("task_output", {"id": "x"}, context)
        assert "invalid arguments" not in str(exc_info.value)


class TestValidCallsPassThrough:
    async def test_git_status_runs(self, context: ToolContext) -> None:
        registry = _registry_with(GitTool())
        result = await registry.execute("git", {"command": "status"}, context)
        assert isinstance(result, ToolResult)

    async def test_error_is_raised_before_timeout_wrapper(self, context: ToolContext) -> None:
        """Validation errors surface as-is (not re-wrapped by the timeout /
        ValueError handling) even when a timeout is configured."""
        registry = _registry_with(GitTool())
        ctx = ToolContext(working_directory=Path("."), timeout_ms=60_000)
        with pytest.raises(ToolError, match="invalid arguments"):
            await registry.execute("git", {}, ctx)


class _BrokenSchemaTool(ToolSpec):
    """A tool whose input_schema is itself invalid."""

    def name(self) -> str:
        return "broken_schema"

    def description(self) -> str:
        return "tool with an invalid schema"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "not-a-real-type"}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(success=True, content="ok")


class TestInvalidSchemaFailsOpen:
    async def test_broken_schema_does_not_break_call(
        self, context: ToolContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        registry = _registry_with(_BrokenSchemaTool())
        with caplog.at_level("WARNING"):
            result = await registry.execute("broken_schema", {"anything": 1}, context)
        assert result.content == "ok"
        assert any("invalid input_schema" in r.message for r in caplog.records)


class _CountingSchemaTool(ToolSpec):
    def __init__(self) -> None:
        self.schema_calls = 0

    def name(self) -> str:
        return "counting"

    def description(self) -> str:
        return "counts input_schema() calls"

    def input_schema(self) -> dict[str, Any]:
        self.schema_calls += 1
        return {"type": "object", "properties": {"x": {"type": "integer"}}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(success=True, content="ok")


class TestValidatorCaching:
    async def test_schema_sampled_once_per_registration(self, context: ToolContext) -> None:
        tool = _CountingSchemaTool()
        registry = _registry_with(tool)
        for _ in range(3):
            await registry.execute("counting", {"x": 1}, context)
        assert tool.schema_calls == 1

    async def test_re_registration_invalidates_cache(self, context: ToolContext) -> None:
        """Overwriting a tool under the same name must rebuild the
        validator instead of validating against the stale schema."""
        first = _CountingSchemaTool()
        registry = _registry_with(first)
        await registry.execute("counting", {"x": 1}, context)
        assert first.schema_calls == 1

        second = _CountingSchemaTool()
        registry.register(second)  # overwrite under the same name
        await registry.execute("counting", {"x": 1}, context)
        assert second.schema_calls == 1
