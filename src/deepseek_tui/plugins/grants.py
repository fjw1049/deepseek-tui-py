"""Digest-bound authorization grants, separate from plugin permission claims."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.config.paths import user_deepseek_dir
from deepseek_tui.plugins.identity import is_safe_plugin_id, validate_plugin_id
from deepseek_tui.utils import write_json_atomic

EXECUTION_CAPABILITIES = frozenset(
    {
        "hooks.execute",
        "mcp.connect",
        "process.spawn",
        "package.install-scripts",
    }
)

# Capabilities that execute arbitrary native code or spawn processes.
# These never qualify for the legacy trusted-without-grant bypass: an
# explicit digest-bound grant is required.
HIGH_RISK_CAPABILITIES = frozenset(
    {
        "process.spawn",
        "package.install-scripts",
    }
)

# Capabilities that a plain ``plugin trust`` grants. High-risk capabilities
# (process spawn / install scripts) require a separate, deliberate
# ``plugin grant`` step and are intentionally excluded here so the
# HIGH_RISK_CAPABILITIES gate in :func:`execution_authorized` stays live.
LOW_RISK_CAPABILITIES = EXECUTION_CAPABILITIES - HIGH_RISK_CAPABILITIES


@dataclass(frozen=True, slots=True)
class PluginGrant:
    plugin_id: str
    digest: str
    capabilities: frozenset[str]
    granted_at: str
    source: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "digest": self.digest,
            "capabilities": sorted(self.capabilities),
            "granted_at": self.granted_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginGrant:
        return cls(
            plugin_id=str(data["plugin_id"]),
            digest=str(data["digest"]),
            capabilities=frozenset(str(item) for item in data.get("capabilities", [])),
            granted_at=str(data.get("granted_at") or ""),
            source=str(data.get("source") or "user"),
        )


def grants_root(home: Path | None = None) -> Path:
    return (home or user_deepseek_dir()) / "plugin-host" / "grants"


def _grant_path(plugin_id: str, digest: str, *, home: Path | None = None) -> Path:
    validate_plugin_id(plugin_id)
    safe_digest = digest.replace("/", "_").replace(":", "_")
    if not safe_digest or ".." in safe_digest or "\\" in safe_digest:
        raise ValueError(f"unsafe grant digest: {digest!r}")
    return grants_root(home) / plugin_id / f"{safe_digest}.json"


def read_grant(
    plugin_id: str,
    digest: str,
    *,
    home: Path | None = None,
) -> PluginGrant | None:
    if not is_safe_plugin_id(plugin_id) or not digest:
        return None
    path = _grant_path(plugin_id, digest, home=home)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return PluginGrant.from_dict(data)
    except (KeyError, TypeError, ValueError):
        return None


def write_grant(grant: PluginGrant, *, home: Path | None = None) -> Path:
    path = _grant_path(grant.plugin_id, grant.digest, home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, grant.to_dict())
    return path


def revoke_grant(
    plugin_id: str,
    digest: str | None = None,
    *,
    home: Path | None = None,
) -> int:
    """Revoke one digest grant, or every grant for the plugin when digest is None."""
    if not is_safe_plugin_id(plugin_id):
        return 0
    root = grants_root(home) / plugin_id
    if not root.is_dir():
        return 0
    removed = 0
    if digest is not None:
        path = _grant_path(plugin_id, digest, home=home)
        if path.is_file():
            path.unlink()
            removed = 1
        return removed
    for path in root.glob("*.json"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def grant_execution(
    plugin_id: str,
    digest: str,
    *,
    capabilities: frozenset[str] | None = None,
    home: Path | None = None,
) -> PluginGrant:
    caps = capabilities or EXECUTION_CAPABILITIES
    grant = PluginGrant(
        plugin_id=validate_plugin_id(plugin_id),
        digest=digest,
        capabilities=frozenset(caps),
        granted_at=datetime.now(timezone.utc).isoformat(),
    )
    write_grant(grant, home=home)
    return grant


def grant_trust(
    plugin_id: str,
    digest: str,
    *,
    home: Path | None = None,
) -> PluginGrant:
    """Grant only the low-risk capabilities implied by ``plugin trust``.

    High-risk capabilities (process spawn / install scripts) require a
    deliberate :func:`grant_execution` — usually via ``plugin grant`` — so
    trusting a plugin never silently authorizes arbitrary code execution.
    """
    return grant_execution(
        plugin_id,
        digest,
        capabilities=LOW_RISK_CAPABILITIES,
        home=home,
    )


def has_execution_grant(
    plugin_id: str,
    digest: str,
    capability: str,
    *,
    home: Path | None = None,
) -> bool:
    grant = read_grant(plugin_id, digest, home=home)
    if grant is None:
        return False
    return capability in grant.capabilities


def _any_grants(plugin_id: str, *, home: Path | None = None) -> bool:
    if not is_safe_plugin_id(plugin_id):
        return False
    root = grants_root(home) / plugin_id
    return root.is_dir() and any(root.glob("*.json"))


def migrate_legacy_fingerprint_grants(
    plugin_id: str,
    digest: str,
    *,
    home: Path | None = None,
) -> bool:
    """Replace fingerprint-only grants with a store ``sha256:`` grant.

    Pre-hardening trusts wrote ``fp:…`` grants. Runtime now binds
    ``sha256:…`` digests, so those installs would otherwise be denied until
    the user re-runs ``plugin trust``. When *every* on-disk grant for the
    plugin is a legacy fingerprint file, rewrite to *digest* and return True.
    """
    if not digest.startswith("sha256:") or not is_safe_plugin_id(plugin_id):
        return False
    root = grants_root(home) / plugin_id
    if not root.is_dir():
        return False
    files = [path for path in root.glob("*.json") if path.is_file()]
    if not files:
        return False
    # Grant filenames use digest with ``:``/``/`` → ``_`` (see ``_grant_path``).
    if not all(path.stem.startswith("fp_") for path in files):
        return False
    revoke_grant(plugin_id, home=home)
    grant_trust(plugin_id, digest, home=home)
    return True


def execution_authorized(
    *,
    trusted: bool,
    plugin_id: str,
    digest: str,
    capability: str,
    home: Path | None = None,
) -> bool:
    """Return whether *plugin_id*@*digest* may exercise *capability*.

    Rules:
    1. Must be marked trusted and have a non-empty digest.
    2. Matching digest-bound grant wins.
    3. Otherwise deny (including trusted-but-no-grant). There is no
       legacy "trusted with zero grant files" bypass — that path allowed a
       repository-committed project lockfile to activate hooks/MCP without
       any write under ``~/.deepseek``.
    """
    if not trusted or not digest or not is_safe_plugin_id(plugin_id):
        return False
    return has_execution_grant(plugin_id, digest, capability, home=home)

def legacy_trust_implies_grant(
    *,
    trusted: bool,
    plugin_id: str,
    digest: str,
    home: Path | None = None,
) -> bool:
    """Compatibility wrapper; prefer :func:`execution_authorized`."""
    return execution_authorized(
        trusted=trusted,
        plugin_id=plugin_id,
        digest=digest,
        capability="hooks.execute",
        home=home,
    )
