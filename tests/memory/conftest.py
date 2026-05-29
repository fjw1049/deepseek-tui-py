"""Memory test fixtures — live API opt-in via ``-m live``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_api_key() -> str | None:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    return key or None


def _apply_live_api_key(cfg: Config) -> Config:
    """``DEEPSEEK_API_KEY`` wins over stale keys in project config.toml."""
    key = _env_api_key()
    if not key:
        return cfg
    overrides: dict = {
        "api_key": key,
        "providers": {"deepseek": {"api_key": key}},
    }
    emb_key = os.environ.get("DEEPSEEK_EMBEDDING_API_KEY", "").strip()
    emb_url = os.environ.get("DEEPSEEK_EMBEDDING_BASE_URL", "").strip()
    if emb_key or emb_url:
        smart_patch: dict = {}
        if emb_key:
            smart_patch["embedding_api_key"] = emb_key
        if emb_url:
            smart_patch["embedding_base_url"] = emb_url
        overrides["memory"] = {"smart": smart_patch}
    return Config.merge_dict(cfg, overrides)


def _has_api_key(cfg: Config) -> bool:
    if _env_api_key():
        return True
    pc = cfg.effective_provider_config()
    return bool(cfg.api_key or pc.api_key)


@pytest.fixture(scope="module")
def live_project_config():
    """Project config with API key; skip when missing.

    Live runs use ``DEEPSEEK_SKIP_KEYRING=1`` so env/config beat macOS keychain.
    """
    os.environ["DEEPSEEK_SKIP_KEYRING"] = "1"
    cfg = _apply_live_api_key(ConfigLoader().load(workspace=PROJECT_ROOT))
    if not _has_api_key(cfg):
        pytest.skip("no DEEPSEEK_API_KEY env or api_key in .deepseek/config.toml")
    return cfg


def pytest_collection_modifyitems(config, items) -> None:
    """Skip ``@pytest.mark.live`` unless the user explicitly selects ``-m live``."""
    markexpr = config.getoption("-m", default="") or ""
    if "live" in markexpr and "not live" not in markexpr:
        return
    skip = pytest.mark.skip(reason="pass -m live to run real API memory tests")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
