from __future__ import annotations

import hashlib
import re


def qualify_tool_name(server_name: str, tool_name: str) -> str:
    """Encode an MCP tool name as mcp__<server>__<tool>."""
    sanitized_server = re.sub(r"[^a-z0-9_]", "_", server_name.lower())
    sanitized_tool = re.sub(r"[^a-z0-9_]", "_", tool_name.lower())
    qualified = f"mcp__{sanitized_server}__{sanitized_tool}"
    if len(qualified) > 64:
        hash_suffix = hashlib.sha256(qualified.encode()).hexdigest()[:12]
        qualified = qualified[:51] + "_" + hash_suffix
    return qualified


def parse_qualified_tool_name(qualified: str) -> tuple[str, str] | None:
    """Parse a qualified MCP tool name back into (server, tool)."""
    if not qualified.startswith("mcp__"):
        return None
    rest = qualified[5:]
    parts = rest.split("__", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]
