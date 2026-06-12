"""Assembler materialization parity tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.host.assembler import collect_builtin_contributions
from deepseek_tui.host.catalog import BuiltinModuleCatalog
from deepseek_tui.host.contributions import Contributions
from deepseek_tui.host.module import ModuleDescriptor
from deepseek_tui.host.services import ServiceScope
from deepseek_tui.tools.runtime import materialize_tool_runtime


class CatalogService:
    def __init__(self, value: str) -> None:
        self.value = value


@dataclass(slots=True)
class _Module:
    descriptor: ModuleDescriptor
    on_contribute: Callable[[Contributions], None]

    def contribute(self, contributions: Contributions) -> None:
        self.on_contribute(contributions)


@pytest.mark.asyncio
async def test_materialized_runtime_merges_catalog_services(tmp_path: Path) -> None:
    catalog_service = CatalogService("from-catalog")

    def _register(contributions: Contributions) -> None:
        contributions.services.add(
            CatalogService,
            catalog_service,
            owner="test",
            scope=ServiceScope.PROCESS,
        )

    catalog = BuiltinModuleCatalog(
        [
            _Module(
                descriptor=ModuleDescriptor(id="catalog-service", enabled=lambda _c: True),
                on_contribute=_register,
            )
        ]
    )
    cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False))
    assembled = collect_builtin_contributions(cfg, catalog=catalog)

    runtime = await materialize_tool_runtime(
        config=cfg,
        working_directory=tmp_path,
        contributions=assembled,
    )
    try:
        assert runtime.context.services.optional(CatalogService) is catalog_service
    finally:
        await runtime.shutdown()
