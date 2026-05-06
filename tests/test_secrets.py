"""High-level SecretsManager tests.

After Stage 1.2 the precedence is ``keyring → env → config.toml → None``,
not ``env → config → keyring`` like the original Python port. Tests have
been rewritten to inject :class:`~deepseek_tui.secrets.InMemoryKeyringStore`
so they no longer depend on whatever keyring backend the CI host
happens to expose, and to assert the corrected order.

Detailed parity tests (including NVIDIA aliases, blank-value semantics,
file-store invariants, etc.) live in
``tests/parity/phase_a/test_secrets.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.secrets import (
    InMemoryKeyringStore,
    Secrets,
    SecretsManager,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Shared env hygiene: tests poke real env vars through monkeypatch, so
# strip every known provider env before each test runs.
# ---------------------------------------------------------------------------


_KNOWN_ENVS = (
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "NOVITA_API_KEY",
    "NVIDIA_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _clear_known_envs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for var in _KNOWN_ENVS:
        monkeypatch.delenv(var, raising=False)
    yield


def _make_manager(store: InMemoryKeyringStore | None = None) -> SecretsManager:
    return SecretsManager(Secrets(store or InMemoryKeyringStore()))


# ---------------------------------------------------------------------------
# Precedence semantics
# ---------------------------------------------------------------------------


def test_resolve_api_key_prefers_keyring_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule: a value in the keyring must beat the env var."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-secret")
    store = InMemoryKeyringStore()
    store.set("deepseek", "ring-secret")
    config = Config(providers={"deepseek": ProviderConfig(api_key="config-secret")})

    assert _make_manager(store).resolve_api_key(config) == "ring-secret"


def test_resolve_api_key_prefers_env_over_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the keyring is empty, env beats config.toml."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-secret")
    config = Config(providers={"deepseek": ProviderConfig(api_key="config-secret")})

    assert _make_manager().resolve_api_key(config) == "env-secret"


def test_resolve_api_key_falls_back_to_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No keyring + no env → fall through to the TOML api_key field."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = Config(providers={"deepseek": ProviderConfig(api_key="config-secret")})

    assert _make_manager().resolve_api_key(config) == "config-secret"


def test_resolve_api_key_returns_none_when_all_layers_empty() -> None:
    config = Config(providers={"deepseek": ProviderConfig()})
    assert _make_manager().resolve_api_key(config) is None


# ---------------------------------------------------------------------------
# Provider listing
# ---------------------------------------------------------------------------


def test_list_providers_includes_active_and_configured() -> None:
    config = Config(
        provider="deepseek",
        providers={
            "deepseek": ProviderConfig(),
            "openai": ProviderConfig(),
        },
    )

    assert _make_manager().list_providers(config) == ["deepseek", "openai"]


# ---------------------------------------------------------------------------
# Multi-provider lookup
# ---------------------------------------------------------------------------


def test_resolve_api_key_for_multiple_providers() -> None:
    config = Config(
        provider="openai",
        providers={
            "deepseek": ProviderConfig(api_key="deepseek-secret"),
            "openai": ProviderConfig(api_key="openai-secret"),
        },
    )
    manager = _make_manager()
    assert manager.resolve_api_key(config, provider_name="openai") == "openai-secret"
    assert manager.resolve_api_key(config, provider_name="deepseek") == "deepseek-secret"


# ---------------------------------------------------------------------------
# delete_api_key returns True iff something was actually removed.
# ---------------------------------------------------------------------------


def test_delete_api_key_returns_false_when_missing() -> None:
    manager = _make_manager()
    assert manager.delete_api_key("deepseek") is False


def test_delete_api_key_returns_true_when_removed() -> None:
    store = InMemoryKeyringStore()
    store.set("deepseek", "sk-remove-me")
    manager = _make_manager(store)

    assert manager.delete_api_key("deepseek") is True
    # And it really did get removed.
    assert store.get("deepseek") is None
