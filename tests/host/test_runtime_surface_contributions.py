"""Characterization tests for capability runtime surface contributions."""

from __future__ import annotations

import pytest
from starlette.routing import Route

from deepseek_tui.capabilities.runtime_surfaces import register_builtin_runtime_surfaces
from deepseek_tui.config.models import Config, EvolutionConfig, FeatureConfig
from deepseek_tui.host.assembler import collect_builtin_contributions
from deepseek_tui.host.surfaces import (
    RuntimeSurfaceRegistry,
    RuntimeSurfaceRegistryError,
    build_surface_router,
)


def _route_keys(router: object) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for route in router.routes:  # type: ignore[attr-defined]
        if not isinstance(route, Route):
            continue
        for method in route.methods:
            if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                keys.add((method, route.path))
    return keys


def _static_runtime_route_keys() -> set[tuple[str, str]]:
    from deepseek_tui.app_server.runtime_api.routes import build_runtime_api_router

    return _route_keys(build_runtime_api_router())


def _enabled_config() -> Config:
    return Config(
        features=FeatureConfig(mcp=True, automations=True, tasks=True),
        evolution=EvolutionConfig(enabled=True),
    )


def test_capability_surface_paths_match_static_runtime_router() -> None:
    static = _static_runtime_route_keys()
    registry = RuntimeSurfaceRegistry()
    register_builtin_runtime_surfaces(registry, _enabled_config())

    contributed = {(route.method, route.path) for route in registry.routes()}
    assert contributed.issubset(static)
    assert len(contributed) == 17
    assert ("GET", "/v1/evolution/pending") in contributed
    assert ("POST", "/v1/mcp/startup") in contributed
    assert ("POST", "/v1/triggers") in contributed
    assert ("GET", "/v1/automations") in contributed


def test_collect_builtin_contributions_registers_runtime_surfaces() -> None:
    assembled = collect_builtin_contributions(Config())
    contributed = {(route.method, route.path) for route in assembled.surfaces.routes()}
    assert len(contributed) == 17


def test_build_runtime_api_router_mounts_capability_surfaces() -> None:
    from deepseek_tui.app_server.runtime_api.routes import build_runtime_api_router

    assembled = collect_builtin_contributions(Config())
    contributed = {(route.method, route.path) for route in assembled.surfaces.routes()}
    mounted = _route_keys(build_runtime_api_router())
    assert contributed.issubset(mounted)


def test_mount_surface_router_matches_contributed_paths() -> None:
    registry = RuntimeSurfaceRegistry()
    register_builtin_runtime_surfaces(registry, _enabled_config())
    mounted = _route_keys(build_surface_router(registry))
    contributed = {(route.method, route.path) for route in registry.routes()}
    assert mounted == contributed


def test_runtime_surface_registry_rejects_duplicate_capability_route() -> None:
    registry = RuntimeSurfaceRegistry()
    register_builtin_runtime_surfaces(registry, _enabled_config())

    with pytest.raises(RuntimeSurfaceRegistryError, match="already registered"):
        registry.add_route(
            id="duplicate",
            owner="test",
            method="GET",
            path="/v1/evolution/pending",
            handler=lambda: {"ok": True},
        )


def test_register_builtin_runtime_surfaces_matches_catalog_surface_count() -> None:
    registry = RuntimeSurfaceRegistry()
    register_builtin_runtime_surfaces(
        registry,
        Config(
            features=FeatureConfig(mcp=False, automations=False),
            evolution=EvolutionConfig(enabled=False),
        ),
    )
    catalog = collect_builtin_contributions(Config())
    assert len(registry.routes()) == len(catalog.surfaces.routes()) == 17
