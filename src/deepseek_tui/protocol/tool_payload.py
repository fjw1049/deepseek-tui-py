"""Tool payload + output types.

Mirrors Rust ``ToolKind``, ``LocalShellParams``, ``ToolPayload``,
``ToolOutput`` (protocol/src/lib.rs:238-286).

Rust uses ``#[serde(tag = "type", rename_all = "snake_case")]`` for the
two enums, so the wire shape is::

    {"type": "function", "arguments": "..."}
    {"type": "custom", "input": "..."}
    {"type": "local_shell", "params": {...}}
    {"type": "mcp", "server": "...", "tool": "...",
     "raw_arguments": {...}, "raw_tool_call_id": "..."}   # last omitted if None

    {"type": "function", "body": {...}, "success": true}  # body omitted if None
    {"type": "mcp", "result": {...}}
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "LocalShellParams",
    "ToolKind",
    "ToolOutput",
    "ToolOutputFunction",
    "ToolOutputMcp",
    "ToolPayload",
    "ToolPayloadCustom",
    "ToolPayloadFunction",
    "ToolPayloadLocalShell",
    "ToolPayloadMcp",
]


class ToolKind(str, Enum):
    """Mirror of Rust ``ToolKind`` (lib.rs:240-243)."""

    FUNCTION = "function"
    MCP = "mcp"


class LocalShellParams(BaseModel):
    """Mirror of Rust ``LocalShellParams`` (lib.rs:246-252)."""

    model_config = ConfigDict(extra="forbid")

    command: str
    cwd: str | None = None
    timeout_ms: int | None = None


# --- ToolPayload variants -------------------------------------------------


class ToolPayloadFunction(BaseModel):
    type: Literal["function"] = "function"
    arguments: str


class ToolPayloadCustom(BaseModel):
    type: Literal["custom"] = "custom"
    input: str


class ToolPayloadLocalShell(BaseModel):
    type: Literal["local_shell"] = "local_shell"
    params: LocalShellParams


class ToolPayloadMcp(BaseModel):
    type: Literal["mcp"] = "mcp"
    server: str
    tool: str
    raw_arguments: Any
    raw_tool_call_id: str | None = None


ToolPayload = Annotated[
    ToolPayloadFunction | ToolPayloadCustom | ToolPayloadLocalShell | ToolPayloadMcp,
    Field(discriminator="type"),
]


# --- ToolOutput variants --------------------------------------------------


class ToolOutputFunction(BaseModel):
    type: Literal["function"] = "function"
    body: Any | None = None
    success: bool


class ToolOutputMcp(BaseModel):
    type: Literal["mcp"] = "mcp"
    result: Any


ToolOutput = Annotated[
    ToolOutputFunction | ToolOutputMcp,
    Field(discriminator="type"),
]
