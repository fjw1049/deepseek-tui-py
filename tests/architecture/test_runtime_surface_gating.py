"""Architecture tests for feature-gated runtime surface catalog."""

from __future__ import annotations

from deepseek_tui.config.models import Config, EvolutionConfig, FeatureConfig
from deepseek_tui.host.assembler import collect_builtin_contributions


def test_default_config_exposes_only_mcp_surfaces() -> None:
    routes = collect_builtin_contributions(Config()).surfaces.routes()
    paths = {route.path for route in routes}
    assert paths == {"/v1/mcp/startup", "/v1/mcp/preload-status"}


def test_all_features_enabled_exposes_full_surface_set() -> None:
    cfg = Config(
        features=FeatureConfig(mcp=True, automations=True, tasks=True),
        evolution=EvolutionConfig(enabled=True),
    )
    routes = collect_builtin_contributions(cfg).surfaces.routes()
    assert len(routes) == 17
