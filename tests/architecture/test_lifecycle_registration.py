"""Architecture characterization for engine lifecycle observer registration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.host.engine_lifecycle import register_engine_lifecycle_observers
from deepseek_tui.host.lifecycle import LifecycleRegistry
from deepseek_tui.tools.context import ToolContext


def _minimal_config() -> Config:
    return Config(
        features=FeatureConfig(
            tasks=False,
            subagents=False,
            mcp=False,
            automations=False,
        )
    )


@pytest.mark.asyncio
async def test_engine_create_registers_observers_in_stable_order(tmp_path: Path) -> None:
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
        config=_minimal_config(),
        working_directory=tmp_path,
    )
    try:
        observer_ids = [
            registration.id for registration in engine.lifecycle_registry.registrations()
        ]
        assert observer_ids == [
            "lsp.after_tool",
            "memory.before_turn",
            "post_turn.after_tool",
            "goal.lifecycle",
        ]
    finally:
        await engine.shutdown_session()
        handle.drain_events()


def test_register_engine_lifecycle_observers_is_idempotent() -> None:
    registry = LifecycleRegistry()
    engine = SimpleNamespace(
        lifecycle_registry=registry,
        tool_context=ToolContext(working_directory=Path("/tmp")),
        turn_counter=0,
        pending_lsp_blocks=[],
        memory_coordinator=None,
        memory_thread_id=None,
        memory_mode=None,
        _cycle_session_id=None,
        post_turn=None,
        goal_controller=None,
    )

    register_engine_lifecycle_observers(engine)  # type: ignore[arg-type]
    register_engine_lifecycle_observers(engine)  # type: ignore[arg-type]

    assert len(registry.registrations()) == 4


@pytest.mark.asyncio
async def test_lifecycle_observers_read_live_engine_fields(tmp_path: Path) -> None:
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
        config=_minimal_config(),
        working_directory=tmp_path,
    )
    try:
        engine.turn_counter = 7
        engine.memory_thread_id = "thread-live"
        engine.memory_mode = "smart"

        memory_observer = next(
            registration.observer
            for registration in engine.lifecycle_registry.registrations()
            if registration.id == "memory.before_turn"
        )
        assert memory_observer.memory_thread_id() == "thread-live"
        assert memory_observer.memory_mode() == "smart"

        lsp_observer = next(
            registration.observer
            for registration in engine.lifecycle_registry.registrations()
            if registration.id == "lsp.after_tool"
        )
        assert lsp_observer.turn_counter() == 7
    finally:
        await engine.shutdown_session()
        handle.drain_events()
