"""MCP startup lifecycle types used by the manager and legacy server hooks."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_serializer, model_validator

__all__ = [
    "McpStartupCompleteEvent",
    "McpStartupCompleteEventFrame",
    "McpStartupFailure",
    "McpStartupStatus",
    "McpStartupUpdateEvent",
    "McpStartupUpdateEventFrame",
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


_StatusVariants = Annotated[
    _StatusStarting | _StatusReady | _StatusCancelled | _StatusFailed,
    Field(discriminator="type"),
]


class McpStartupStatus(RootModel[_StatusVariants]):
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
    server_name: str
    status: McpStartupStatus


class McpStartupFailure(BaseModel):
    server_name: str
    error: str


class McpStartupCompleteEvent(BaseModel):
    ready: list[str] = Field(default_factory=list)
    failed: list[McpStartupFailure] = Field(default_factory=list)
    cancelled: list[str] = Field(default_factory=list)


class McpStartupUpdateEventFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["mcp_startup_update"] = "mcp_startup_update"
    update: McpStartupUpdateEvent


class McpStartupCompleteEventFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["mcp_startup_complete"] = "mcp_startup_complete"
    summary: McpStartupCompleteEvent
