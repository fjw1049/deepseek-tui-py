"""Test parallel tool execution (mirrors Rust turn_loop.rs:1205-1303)."""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.engine.dispatch import (
    ToolExecutionPlan,
    should_parallelize_tool_batch,
)
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.base import ToolCapability, ToolResult


class SlowReadTool:
    """Mock read-only tool that sleeps."""

    def __init__(self, name: str, delay_ms: int = 100):
        self._name = name
        self._delay_ms = delay_ms

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return f"Slow read tool ({self._delay_ms}ms)"

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict, context) -> ToolResult:
        await asyncio.sleep(self._delay_ms / 1000.0)
        return ToolResult(
            success=True,
            content=f"{self._name} result after {self._delay_ms}ms",
        )


@pytest.mark.asyncio
async def test_parallel_execution_faster_than_serial():
    """Parallel execution of 3 read-only tools is faster than serial."""
    # Each tool takes 100ms
    # Serial: ~300ms, Parallel: ~100ms

    from deepseek_tui.tools.context import ToolContext
    from deepseek_tui.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(SlowReadTool("read_a", delay_ms=100))
    registry.register(SlowReadTool("read_b", delay_ms=100))
    registry.register(SlowReadTool("read_c", delay_ms=100))

    tool_calls = [
        ToolCall(id="1", name="read_a", arguments={}),
        ToolCall(id="2", name="read_b", arguments={}),
        ToolCall(id="3", name="read_c", arguments={}),
    ]

    # Mock Engine with minimal setup
    engine = MagicMock()
    engine.tool_registry = registry
    engine.default_model = "test-model"
    engine.working_set = MagicMock()
    engine.working_set.observe_tool_call = MagicMock()
    engine.handle = MagicMock()
    engine.handle.emit = AsyncMock()
    engine._run_post_edit_lsp_hook = AsyncMock()

    # Bind the method
    from deepseek_tui.engine.engine import Engine as RealEngine

    engine._execute_tools_parallel = RealEngine._execute_tools_parallel.__get__(
        engine, type(engine)
    )

    async def mock_execute_single(tc, *args):
        return await registry.execute(
            tc.name, tc.arguments, ToolContext(working_directory=Path.cwd())
        )

    engine._execute_single_tool = AsyncMock(side_effect=mock_execute_single)

    start = time.monotonic()
    results = await engine._execute_tools_parallel(
        tool_calls,
        [],
        "test-model",
    )
    elapsed_ms = (time.monotonic() - start) * 1000

    assert len(results) == 3
    # Should be ~100ms (parallel), not ~300ms (serial)
    # Allow 50ms overhead for test environment
    assert elapsed_ms < 200, f"Took {elapsed_ms}ms, expected <200ms"


@pytest.mark.asyncio
async def test_parallel_execution_preserves_order():
    """Results are returned in the same order as input tool_calls."""
    from deepseek_tui.tools.context import ToolContext
    from deepseek_tui.tools.registry import ToolRegistry

    registry = ToolRegistry()
    # Tools complete in reverse order (c fastest, a slowest)
    registry.register(SlowReadTool("read_a", delay_ms=150))
    registry.register(SlowReadTool("read_b", delay_ms=100))
    registry.register(SlowReadTool("read_c", delay_ms=50))

    tool_calls = [
        ToolCall(id="1", name="read_a", arguments={}),
        ToolCall(id="2", name="read_b", arguments={}),
        ToolCall(id="3", name="read_c", arguments={}),
    ]

    engine = MagicMock()
    engine.tool_registry = registry
    engine.default_model = "test-model"
    engine.working_set = MagicMock()
    engine.working_set.observe_tool_call = MagicMock()
    engine.handle = MagicMock()
    engine.handle.emit = AsyncMock()
    engine._run_post_edit_lsp_hook = AsyncMock()

    from deepseek_tui.engine.engine import Engine as RealEngine

    engine._execute_tools_parallel = RealEngine._execute_tools_parallel.__get__(
        engine, type(engine)
    )

    async def mock_execute_single(tc, *args):
        return await registry.execute(
            tc.name, tc.arguments, ToolContext(working_directory=Path.cwd())
        )

    engine._execute_single_tool = AsyncMock(side_effect=mock_execute_single)

    results = await engine._execute_tools_parallel(
        tool_calls,
        [],
        "test-model",
    )

    # Results must match input order (a, b, c), not completion order (c, b, a)
    assert len(results) == 3
    assert results[0].content[0].tool_use_id == "1"  # read_a
    assert results[1].content[0].tool_use_id == "2"  # read_b
    assert results[2].content[0].tool_use_id == "3"  # read_c


