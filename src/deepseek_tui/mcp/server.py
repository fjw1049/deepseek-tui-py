"""MCP server — expose DeepSeek tools to other agents over stdio JSON-RPC.

Mirrors a trimmed-down version of ``crates/tui/src/mcp_server.rs``. Implements
``initialize``, ``tools/list``, ``tools/call``, and ``resources/list``. The
``deepseek`` / ``deepseek-reply`` meta-tools that wrap a full Engine turn are
deferred (need full Engine integration); only direct registry tools are
exposed for now.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from deepseek_tui.tools.runtime import create_tool_runtime

logger = logging.getLogger(__name__)

# Default tools exposed to outside agents (mirrors Rust default_expose_tools).
DEFAULT_EXPOSED_TOOLS: tuple[str, ...] = (
    "read_file",
    "list_dir",
    "grep_files",
    "file_search",
    "git_status",
    "git_diff",
    "git_log",
)


def _make_response(req_id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})


def _make_error(req_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    )


class McpStdioServer:
    """Stdio JSON-RPC MCP server.

    Reads newline-delimited JSON requests from stdin, writes responses to
    stdout. Each request is processed sequentially.
    """

    def __init__(self, workspace: Path, exposed_tools: tuple[str, ...] | None = None) -> None:
        self.workspace = workspace.resolve()
        self.exposed_tools = exposed_tools or DEFAULT_EXPOSED_TOOLS
        self._runtime: Any = None

    async def _ensure_runtime(self) -> None:
        if self._runtime is None:
            self._runtime = await create_tool_runtime(working_directory=self.workspace)

    async def run(self) -> None:
        loop = asyncio.get_event_loop()
        await self._ensure_runtime()
        try:
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                except json.JSONDecodeError:
                    continue
                response = await self._dispatch(req)
                if response is not None:
                    print(response, flush=True)
        finally:
            if self._runtime is not None:
                await self._runtime.shutdown()

    async def _dispatch(self, req: dict[str, Any]) -> str | None:
        method = req.get("method", "")
        params = req.get("params", {}) or {}
        req_id = req.get("id")

        try:
            if method == "initialize":
                return _make_response(req_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "deepseek-tui", "version": "0.1.0"},
                })
            if method == "tools/list":
                return _make_response(req_id, self._tools_list())
            if method == "tools/call":
                return _make_response(req_id, await self._tools_call(params))
            if method == "resources/list":
                return _make_response(req_id, {
                    "resources": [{
                        "uri": f"file://{self.workspace}",
                        "name": "workspace",
                        "description": "Workspace root",
                        "mimeType": "inode/directory",
                    }],
                    "nextCursor": None,
                })
            if method == "ping":
                return _make_response(req_id, {})
            if req_id is None:
                # Notification — no response required
                return None
            return _make_error(req_id, -32601, f"Method not found: {method}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("MCP request failed")
            return _make_error(req_id, -32603, f"Internal error: {exc}")

    def _tools_list(self) -> dict[str, Any]:
        registry = self._runtime.registry
        tools: list[dict[str, Any]] = []
        for name in self.exposed_tools:
            if not registry.contains(name):
                continue
            tool = registry.get(name)
            tools.append({
                "name": name,
                "description": tool.description(),
                "inputSchema": tool.input_schema(),
            })
        return {"tools": tools, "nextCursor": None}

    async def _tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        if name not in self.exposed_tools:
            raise ValueError(f"Tool not exposed: {name}")
        arguments = params.get("arguments", {}) or {}
        registry = self._runtime.registry
        if not registry.contains(name):
            raise ValueError(f"Tool not registered: {name}")
        result = await registry.execute(name, arguments, self._runtime.context)
        return {
            "content": [{"type": "text", "text": result.content}],
            "isError": not result.success,
        }


async def run_mcp_server(workspace: Path) -> None:
    """Entry point for ``deepseek-tui mcp-server`` CLI."""
    server = McpStdioServer(workspace=workspace)
    await server.run()
