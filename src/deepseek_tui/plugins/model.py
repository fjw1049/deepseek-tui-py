"""Canonical, serializable plugin inspection model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any


class CompatibilityStatus(str, Enum):
    NATIVE = "native"
    ADAPTED = "adapted"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ActivationMode(str, Enum):
    CATALOG = "catalog"
    SESSION = "session"
    ON_DEMAND = "on_demand"


class RiskClass(str, Enum):
    CONTENT = "content"
    PROCESS = "process"
    PRIVILEGED = "privileged"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    source_path: str = ""
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "source_path": self.source_path,
            "remediation": self.remediation,
        }


@dataclass(frozen=True, slots=True)
class ResourceRef:
    path: str
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        path = PurePosixPath(self.path)
        if (
            not self.path
            or "\\" in self.path
            or path.is_absolute()
            or ".." in path.parts
            or "\x00" in self.path
        ):
            raise ValueError(f"unsafe plugin resource path: {self.path!r}")

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "media_type": self.media_type}


@dataclass(frozen=True, slots=True)
class PermissionClaim:
    capability: str
    reason: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "reason": self.reason,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class ContributionSpec:
    kind: str
    name: str
    summary: str
    status: CompatibilityStatus
    activation: ActivationMode
    risk: RiskClass
    resources: tuple[ResourceRef, ...] = ()
    permissions: tuple[PermissionClaim, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "summary": self.summary,
            "status": self.status.value,
            "activation": self.activation.value,
            "risk": self.risk.value,
            "resources": [item.to_dict() for item in self.resources],
            "permissions": [item.to_dict() for item in self.permissions],
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    kind: str
    locator: str
    digest: str
    relative_root: str = "."

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "locator": self.locator,
            "digest": self.digest,
            "relative_root": self.relative_root,
        }


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    status: CompatibilityStatus
    adapter_id: str
    adapter_version: int
    diagnostics: tuple[Diagnostic, ...] = ()
    can_install: bool = True
    can_activate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "can_install": self.can_install,
            "can_activate": self.can_activate,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class DerivedPlugin:
    schema_version: int
    plugin_id: str
    version: str
    description: str
    source: SourceProvenance
    contributions: tuple[ContributionSpec, ...]
    permission_claims: tuple[PermissionClaim, ...]
    compatibility: CompatibilityReport
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plugin_id": self.plugin_id,
            "version": self.version,
            "description": self.description,
            "source": self.source.to_dict(),
            "contributions": [item.to_dict() for item in self.contributions],
            "permission_claims": [item.to_dict() for item in self.permission_claims],
            "compatibility": self.compatibility.to_dict(),
            "metadata": self.metadata,
        }