@pytest.mark.asyncio
async def test_parallel_execution_error_isolation():
    """One tool failing doesn't prevent others from completing."""
    from deepseek_tui.tools.base import ToolError
    from deepseek_tui.tools.context import ToolContext
    from deepseek_tui.tools.registry import ToolRegistry

    class FailingTool(SlowReadTool):
        async def execute(self, input_data: dict, context) -> ToolResult:
            await asyncio.sleep(self._delay_ms / 1000.0)
            raise ToolError(f"{self._name} failed")

    registry = ToolRegistry()
    registry.register(SlowReadTool("read_a", delay_ms=50))
    registry.register(FailingTool("read_b", delay_ms=50))
    registry.register(SlowReadTool("read_c", delay_ms=50))

    tool_calls = [
        ToolCall(id="1", name="read_a", arguments={}),
        ToolCall(id="2", name="read_b", arguments={}),
        ToolCall(id="3", name="read_c", arguments={}),
    ]

    engine = MagicMock()
    engine.tool_registry = registry
    engine.default_model = "test-model"
    engine.working_set = MagicMock()
    engine.working_set.observe_tool_call = MagicMock()
    engine.handle = MagicMock()
    engine.handle.emit = AsyncMock()
    engine._run_post_edit_lsp_hook = AsyncMock()

    from deepseek_tui.engine.engine import Engine as RealEngine

    engine._execute_tools_parallel = RealEngine._execute_tools_parallel.__get__(
        engine, type(engine)
    )

    async def mock_execute_single(tc, *args):
        return await registry.execute(
            tc.name, tc.arguments, ToolContext(working_directory=Path.cwd())
        )

    engine._execute_single_tool = AsyncMock(side_effect=mock_execute_single)

    results = await engine._execute_tools_parallel(
        tool_calls,
        [],
        "test-model",
    )

    # All 3 results returned
    assert len(results) == 3
    # First and third succeeded
    assert not results[0].content[0].is_error
    assert not results[2].content[0].is_error
    # Second failed
    assert results[1].content[0].is_error
    assert "read_b failed" in results[1].content[0].content


def test_should_parallelize_rejects_write_tools():
    """Write tools force serial execution."""
    plans = [
        ToolExecutionPlan(
            index=0,
            id="1",
            name="read_file",
            input={},
            read_only=True,
            supports_parallel=True,
            approval_required=False,
        ),
        ToolExecutionPlan(
            index=1,
            id="2",
            name="write_file",
            input={},
            read_only=False,  # Write tool
            supports_parallel=False,
            approval_required=False,
        ),
    ]

    assert not should_parallelize_tool_batch(plans)


def test_should_parallelize_rejects_approval_required():
    """Tools requiring approval force serial execution."""
    plans = [
        ToolExecutionPlan(
            index=0,
            id="1",
            name="read_file",
            input={},
            read_only=True,
            supports_parallel=True,
            approval_required=False,
        ),
        ToolExecutionPlan(
            index=1,
            id="2",
            name="exec_shell",
            input={},
            read_only=True,
            supports_parallel=True,
            approval_required=True,  # Needs approval
        ),
    ]

    assert not should_parallelize_tool_batch(plans)



