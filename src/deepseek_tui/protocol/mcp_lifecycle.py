"""MCP server startup lifecycle types.

Mirrors Rust types in ``crates/protocol/src/lib.rs:316-341``.

Wire shape::

    McpStartupStatus is a discriminated union; Rust uses
    ``#[serde(rename_all = "snake_case")]``. The "Failed" variant has an
    ``error`` payload, others are plain string tags. Rust's serde
    encodes plain unit-like variants as a bare string and the data
    variant as an externally tagged object:

        "starting" | "ready" | "cancelled" | {"failed": {"error": "..."}}

    To match Rust byte-for-byte we expose ``McpStartupStatus`` as a
    ``Annotated[Union, Field(discriminator="status")]`` for the data
    case, plus a string-coerce path for the bare-tag forms. In practice
    the only emitter is :class:`McpStartupUpdateEvent` which embeds the
    status — so callers use that wrapper instead of touching the
    enum directly.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel, model_serializer, model_validator

__all__ = [
    "McpStartupCompleteEvent",
    "McpStartupFailure",
    "McpStartupStatus",
    "McpStartupUpdateEvent",
]


class _StatusStarting(BaseModel):
    type: Literal["starting"] = "starting"


class _StatusReady(BaseModel):
    type: Literal["ready"] = "ready"


class _StatusCancelled(BaseModel):
    type: Literal["cancelled"] = "cancelled"


class _StatusFailed(BaseModel):
    type: Literal["failed"] = "failed"
    error: str


_StatusVariants = (
    Annotated[
        _StatusStarting | _StatusReady | _StatusCancelled | _StatusFailed,
        Field(discriminator="type"),
    ]
)


class McpStartupStatus(RootModel[_StatusVariants]):
    """MCP server startup status.

    Rust serde shape (``#[serde(rename_all = "snake_case")]`` on a Rust
    enum with one data variant)::

        "starting" | "ready" | "cancelled" | {"failed": {"error": "..."}}

    We expose factory constants for the unit variants and a constructor
    for the failed case::

        McpStartupStatus.starting()
        McpStartupStatus.ready()
        McpStartupStatus.cancelled()
        McpStartupStatus.failed("backend offline")
    """

    @classmethod
    def starting(cls) -> McpStartupStatus:
        return cls(_StatusStarting())

    @classmethod
    def ready(cls) -> McpStartupStatus:
        return cls(_StatusReady())

    @classmethod
    def cancelled(cls) -> McpStartupStatus:
        return cls(_StatusCancelled())

    @classmethod
    def failed(cls, error: str) -> McpStartupStatus:
        return cls(_StatusFailed(error=error))

    @model_serializer(mode="plain")
    def _serialise(self) -> Any:
        inner = self.root
        if isinstance(inner, _StatusFailed):
            return {"failed": {"error": inner.error}}
        return inner.type

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"type": data}
        if isinstance(data, dict) and "failed" in data and "type" not in data:
            payload = data["failed"]
            if isinstance(payload, dict):
                return {"type": "failed", **payload}
        return data


class McpStartupUpdateEvent(BaseModel):
    """Mirror of Rust ``McpStartupUpdateEvent`` (lib.rs:325-328)."""

    server_name: str
    status: McpStartupStatus


class McpStartupFailure(BaseModel):
    """Mirror of Rust ``McpStartupFailure`` (lib.rs:331-334)."""

    server_name: str
    error: str


class McpStartupCompleteEvent(BaseModel):
    """Mirror of Rust ``McpStartupCompleteEvent`` (lib.rs:337-341)."""

    ready: list[str] = Field(default_factory=list)
    failed: list[McpStartupFailure] = Field(default_factory=list)
    cancelled: list[str] = Field(default_factory=list)
