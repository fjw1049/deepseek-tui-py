"""Characterization tests for capability runtime surface contributions."""

from __future__ import annotations

import pytest
from starlette.routing import Route

from deepseek_tui.config.models import Config, EvolutionConfig, FeatureConfig
from deepseek_tui.host.assembler import collect_builtin_contributions
from deepseek_tui.host.surfaces import (
    RuntimeSurfaceRegistry,
    RuntimeSurfaceRegistryError,
    build_surface_router,
)


def _register_catalog_surfaces(registry: RuntimeSurfaceRegistry, config: Config) -> None:
    assembled = collect_builtin_contributions(config)
    registry.merge_routes_from(assembled.surfaces)


def _route_keys(router: object) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for route in router.routes:  # type: ignore[attr-defined]
        if not isinstance(route, Route):
            continue
        for method in route.methods:
            if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                keys.add((method, route.path))
    return keys


def _static_runtime_route_keys(config: Config | None = None) -> set[tuple[str, str]]:
    from deepseek_tui.app_server.runtime_api.routes import build_runtime_api_router

    return _route_keys(build_runtime_api_router(config))


def _enabled_config() -> Config:
    return Config(
        features=FeatureConfig(mcp=True, automations=True, tasks=True),
        evolution=EvolutionConfig(enabled=True),
    )


def _surface_count(config: Config) -> int:
    return len(collect_builtin_contributions(config).surfaces.routes())


def test_capability_surface_paths_match_static_runtime_router() -> None:
    cfg = _enabled_config()
    static = _static_runtime_route_keys(cfg)
    registry = RuntimeSurfaceRegistry()
    _register_catalog_surfaces(registry, cfg)

    contributed = {(route.method, route.path) for route in registry.routes()}
    assert contributed.issubset(static)
    assert len(contributed) == 17
    assert ("GET", "/v1/evolution/pending") in contributed
    assert ("POST", "/v1/mcp/startup") in contributed
    assert ("POST", "/v1/triggers") in contributed
    assert ("GET", "/v1/automations") in contributed


def test_collect_builtin_contributions_registers_runtime_surfaces_by_feature() -> None:
    default = collect_builtin_contributions(Config())
    assert _surface_count(Config()) == 2
    assert len(default.surfaces.routes()) == 2

    enabled = collect_builtin_contributions(_enabled_config())
    assert len(enabled.surfaces.routes()) == 17


def test_build_runtime_api_router_mounts_capability_surfaces() -> None:
    from deepseek_tui.app_server.runtime_api.routes import build_runtime_api_router

    cfg = _enabled_config()
    assembled = collect_builtin_contributions(cfg)
    contributed = {(route.method, route.path) for route in assembled.surfaces.routes()}
    mounted = _route_keys(build_runtime_api_router(cfg))
    assert contributed.issubset(mounted)


def test_mount_surface_router_matches_contributed_paths() -> None:
    cfg = _enabled_config()
    registry = RuntimeSurfaceRegistry()
    _register_catalog_surfaces(registry, cfg)
    mounted = _route_keys(build_surface_router(registry))
    contributed = {(route.method, route.path) for route in registry.routes()}
    assert mounted == contributed


def test_runtime_surface_registry_rejects_duplicate_capability_route() -> None:
    cfg = _enabled_config()
    registry = RuntimeSurfaceRegistry()
    _register_catalog_surfaces(registry, cfg)

    with pytest.raises(RuntimeSurfaceRegistryError, match="already registered"):
        registry.add_route(
            id="duplicate",
            owner="test",
            method="GET",
            path="/v1/evolution/pending",
            handler=lambda: {"ok": True},
        )


def test_register_catalog_surfaces_matches_catalog_surface_count() -> None:
    cfg = Config(
        features=FeatureConfig(mcp=False, automations=False),
        evolution=EvolutionConfig(enabled=False),
    )
    registry = RuntimeSurfaceRegistry()
    _register_catalog_surfaces(registry, cfg)
    catalog = collect_builtin_contributions(cfg)
    assert len(registry.routes()) == len(catalog.surfaces.routes()) == 0


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (
            Config(
                features=FeatureConfig(mcp=True, automations=False, tasks=True),
                evolution=EvolutionConfig(enabled=False),
            ),
            2,
        ),
        (
            Config(
                features=FeatureConfig(mcp=False, automations=False, tasks=True),
                evolution=EvolutionConfig(enabled=True),
            ),
            3,
        ),
        (
            Config(
                features=FeatureConfig(mcp=False, automations=True, tasks=True),
                evolution=EvolutionConfig(enabled=False),
            ),
            12,
        ),
        (_enabled_config(), 17),
    ],
)
def test_runtime_surface_count_follows_feature_gates(config: Config, expected: int) -> None:
    assert _surface_count(config) == expected


def test_runtime_surface_create_route_preserves_status_code() -> None:
    from deepseek_tui.capabilities.automation import contribute_runtime_surfaces

    registry = RuntimeSurfaceRegistry()
    contribute_runtime_surfaces(registry)

    create_route = next(
        route
        for route in registry.routes()
        if route.method == "POST" and route.path == "/v1/automations"
    )
    assert create_route.status_code == 201

    mounted = build_surface_router(registry)
    route = next(
        item
        for item in mounted.routes  # type: ignore[attr-defined]
        if isinstance(item, Route)
        and item.path == "/v1/automations"
        and "POST" in item.methods
    )
    assert route.status_code == 201
