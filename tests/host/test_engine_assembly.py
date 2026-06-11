from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.host.assembler import EngineAssemblyRequest, assemble_engine


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
async def test_engine_create_enters_compatible_assembler(tmp_path: Path) -> None:
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
        config=_minimal_config(),
        working_directory=tmp_path,
    )
    try:
        assert engine.tool_context.working_directory == tmp_path.resolve()
        assert engine.tool_runtime is not None
    finally:
        await engine.shutdown_session()
        handle.drain_events()


@pytest.mark.asyncio
async def test_assemble_engine_delegates_to_legacy_creation(tmp_path: Path) -> None:
    handle = EngineHandle()
    engine = await assemble_engine(
        EngineAssemblyRequest(
            engine_cls=Engine,
            handle=handle,
            client=AsyncMock(),
            config=_minimal_config(),
            working_directory=tmp_path,
        )
    )
    try:
        assert engine.tool_context.working_directory == tmp_path.resolve()
        assert engine.tool_registry.contains("read_file")
    finally:
        await engine.shutdown_session()
        handle.drain_events()
