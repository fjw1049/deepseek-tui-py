"""Backwards-compatible high-level manager.

This module preserves the original ``SecretsManager`` API used by the
TUI/CLI while delegating optional secret *storage* to the
:class:`~deepseek_tui.secrets.facade.Secrets` façade.

Runtime API-key resolution intentionally does **not** read the OS
keychain (macOS Keychain / Credential Manager / Secret Service): on
macOS the per-binary keychain ACL prompts for the login password every
time a different Python interpreter reads the item, which is hostile to
local dev. Keys come from env vars or ``config.toml`` instead:

    env (with NVIDIA aliases etc.) → config.toml api_key → None

The keychain backend is still available on demand for the explicit
``deepseek auth`` CLI commands via :attr:`store` / :meth:`set_api_key`,
but it is constructed lazily so a normal runtime start never touches it.
"""

from __future__ import annotations

from deepseek_tui.config.models import Config

from . import SecretsError
from .env_map import env_for
from .facade import Secrets
from .store import DEFAULT_SERVICE, KeyringStore

__all__ = ["SecretsManager"]


class SecretsManager:
    """Stable wrapper used by the rest of the codebase."""

    SERVICE_NAME = DEFAULT_SERVICE

    def __init__(self, secrets: Secrets | None = None) -> None:
        # Built lazily: runtime key resolution no longer uses the OS keychain,
        # so a plain ``SecretsManager()`` must never construct/probe it.
        self._secrets = secrets

    def _ensure_secrets(self) -> Secrets:
        if self._secrets is None:
            self._secrets = Secrets.auto_detect()
        return self._secrets

    @property
    def store(self) -> KeyringStore:
        return self._ensure_secrets().store

    @property
    def backend_name(self) -> str:
        return self._ensure_secrets().backend_name

    # ------------------------------------------------------------------
    # API key resolution
    # ------------------------------------------------------------------

    def resolve_api_key(
        self, config: Config, provider_name: str | None = None
    ) -> str | None:
        """Resolve an API key from ``env → config.toml`` (no OS keychain)."""
        provider = provider_name or config.provider

        env_val = env_for(provider)
        if env_val is not None and env_val.strip():
            return env_val

        provider_config = config.providers.get(provider)
        if provider_config and provider_config.api_key:
            value = provider_config.api_key
            if value.strip():
                return value

        # Layer 4: top-level config.api_key fallback (used by doctor/CLI).
        if config.api_key and config.api_key.strip():
            return config.api_key

        return None

    # ------------------------------------------------------------------
    # Convenience helpers (kept for back-compat with old call sites)
    # ------------------------------------------------------------------

    def set_api_key(self, provider: str, value: str) -> None:
        self._ensure_secrets().set(provider, value)

    def delete_api_key(self, provider: str) -> bool:
        """Delete a stored key. Returns False when no key was present."""
        # Mirror the legacy contract: True iff something was actually
        # stored. We probe before deleting to make the boolean meaningful.
        secrets = self._ensure_secrets()
        try:
            existed = secrets.get(provider) is not None
        except SecretsError:
            existed = False
        try:
            secrets.delete(provider)
        except SecretsError:
            return False
        return existed

    def list_providers(self, config: Config) -> list[str]:
        providers = set(config.providers)
        providers.add(config.provider)
        return sorted(providers)
