"""Real-API integration helpers.

Shared utilities for tests that hit a live DeepSeek endpoint instead
of stubbing the network. Tests that import from here MUST be marked
with ``pytest.mark.skipif(...)`` or rely on the helpers below to
short-circuit when no API key is reachable.

Key resolution order (mirrors what a normal app run would see):

1. ``DEEPSEEK_API_KEY`` env var
2. ``[providers.deepseek] api_key`` from the project's
   ``config.toml`` (the file the user keeps at the repo root)
3. ``None`` -> the test that needs a key skips

We deliberately don't go through SecretsManager here because most of
these integration tests run before the Stage 1.4 wiring is complete.
Once the auto-detect Secrets façade is also integrated (integration
debt #4), the fallback will go through the same chain a real run
takes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover
    import tomli as _toml  # type: ignore[import-not-found]

# ``tests/_real_api.py`` lives at <repo>/tests/_real_api.py, so the
# repo root is one parent up.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROJECT_CONFIG = _REPO_ROOT / "config.toml"


def _read_key_from_project_config() -> str | None:
    if not _PROJECT_CONFIG.exists():
        return None
    try:
        with _PROJECT_CONFIG.open("rb") as fh:
            data: dict[str, Any] = _toml.load(fh)
    except (OSError, _toml.TOMLDecodeError):
        return None
    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        return None
    deepseek = providers.get("deepseek", {})
    if not isinstance(deepseek, dict):
        return None
    raw = deepseek.get("api_key")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def get_deepseek_api_key() -> str | None:
    """Return a usable DeepSeek API key, or ``None`` if unavailable.

    Honours ``DEEPSEEK_API_KEY`` then falls back to the project
    ``config.toml``. Empty / whitespace values are treated as missing
    so a stale env var doesn't mask the config.toml entry.
    """
    env_value = os.environ.get("DEEPSEEK_API_KEY")
    if env_value and env_value.strip():
        return env_value.strip()
    return _read_key_from_project_config()


def has_deepseek_api_key() -> bool:
    """Cheap predicate for ``pytest.mark.skipif``."""
    return get_deepseek_api_key() is not None


def get_deepseek_base_url() -> str:
    """Return the base URL the live tests should hit.

    Reads ``[providers.deepseek] base_url`` from project config when
    present, otherwise the public default. Does NOT honour env vars
    because we don't currently expose one for base URL — the project
    config is the single source of truth for that knob.
    """
    if _PROJECT_CONFIG.exists():
        try:
            with _PROJECT_CONFIG.open("rb") as fh:
                data: dict[str, Any] = _toml.load(fh)
        except (OSError, _toml.TOMLDecodeError):
            data = {}
        providers = data.get("providers", {})
        if isinstance(providers, dict):
            deepseek = providers.get("deepseek", {})
            if isinstance(deepseek, dict):
                base_url = deepseek.get("base_url")
                if isinstance(base_url, str) and base_url.strip():
                    return base_url.strip()
    return "https://api.deepseek.com"
