#!/usr/bin/env python3
"""Minimal stdio MCP server for end-to-end tests.

Implements initialize, tools/list, and tools/call (echo tool) over
JSON-RPC 2.0 line protocol (MCP 2024-11-05).
"""

from __future__ import annotations

import json
import sys


def _respond(msg_id: object, result: dict) -> None:
    print(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}), flush=True)


def _error(msg_id: object, message: str) -> None:
    print(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": message},
            }
        ),
        flush=True,
    )


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        req = json.loads(line)
        msg_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        if method == "initialize":
            _respond(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "minimal-mcp-fixture", "version": "0.1.0"},
                },
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _respond(
                msg_id,
                {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo the message argument",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "message": {"type": "string"},
                                },
                                "required": ["message"],
                            },
                        }
                    ]
                },
            )
        elif method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            if name != "echo":
                _error(msg_id, f"unknown tool: {name}")
                continue
            text = arguments.get("message", "")
            _respond(
                msg_id,
                {
                    "content": [{"type": "text", "text": f"echo:{text}"}],
                    "isError": False,
                },
            )
        elif msg_id is not None:
            _error(msg_id, f"method not found: {method}")


if __name__ == "__main__":
    main()
