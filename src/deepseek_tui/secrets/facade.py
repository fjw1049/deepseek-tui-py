"""High-level secret façade combining a backend store with env fallbacks.

Mirrors the `Secrets` struct in
`docs/DeepSeek-TUI-main/crates/secrets/src/lib.rs:299-388`.

Lookup precedence (Rust hard rule, lib.rs:14):

    keyring → env → none

Callers that want a third "config-file" tier (e.g. our TOML config with
``[providers.deepseek] api_key = ...``) wire it on top of this façade.
The Python `SecretsManager` shim in :mod:`deepseek_tui.secrets.manager`
does exactly that — it's the explicit "caller" the Rust comment refers
to.
"""

from __future__ import annotations

import logging

from .env_map import env_for
from .file_store import FileKeyringStore
from .store import (
    DEFAULT_SERVICE,
    DefaultKeyringStore,
    KeyringStore,
)

__all__ = ["Secrets"]

_LOG = logging.getLogger(__name__)


class Secrets:
    """Façade combining a keyring backend with env-var fallbacks."""

    def __init__(self, store: KeyringStore, service: str = DEFAULT_SERVICE) -> None:
        self._store = store
        self._service = service

    @property
    def store(self) -> KeyringStore:
        return self._store

    @property
    def backend_name(self) -> str:
        return self._store.backend_name

    def __repr__(self) -> str:
        return (
            f"Secrets(backend={self._store.backend_name!r}, "
            f"service={self._service!r})"
        )

    @classmethod
    def auto_detect(cls) -> Secrets:
        """Build a façade with the best available backend.

        On platforms with a working OS keyring this returns
        :class:`DefaultKeyringStore`; otherwise it falls back to
        :class:`FileKeyringStore` under
        ``~/.deepseek/secrets/secrets.json``.

        Mirrors `Secrets::auto_detect` (Rust lib.rs:338-351).
        """
        default_store = DefaultKeyringStore()
        try:
            default_store.probe()
        except Exception as err:  # pragma: no cover — depends on host
            _LOG.warning(
                "OS keyring unavailable (%s); falling back to file-backed "
                "secret store",
                err,
            )
            try:
                path = FileKeyringStore.default_path()
            except Exception:  # pragma: no cover
                from pathlib import Path
                path = Path(".deepseek-secrets.json")
            return cls(FileKeyringStore(path))
        return cls(default_store)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> str | None:
        """Resolve a secret with ``keyring → env → none`` precedence.

        Empty/whitespace values on either layer are treated as "unset",
        matching Rust's ``v.trim().is_empty()`` checks (lib.rs:367, 410).
        """
        try:
            stored = self._store.get(name)
        except Exception as err:
            _LOG.warning("keyring read for %r failed: %s", name, err)
            stored = None
        if stored is not None and stored.strip():
            return stored
        return env_for(name)

    def get(self, name: str) -> str | None:
        """Read a secret directly (no env fallback)."""
        return self._store.get(name)

    def set(self, name: str, value: str) -> None:
        """Write a secret through the underlying store."""
        self._store.set(name, value)

    def delete(self, name: str) -> None:
        """Delete a secret through the underlying store. No-op if absent."""
        self._store.delete(name)
