"""Secret storage with the Rust hard-rule lookup precedence.

Public surface:

* :class:`SecretsManager` — stable high-level wrapper used by the rest
  of the codebase. Layers ``keyring → env → config.toml → None``.
* :class:`Secrets` — the two-layer façade used by Rust
  (``keyring → env → None``). Use this directly when you don't need the
  TOML config-file fallback.
* :class:`KeyringStore` — abstract backend.
* :class:`DefaultKeyringStore` — OS keyring (macOS Keychain etc.).
* :class:`InMemoryKeyringStore` — process-local store, for tests.
* :class:`FileKeyringStore` — JSON-on-disk fallback for headless
  environments.
* :func:`env_for` — provider name → environment variable lookup.
* :data:`DEFAULT_SERVICE` — Keychain/credential-store service label.
* :class:`SecretsError`, :class:`InsecurePermissionsError` — error
  types.
"""

from .env_map import env_for
from .errors import InsecurePermissionsError, SecretsError
from .facade import Secrets
from .file_store import FileKeyringStore
from .manager import SecretsManager
from .store import (
    DEFAULT_SERVICE,
    DefaultKeyringStore,
    InMemoryKeyringStore,
    KeyringStore,
)

__all__ = [
    "DEFAULT_SERVICE",
    "DefaultKeyringStore",
    "FileKeyringStore",
    "InMemoryKeyringStore",
    "InsecurePermissionsError",
    "KeyringStore",
    "Secrets",
    "SecretsError",
    "SecretsManager",
    "env_for",
]
