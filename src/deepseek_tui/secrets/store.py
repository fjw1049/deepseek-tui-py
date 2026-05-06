"""Keyring-store abstraction with OS and in-memory backends.

Mirrors `KeyringStore`, `DefaultKeyringStore`, and `InMemoryKeyringStore`
in `docs/DeepSeek-TUI-main/crates/secrets/src/lib.rs:54-176`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock

import keyring as _keyring_pkg
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError

from .errors import SecretsError

__all__ = [
    "DEFAULT_SERVICE",
    "DefaultKeyringStore",
    "InMemoryKeyringStore",
    "KeyringStore",
]


# Same service label as Rust (lib.rs:27). On macOS, lets you verify with:
#   security find-generic-password -s deepseek -a <provider>
DEFAULT_SERVICE = "deepseek"


class KeyringStore(ABC):
    """Abstract secret store.

    Concrete implementations:
    - :class:`DefaultKeyringStore` — OS keyring (macOS Keychain etc.)
    - :class:`InMemoryKeyringStore` — tests
    - :class:`FileKeyringStore` — JSON-on-disk fallback (see file_store.py)
    """

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Return the stored value, or ``None`` if no entry exists."""

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        """Write a value, replacing any existing entry."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove an entry. No-op if the entry is absent."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Short, human-readable backend label (used by `doctor`)."""


class DefaultKeyringStore(KeyringStore):
    """OS keyring backend.

    macOS Keychain, Windows Credential Manager, Linux Secret Service /
    KWallet — all dispatched by the `keyring` Python package.
    """

    def __init__(self, service: str = DEFAULT_SERVICE) -> None:
        self._service = service

    @property
    def service(self) -> str:
        return self._service

    @property
    def backend_name(self) -> str:
        return "system keyring"

    def probe(self) -> None:
        """Probe the OS keyring without writing.

        Raises :class:`SecretsError` if no backend is reachable. This is
        equivalent to ``DefaultKeyringStore::probe`` in Rust (lib.rs:88-105).
        """
        try:
            # Calling get_password() with a sentinel surfaces "no backend
            # / no storage" without actually creating an entry.
            _keyring_pkg.get_password(self._service, "__probe__")
        except NoKeyringError as err:
            raise SecretsError(f"keyring backend error: {err}") from err
        except KeyringError as err:
            raise SecretsError(f"keyring backend error: {err}") from err

    def get(self, key: str) -> str | None:
        try:
            return _keyring_pkg.get_password(self._service, key)
        except KeyringError as err:
            raise SecretsError(f"keyring backend error: {err}") from err

    def set(self, key: str, value: str) -> None:
        try:
            _keyring_pkg.set_password(self._service, key, value)
        except KeyringError as err:
            raise SecretsError(f"keyring backend error: {err}") from err

    def delete(self, key: str) -> None:
        try:
            _keyring_pkg.delete_password(self._service, key)
        except PasswordDeleteError:
            # No entry == success, mirrors Rust's match-on-NoEntry.
            return
        except KeyringError as err:
            raise SecretsError(f"keyring backend error: {err}") from err


class InMemoryKeyringStore(KeyringStore):
    """Process-local in-memory store. For tests."""

    def __init__(self) -> None:
        self._entries: dict[str, str] = {}
        self._lock = Lock()

    @property
    def backend_name(self) -> str:
        return "in-memory (test)"

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._entries.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._entries[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)
