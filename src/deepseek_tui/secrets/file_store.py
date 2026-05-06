"""JSON-on-disk fallback secret store.

Mirrors `FileKeyringStore` in
`docs/DeepSeek-TUI-main/crates/secrets/src/lib.rs:181-297`.

The fallback exists for headless Linux machines without a Secret
Service / dbus, but the implementation runs unchanged on macOS and
Windows so that test fixtures and `auto_detect()` paths stay portable.

Storage format::

    {
      "entries": {
        "deepseek": "sk-...",
        "openrouter": "or-..."
      }
    }

Unix invariants (do not regress — see issue #281 in the Rust repo):

* The directory is created with mode ``0o700``.
* The file is written with mode ``0o600`` and rejected on read if any
  group/other bit is set (mode & 0o077 != 0).
* ``set()``/``delete()`` MUST surface read errors instead of silently
  treating them as "empty blob"; doing so on insecure perms or corrupt
  JSON wipes every previously-stored secret on the next write.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from .errors import InsecurePermissionsError, SecretsError
from .store import KeyringStore

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["FileKeyringStore"]


_IS_UNIX = sys.platform != "win32"


class FileKeyringStore(KeyringStore):
    """JSON-backed keyring store with Unix permission enforcement."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def backend_name(self) -> str:
        return "file-based (~/.deepseek/secrets/)"

    @staticmethod
    def default_path() -> Path:
        """Resolve ``<home>/.deepseek/secrets/secrets.json``.

        Mirrors `FileKeyringStore::default_path` (Rust lib.rs:202-210).
        Uses :func:`pathlib.Path.home` which honours ``HOME`` on Unix
        and ``USERPROFILE`` on Windows.
        """
        try:
            home = Path.home()
        except (RuntimeError, OSError) as err:  # pragma: no cover
            raise SecretsError(
                "could not resolve home directory for FileKeyringStore"
            ) from err
        return home / ".deepseek" / "secrets" / "secrets.json"

    def get(self, key: str) -> str | None:
        with self._lock:
            blob = self._load_unlocked()
            return blob.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            # IMPORTANT (issue #281): surface read errors here. If we
            # fell back to an empty dict on any read failure, the next
            # store call would silently wipe every previously stored
            # secret. The Rust comment at lib.rs:275-283 covers this.
            blob = self._load_unlocked()
            blob[key] = value
            self._store_unlocked(blob)

    def delete(self, key: str) -> None:
        with self._lock:
            # Same #281 invariant as set(): never substitute an empty blob
            # on read error, or "delete <one-key>" becomes "delete every-key".
            blob = self._load_unlocked()
            blob.pop(key, None)
            self._store_unlocked(blob)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

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
            raise SecretsError(
                f"file-backed secret store I/O error: {err}"
            ) from err
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as err:
            raise SecretsError(
                f"file-backed secret store JSON error: {err}"
            ) from err
        return _coerce_blob(parsed)

    def _store_unlocked(self, blob: Mapping[str, str]) -> None:
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if _IS_UNIX:
            try:
                os.chmod(parent, 0o700)
            except OSError:
                # Best-effort; if it fails the file-level chmod below
                # still protects the secrets payload itself.
                pass
        body = json.dumps({"entries": dict(blob)}, indent=2)
        try:
            self._path.write_text(body, encoding="utf-8")
        except OSError as err:
            raise SecretsError(
                f"file-backed secret store I/O error: {err}"
            ) from err
        if _IS_UNIX:
            os.chmod(self._path, 0o600)


def _coerce_blob(parsed: object) -> dict[str, str]:
    """Validate & normalize a parsed JSON document into ``{key: value}``."""
    if not isinstance(parsed, dict):
        raise SecretsError(
            "file-backed secret store JSON error: top-level must be an object"
        )
    entries_obj = parsed.get("entries", {})
    if not isinstance(entries_obj, dict):
        raise SecretsError(
            "file-backed secret store JSON error: 'entries' must be an object"
        )
    out: dict[str, str] = {}
    for k, v in entries_obj.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise SecretsError(
                "file-backed secret store JSON error: entry keys/values "
                "must be strings"
            )
        out[k] = v
    return out
