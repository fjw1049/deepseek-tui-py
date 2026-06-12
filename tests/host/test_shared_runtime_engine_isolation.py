"""Regression tests for ENGINE-scoped service isolation with shared ToolRuntime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.capabilities.goal import goal_controller_from_engine
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.goal.controller import GoalController
from deepseek_tui.tools.runtime import create_tool_runtime


@pytest.mark.asyncio
async def test_shared_tool_runtime_uses_isolated_engine_services(tmp_path: Path) -> None:
    cfg = Config(
        features=FeatureConfig(
            tasks=False,
            subagents=False,
            mcp=False,
            automations=False,
        )
    )
    shared = await create_tool_runtime(config=cfg, working_directory=tmp_path)

    handle_a = EngineHandle()
    engine_a = await Engine.create(
        handle=handle_a,
        client=AsyncMock(),
        config=cfg,
        working_directory=tmp_path / "thread-a",
        tool_runtime=shared,
    )
    engine_a.tool_context.metadata["runtime_thread_id"] = "thread-a"

    handle_b = EngineHandle()
    engine_b = await Engine.create(
        handle=handle_b,
        client=AsyncMock(),
        config=cfg,
        working_directory=tmp_path / "thread-b",
        tool_runtime=shared,
    )
    engine_b.tool_context.metadata["runtime_thread_id"] = "thread-b"

    try:
        assert engine_a.tool_context is not engine_b.tool_context
        assert engine_a.tool_context.services is not shared.context.services
        assert engine_b.tool_context.services is not shared.context.services

        controller_a = goal_controller_from_engine(engine_a)
        controller_b = goal_controller_from_engine(engine_b)
        assert isinstance(controller_a, GoalController)
        assert isinstance(controller_b, GoalController)
        assert controller_a is not controller_b

        assert engine_a.tool_context.services.optional(GoalController) is controller_a
        assert engine_b.tool_context.services.optional(GoalController) is controller_b
    finally:
        await engine_a.shutdown_session()
        await engine_b.shutdown_session()
        handle_a.drain_events()
        handle_b.drain_events()
        await shared.shutdown()


@pytest.mark.asyncio
async def test_sequential_shared_runtime_engines_do_not_reuse_engine_services(
    tmp_path: Path,
) -> None:
    cfg = Config(
        features=FeatureConfig(
            tasks=False,
            subagents=False,
            mcp=False,
            automations=False,
        )
    )
    shared = await create_tool_runtime(config=cfg, working_directory=tmp_path)

    handle_a = EngineHandle()
    engine_a = await Engine.create(
        handle=handle_a,
        client=AsyncMock(),
        config=cfg,
        working_directory=tmp_path,
        tool_runtime=shared,
    )
    controller_a = goal_controller_from_engine(engine_a)
    await engine_a.shutdown_session()

    handle_b = EngineHandle()
    engine_b = await Engine.create(
        handle=handle_b,
        client=AsyncMock(),
        config=cfg,
        working_directory=tmp_path,
        tool_runtime=shared,
    )
    controller_b = goal_controller_from_engine(engine_b)
    try:
        assert controller_a is not controller_b
        assert engine_b.tool_context.services.optional(GoalController) is controller_b
        assert shared.context.services.optional(GoalController) is None
    finally:
        await engine_b.shutdown_session()
        handle_a.drain_events()
        handle_b.drain_events()
        await shared.shutdown()
