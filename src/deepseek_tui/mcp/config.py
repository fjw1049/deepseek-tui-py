from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class McpServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    enabled: bool = True
    required: bool = False
    connect_timeout: float = 10.0
    execute_timeout: float = 60.0
    read_timeout: float = 120.0
    tool_filter: ToolFilter | None = None


@dataclass(slots=True)
class ToolFilter:
    """Filter which tools are exposed from an MCP server."""

    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)

    def accepts(self, tool_name: str) -> bool:
        if self.deny and tool_name in self.deny:
            return False
        if self.allow:
            return tool_name in self.allow
        return True
