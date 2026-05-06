"""App server implementation with HTTP and stdio JSON-RPC support."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from deepseek_tui.app_server.routes import (
    app_handler,
    healthz,
    jobs_handler,
    mcp_startup_handler,
    prompt_handler,
    thread_handler,
    tool_handler,
)


async def run_http(options: Any) -> None:
    """Run HTTP server (stub - requires aiohttp or similar)."""
    raise NotImplementedError("HTTP server requires aiohttp dependency")


async def run_stdio(config_path: Path | None = None) -> None:
    """Run stdio JSON-RPC server."""
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(
        writer_transport, writer_protocol, reader, asyncio.get_event_loop()
    )

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            try:
                request = json.loads(line_str)
            except json.JSONDecodeError as e:
                response = _jsonrpc_error(None, -32700, f"Parse error: {e}")
                writer.write((json.dumps(response) + "\n").encode("utf-8"))
                await writer.drain()
                continue

            if not isinstance(request, dict):
                response = _jsonrpc_error(None, -32600, "Invalid Request")
                writer.write((json.dumps(response) + "\n").encode("utf-8"))
                await writer.drain()
                continue

            method = request.get("method")
            params = request.get("params", {})
            req_id = request.get("id")

            result, should_exit = await _dispatch_stdio(method, params)

            response = _jsonrpc_result(req_id, result)
            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            await writer.drain()

            if should_exit:
                break

        except Exception as e:
            response = _jsonrpc_error(None, -32603, f"Internal error: {e}")
            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            await writer.drain()


async def _dispatch_stdio(method: str | None, params: Any) -> tuple[Any, bool]:
    """Dispatch stdio JSON-RPC method."""
    if method == "exit":
        return {"status": "ok"}, True
    elif method == "healthz":
        return await healthz(), False
    elif method == "thread":
        return await thread_handler(params), False
    elif method == "app":
        return await app_handler(params), False
    elif method == "prompt":
        return await prompt_handler(params), False
    elif method == "tool":
        return await tool_handler(params), False
    elif method == "jobs":
        return await jobs_handler(), False
    elif method == "mcp/startup":
        return await mcp_startup_handler(params), False
    else:
        raise ValueError(f"Unknown method: {method}")


def _jsonrpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    """Build JSON-RPC result response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    """Build JSON-RPC error response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
