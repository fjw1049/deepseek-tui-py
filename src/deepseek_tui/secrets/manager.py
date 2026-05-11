"""Backwards-compatible high-level manager.

This module preserves the original ``SecretsManager`` API used by the
TUI/CLI while delegating actual secret storage to the new
:class:`~deepseek_tui.secrets.facade.Secrets` façade.

The Rust ``Secrets`` struct is intentionally a *two-layer* lookup
(``keyring → env → none``); the ``config.toml`` ``[providers.X] api_key``
fallback is the responsibility of the *caller*. ``SecretsManager`` is
that caller in this codebase, and stitches the third layer on after
:meth:`Secrets.resolve` returns ``None``.

Final precedence delivered by :meth:`SecretsManager.resolve_api_key`::

    keyring → env (with NVIDIA aliases etc.) → config.toml api_key → None

This is the order the user signed off on for the Python port; do NOT
swap layers without their approval (it changes how every login flow
behaves).
"""

from __future__ import annotations

from deepseek_tui.config.models import Config

from .errors import SecretsError
from .facade import Secrets
from .store import DEFAULT_SERVICE, KeyringStore

__all__ = ["SecretsManager"]


class SecretsManager:
    """Stable wrapper used by the rest of the codebase."""

    SERVICE_NAME = DEFAULT_SERVICE

    def __init__(self, secrets: Secrets | None = None) -> None:
        self._secrets = secrets if secrets is not None else Secrets.auto_detect()

    @property
    def store(self) -> KeyringStore:
        return self._secrets.store

    @property
    def backend_name(self) -> str:
        return self._secrets.backend_name

    # ------------------------------------------------------------------
    # API key resolution
    # ------------------------------------------------------------------

    def resolve_api_key(
        self, config: Config, provider_name: str | None = None
    ) -> str | None:
        """Resolve an API key with ``keyring → env → config`` precedence.

        Behavior:

        1. Look up ``provider`` in the keyring (returning ``None`` for
           empty/whitespace values, matching Rust lib.rs:367).
        2. Otherwise return the canonical env value via
           :func:`env_for` — this includes the NVIDIA alias chain.
        3. Otherwise return ``config.providers[provider].api_key`` if
           present and non-empty.
        4. Otherwise ``None``.
        """
        provider = provider_name or config.provider

        # Layers 1 + 2 (keyring + env): delegate to the façade.
        resolved = self._secrets.resolve(provider)
        if resolved is not None:
            return resolved

        # Layer 3 (config-file): the wrapped layer that Rust leaves to
        # callers. Treat empty/whitespace values as unset for symmetry.
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
        self._secrets.set(provider, value)

    def delete_api_key(self, provider: str) -> bool:
        """Delete a stored key. Returns False when no key was present."""
        # Mirror the legacy contract: True iff something was actually
        # stored. We probe before deleting to make the boolean meaningful.
        try:
            existed = self._secrets.get(provider) is not None
        except SecretsError:
            existed = False
        try:
            self._secrets.delete(provider)
        except SecretsError:
            return False
        return existed

    def list_providers(self, config: Config) -> list[str]:
        providers = set(config.providers)
        providers.add(config.provider)
        return sorted(providers)
