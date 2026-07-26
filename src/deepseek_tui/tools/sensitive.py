"""Sensitive-file guard for read-side tools.

Blocks the model from reading common credential files through tools
(read_file / grep_files / file_search), matching Claude Code's behaviour
(Glob/Grep skip ``.env``, Read refuses private keys). Conservative by
design: an explicit basename list, no broad globs, so false positives are
rare. Templates and public keys stay readable.
"""

from __future__ import annotations

from pathlib import Path

_ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
_PRIVATE_KEY_NAMES = frozenset({"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"})
_SECRET_BASENAMES = frozenset({"credentials", ".netrc", ".npmrc", ".pypirc"})


def is_sensitive_path(path: Path) -> bool:
    """Return True if ``path`` names a file tools must not hand to the model."""
    name = path.name
    if name in _ENV_TEMPLATES:
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name in _PRIVATE_KEY_NAMES:
        return True
    if name.endswith((".pem", ".key")):
        return True
    if name in _SECRET_BASENAMES:
        return True
    return False
