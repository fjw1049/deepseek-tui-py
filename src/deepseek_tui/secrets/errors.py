"""Errors raised by secret-store backends.

Mirrors the variants of `SecretsError` in
`docs/DeepSeek-TUI-main/crates/secrets/src/lib.rs:30-49`.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["InsecurePermissionsError", "SecretsError"]


class SecretsError(Exception):
    """Base class for any error a secret-store backend may surface."""


class InsecurePermissionsError(SecretsError):
    """Raised when an on-disk secrets file has unsafe Unix permissions.

    Mirrors `SecretsError::InsecurePermissions` in the Rust enum.
    """

    def __init__(self, path: Path, mode: int) -> None:
        super().__init__(
            f"file-backed secret store at {path} has insecure "
            f"permissions {mode:o} (expected 0600)"
        )
        self.path = path
        self.mode = mode
