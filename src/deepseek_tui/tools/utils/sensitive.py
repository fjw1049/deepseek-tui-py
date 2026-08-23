"""Sensitive-file guard for read-side and write-side tools.

Blocks the model from reading common credential files through tools
(read_file / grep_files / file_search), matching Claude Code's behaviour
(Glob/Grep skip ``.env``, Read refuses private keys). Conservative by
design: an explicit basename list, no broad globs, so false positives are
rare. Templates and public keys stay readable.

Write-side tools (write_file / edit_file) use ``is_sensitive_write_path``,
which adds ``.git/hooks`` on top of the read-side blocklist: overwriting a
hook is code execution on the next git operation, while merely reading one
is harmless.
"""

from __future__ import annotations

from pathlib import Path

_ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
_PRIVATE_KEY_NAMES = frozenset({"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"})
_SECRET_BASENAMES = frozenset(
    {
        "credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".envrc",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        ".secrets",
    }
)


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


def is_sensitive_write_path(path: Path) -> bool:
    """Write-side guard: the read-side blocklist plus anything under ``.git/hooks``."""
    if is_sensitive_path(path):
        return True
    parts = path.parts
    return any(
        parts[i] == ".git" and parts[i + 1] == "hooks"
        for i in range(len(parts) - 1)
    )
