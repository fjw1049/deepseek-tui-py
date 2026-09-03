"""Canonical, serializable plugin inspection model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any


def _json_dict(obj: Any) -> dict[str, Any]:
    """``dataclasses.asdict`` with Enum → value and tuples → list."""
    def encode(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value

    return {key: encode(val) for key, val in asdict(obj).items()}


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
        return _json_dict(self)


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
        return _json_dict(self)


@dataclass(frozen=True, slots=True)
class PermissionClaim:
    capability: str
    reason: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _json_dict(self)


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
        return _json_dict(self)


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    kind: str
    locator: str
    digest: str
    relative_root: str = "."

    def to_dict(self) -> dict[str, str]:
        return _json_dict(self)


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    status: CompatibilityStatus
    adapter_id: str
    adapter_version: int
    diagnostics: tuple[Diagnostic, ...] = ()
    can_install: bool = True
    can_activate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _json_dict(self)


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
        return _json_dict(self)
