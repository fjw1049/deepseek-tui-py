"""Engine ↔ MemoryCoordinator wiring (no real API)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.memory.coordinator import MemoryCoordinator
from deepseek_tui.memory.formatting import strip_relevant_memories, wrap_relevant_memories
from deepseek_tui.protocol.messages import Message


@pytest.mark.asyncio
async def test_engine_create_default_has_no_memory_coordinator(tmp_path: Path) -> None:
    handle = EngineHandle()
    cfg = Config()
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
        config=cfg,
        working_directory=tmp_path,
        start_mcp=False,
    )
    try:
        assert engine.memory_coordinator is None
    finally:
        await engine.shutdown_session()


@pytest.mark.asyncio
async def test_engine_create_smart_memory_wires_coordinator(tmp_path: Path) -> None:
    handle = EngineHandle()
    data_dir = tmp_path / "memory_data"
    cfg = Config(
        memory=MemoryConfig(
            enabled=True,
            mode="hybrid",
            smart=MemorySmartConfig(
                enabled=True,
                data_dir=str(data_dir),
                l1_every_n=100,
            ),
        ),
    )
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
        config=cfg,
        working_directory=tmp_path,
        start_mcp=False,
    )
    try:
        assert isinstance(engine.memory_coordinator, MemoryCoordinator)
        assert (data_dir / "store").exists() or engine.memory_coordinator.enabled
    finally:
        await engine.shutdown_session()


def test_memory_thread_id_resolution_fallback() -> None:
    engine = Engine.__new__(Engine)
    engine.memory_thread_id = None
    engine._cycle_session_id = "cycle-abc"
    from deepseek_tui.tools.context import ToolContext

    engine.tool_context = ToolContext(working_directory=Path.cwd())
    assert engine._resolve_memory_thread_id() == "cycle-abc"
    engine.tool_context.metadata["runtime_thread_id"] = "thr_wb"
    assert engine._resolve_memory_thread_id() == "thr_wb"


def test_wrap_strip_relevant_memories_roundtrip() -> None:
    user = "explain the pool size"
    l1 = "- (instruction) pool size is 50"
    wrapped = wrap_relevant_memories(user, l1)
    assert strip_relevant_memories(wrapped) == user


def test_messages_for_capture_uses_wire_role_values() -> None:
    captured = Engine._messages_for_capture(
        [
            Message.user("user text"),
            Message.assistant("assistant text"),
            Message.tool_result("tool-1", "tool text"),
        ]
    )
    assert [m["role"] for m in captured] == ["user", "assistant", "tool"]
