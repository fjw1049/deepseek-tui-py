"""Secret storage — keyring backends, env mapping, facade, and manager.

Consolidates the former secrets/ package (env_map, store, file_store, facade, manager).
"""

from __future__ import annotations



import json
import logging
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

import keyring as _keyring_pkg
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from deepseek_tui.config.models import Config

_LOG = logging.getLogger(__name__)


# ============================================================================
# Errors
# ============================================================================


class SecretsError(Exception):
    """Base class for any error a secret-store backend may surface."""


class InsecurePermissionsError(SecretsError):
    def __init__(self, path: Path, mode: int) -> None:
        super().__init__(
            f"file-backed secret store at {path} has insecure "
            f"permissions {mode:o} (expected 0600)"
        )
        self.path = path
        self.mode = mode


# ============================================================================
# Environment variable mapping (formerly env_map.py)
# ============================================================================

_PROVIDER_ENV_CANDIDATES: dict[str, tuple[str, ...]] = {
    "deepseek": ("DEEPSEEK_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "novita": ("NOVITA_API_KEY",),
    "nvidia": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "nvidia-nim": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "nvidia_nim": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "nim": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "volcengine-ark": ("ARK_API_KEY", "VOLCENGINE_API_KEY"),
    "volcengine-ark-anthropic": ("ARK_API_KEY", "VOLCENGINE_API_KEY"),
}


def env_for(name: str) -> str | None:
    """Return the API key for a provider from the environment, or None."""
    candidates = _PROVIDER_ENV_CANDIDATES.get(name.lower())
    if candidates is None:
        return None
    for var in candidates:
        value = os.environ.get(var)
        if value is not None and value.strip():
            return value
    return None


# ============================================================================
# KeyringStore abstraction (formerly store.py)
# ============================================================================

DEFAULT_SERVICE = "deepseek"
_IS_UNIX = sys.platform != "win32"


class KeyringStore(ABC):
    @abstractmethod
    def get(self, key: str) -> str | None: ...

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @property
    @abstractmethod
    def backend_name(self) -> str: ...


class DefaultKeyringStore(KeyringStore):
    def __init__(self, service: str = DEFAULT_SERVICE) -> None:
        self._service = service

    @property
    def service(self) -> str:
        return self._service

    @property
    def backend_name(self) -> str:
        return "system keyring"

    def probe(self) -> None:
        try:
            _keyring_pkg.get_password(self._service, "__probe__")
        except (NoKeyringError, KeyringError) as err:
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
            if sys.platform == "darwin":
                self._macos_security_set(key, value)
                return
            raise SecretsError(f"keyring backend error: {err}") from err

    def delete(self, key: str) -> None:
        try:
            _keyring_pkg.delete_password(self._service, key)
        except PasswordDeleteError:
            return
        except KeyringError as err:
            raise SecretsError(f"keyring backend error: {err}") from err

    def _macos_security_set(self, account: str, value: str) -> None:
        proc = subprocess.run(
            ["security", "add-generic-password", "-s", self._service,
             "-a", account, "-w", value, "-U"],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise SecretsError(f"keyring backend error: macOS security(1) failed: {detail}")


class InMemoryKeyringStore(KeyringStore):
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


# ============================================================================
# FileKeyringStore (formerly file_store.py)
# ============================================================================


class FileKeyringStore(KeyringStore):
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def backend_name(self) -> str:
        return "file-based (./.deepseek/secrets/)"

    @staticmethod
    def default_path() -> Path:
        from deepseek_tui.config.paths import user_deepseek_dir
        try:
            return user_deepseek_dir() / "secrets" / "secrets.json"
        except (RuntimeError, OSError) as err:
            raise SecretsError(
                "could not resolve ~/.deepseek directory for FileKeyringStore"
            ) from err

    def get(self, key: str) -> str | None:
        with self._lock:
            blob = self._load_unlocked()
            return blob.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            blob = self._load_unlocked()
            blob[key] = value
            self._store_unlocked(blob)

    def delete(self, key: str) -> None:
        with self._lock:
            blob = self._load_unlocked()
            blob.pop(key, None)
            self._store_unlocked(blob)

    def _load_unlocked(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        if _IS_UNIX:
            mode = self._path.stat().st_mode & 0o777
            if mode & 0o077 != 0:
                raise InsecurePermissionsError(self._path, mode)
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as err:
            raise SecretsError(f"file-backed secret store I/O error: {err}") from err
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as err:
            raise SecretsError(f"file-backed secret store JSON error: {err}") from err
        return _coerce_blob(parsed)

    def _store_unlocked(self, blob: Mapping[str, str]) -> None:
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if _IS_UNIX:
            try:
                os.chmod(parent, 0o700)
            except OSError:
                pass
        body = json.dumps({"entries": dict(blob)}, indent=2)
        try:
            self._path.write_text(body, encoding="utf-8")
        except OSError as err:
            raise SecretsError(f"file-backed secret store I/O error: {err}") from err
        if _IS_UNIX:
            os.chmod(self._path, 0o600)


def _coerce_blob(parsed: object) -> dict[str, str]:
    if not isinstance(parsed, dict):
        raise SecretsError("file-backed secret store JSON error: top-level must be an object")
    entries_obj = parsed.get("entries", {})
    if not isinstance(entries_obj, dict):
        raise SecretsError("file-backed secret store JSON error: 'entries' must be an object")
    out: dict[str, str] = {}
    for k, v in entries_obj.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise SecretsError(
                "file-backed secret store JSON error: entry keys/values must be strings"
            )
        out[k] = v
    return out


# ============================================================================
# Secrets facade (formerly facade.py)
# ============================================================================


class Secrets:
    """Facade combining a keyring backend with env-var fallbacks."""

    def __init__(self, store: KeyringStore, service: str = DEFAULT_SERVICE) -> None:
        self._store = store
        self._service = service

    @property
    def store(self) -> KeyringStore:
        return self._store

    @property
    def backend_name(self) -> str:
        return self._store.backend_name

    @classmethod
    def auto_detect(cls) -> Secrets:
        default_store = DefaultKeyringStore()
        try:
            default_store.probe()
        except Exception as err:
            _LOG.warning("OS keyring unavailable (%s); falling back to file-backed secret store", err)
            try:
                path = FileKeyringStore.default_path()
            except Exception:
                path = Path(".deepseek-secrets.json")
            return cls(FileKeyringStore(path))
        return cls(default_store)

    def resolve(self, name: str) -> str | None:
        try:
            stored = self._store.get(name)
        except Exception as err:
            _LOG.warning("keyring read for %r failed: %s", name, err)
            stored = None
        if stored is not None and stored.strip():
            return stored
        return env_for(name)

    def get(self, name: str) -> str | None:
        return self._store.get(name)

    def set(self, name: str, value: str) -> None:
        self._store.set(name, value)

    def delete(self, name: str) -> None:
        self._store.delete(name)


# ============================================================================
# SecretsManager (formerly manager.py)
# ============================================================================


class SecretsManager:
    """Stable high-level wrapper: keyring → env → config.toml → None."""

    SERVICE_NAME = DEFAULT_SERVICE

    def __init__(self, secrets: Secrets | None = None) -> None:
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

    def resolve_api_key(self, config: Config, provider_name: str | None = None) -> str | None:
        provider = provider_name or config.provider

        if not os.environ.get("DEEPSEEK_SKIP_KEYRING"):
            try:
                stored = self._ensure_secrets().get(provider)
            except Exception:
                stored = None
            if stored is not None and stored.strip():
                return stored

        env_val = env_for(provider)
        if env_val is not None and env_val.strip():
            return env_val

        provider_config = config.providers.get(provider)
        if provider_config and provider_config.api_key:
            value = provider_config.api_key
            if value.strip():
                return value

        if config.api_key and config.api_key.strip():
            return config.api_key

        return None

    def set_api_key(self, provider: str, value: str) -> None:
        self._ensure_secrets().set(provider, value)

    def delete_api_key(self, provider: str) -> bool:
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
