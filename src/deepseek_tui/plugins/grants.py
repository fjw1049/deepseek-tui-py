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
        "runtime.tool-provider",
    }
)


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


def legacy_trust_implies_grant(
    *,
    trusted: bool,
    plugin_id: str,
    digest: str,
    home: Path | None = None,
) -> bool:
    """Bridge lockfile ``trusted`` until callers migrate fully to grants.

    If a digest-bound grant exists it wins. Otherwise a legacy trusted flag
    still authorizes execution for that digest so existing installs keep
    working; new trusts should write an explicit grant.
    """
    if has_execution_grant(plugin_id, digest, "hooks.execute", home=home):
        return True
    if has_execution_grant(plugin_id, digest, "mcp.connect", home=home):
        return True
    return bool(trusted and digest)
