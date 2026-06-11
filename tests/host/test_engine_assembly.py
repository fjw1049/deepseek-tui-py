from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.host.assembler import (
    EngineAssemblyRequest,
    assemble_engine,
    collect_builtin_contributions,
)
from deepseek_tui.host.engine_attach import attach_engine_capabilities
from deepseek_tui.host.catalog import BuiltinModuleCatalog
from deepseek_tui.host.contributions import Contributions
from deepseek_tui.host.lifecycle import FunctionLifecycleObserver
from deepseek_tui.host.module import ModuleDescriptor


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
async def test_engine_create_registers_lifecycle_observers(tmp_path: Path) -> None:
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
        config=_minimal_config(),
        working_directory=tmp_path,
    )
    try:
        observer_ids = [
            registration.id
            for registration in engine.lifecycle_registry.registrations()
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


@pytest.mark.asyncio
async def test_assemble_engine_materializes_from_contributions(tmp_path: Path) -> None:
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


@pytest.mark.asyncio
async def test_assemble_engine_merges_catalog_lifecycle_observers(tmp_path: Path) -> None:
    @dataclass(slots=True)
    class _Module:
        descriptor: ModuleDescriptor

        def contribute(self, contributions: Contributions) -> None:
            contributions.lifecycle.add(
                id="catalog.before_turn",
                owner="catalog",
                order=50,
                observer=FunctionLifecycleObserver(),
            )

    catalog = BuiltinModuleCatalog(
        [_Module(descriptor=ModuleDescriptor(id="catalog", enabled=lambda _cfg: True))]
    )
    contributions = collect_builtin_contributions(_minimal_config(), catalog=catalog)
    handle = EngineHandle()
    engine = await assemble_engine(
        EngineAssemblyRequest(
            engine_cls=Engine,
            handle=handle,
            client=AsyncMock(),
            config=_minimal_config(),
            working_directory=tmp_path,
            contributions=contributions,
        )
    )
    try:
        observer_ids = [
            registration.id
            for registration in engine.lifecycle_registry.registrations()
        ]
        assert "catalog.before_turn" in observer_ids
        assert "memory.before_turn" in observer_ids
    finally:
        await engine.shutdown_session()
        handle.drain_events()


def test_attach_engine_capabilities_is_host_entrypoint() -> None:
    assert attach_engine_capabilities.__module__ == "deepseek_tui.host.engine_attach"


def test_register_engine_lifecycle_observers_is_host_entrypoint() -> None:
    from deepseek_tui.host.engine_lifecycle import register_engine_lifecycle_observers

    assert register_engine_lifecycle_observers.__module__ == "deepseek_tui.host.engine_lifecycle"
