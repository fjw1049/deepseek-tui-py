"""Low-level tool execution helpers for the engine turn loop.

Mirrors `crates/tui/src/core/engine/tool_execution.rs:1-298`.

Keeps the mechanics of audit logging, execution locking, and MCP dispatch
out of ``engine.py``; the engine still owns planning, approval, and how
tool results are written back into session state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from deepseek_tui.tools.base import ToolError, ToolResult
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# --- Audit logging (Rust tool_execution.rs:11-26) ------------------------


def emit_tool_audit(event: dict[str, Any]) -> None:
    """Append a JSONL audit line to ``$DEEPSEEK_TOOL_AUDIT_LOG`` if set.

    Silent no-op when the env var is unset or the write fails.
    """
    path_str = os.environ.get("DEEPSEEK_TOOL_AUDIT_LOG")
    if not path_str:
        return
    try:
        line = json.dumps(event, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return
    path = Path(path_str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# --- Execution with lock (Rust tool_execution.rs:152-196) ----------------


async def execute_tool_with_lock(
    write_lock: asyncio.Lock,
    supports_parallel: bool,
    tool_name: str,
    tool_input: dict[str, Any],
    registry: ToolRegistry,
    context: ToolContext,
    mcp_manager: Any | None = None,
) -> ToolResult:
    """Execute a single tool, respecting the write lock.

    Read-only tools that support parallel run **without** the lock so they
    can overlap.  Write tools acquire the lock exclusively.

    Mirrors Rust ``execute_tool_with_lock`` (tool_execution.rs:152-196).
    """
    is_mcp = _is_mcp_tool(tool_name)

    if is_mcp:
        if mcp_manager is None:
            raise ToolError(f"tool '{tool_name}' is not registered")
        return await _execute_mcp_tool(mcp_manager, tool_name, tool_input)

    if supports_parallel:
        return await registry.execute(tool_name, tool_input, context)

    async with write_lock:
        return await registry.execute(tool_name, tool_input, context)


# --- MCP tool execution (Rust tool_execution.rs:29-41) --------------------


def _is_mcp_tool(name: str) -> bool:
    return name.startswith("mcp__") or name.startswith("mcp_")


async def _execute_mcp_tool(
    mcp_manager: Any,
    name: str,
    input_data: dict[str, Any],
) -> ToolResult:
    """Execute a tool via the MCP manager/pool."""
    try:
        result = await mcp_manager.call_tool(name, input_data)
        content = (
            json.dumps(result, ensure_ascii=False, default=str)
            if not isinstance(result, str)
            else result
        )
        return ToolResult(success=True, content=content)
    except Exception as exc:
        raise ToolError(f"MCP tool failed: {exc}") from exc
