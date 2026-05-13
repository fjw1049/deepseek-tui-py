"""MCP server — expose DeepSeek tools to other agents over stdio JSON-RPC.

Mirrors a trimmed-down version of ``crates/tui/src/mcp_server.rs``. Implements
``initialize``, ``tools/list``, ``tools/call``, ``resources/list``, and
``resources/read``. Adds the ``deepseek`` meta-tool which wraps a one-shot
``Engine`` turn (the ``deepseek-reply`` continuation variant is still
deferred — see HANDOVER pre-realapi-batch-2 for the gap).
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
                return _make_response(req_id, self._resources_list())
            if method == "resources/read":
                return _make_response(req_id, self._resources_read(params))
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
        # ``deepseek`` meta-tool: lets an outside MCP agent ask DeepSeek
        # itself for an answer without going through the registry. Mirrors
        # Rust ``mcp_server.rs:176-224`` ``deepseek`` schema.
        tools.append({
            "name": "deepseek",
            "description": (
                "Ask DeepSeek for a one-shot text answer. Returns the model's "
                "completion as plain text. No tool calls, no streaming."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The user prompt to send to DeepSeek.",
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional model override.",
                    },
                },
                "required": ["prompt"],
            },
        })
        return {"tools": tools, "nextCursor": None}

    async def _tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        if name == "deepseek":
            return await self._deepseek_meta_call(arguments)
        if name not in self.exposed_tools:
            raise ValueError(f"Tool not exposed: {name}")
        registry = self._runtime.registry
        if not registry.contains(name):
            raise ValueError(f"Tool not registered: {name}")
        result = await registry.execute(name, arguments, self._runtime.context)
        return {
            "content": [{"type": "text", "text": result.content}],
            "isError": not result.success,
        }

    async def _deepseek_meta_call(
        self, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """One-shot LLM round-trip behind the ``deepseek`` MCP meta-tool.

        Builds a fresh ``DeepSeekClient`` from the loaded ``Config`` (which
        the runtime context carries), sends a single non-streaming chat
        completion (semantically — internally we still consume SSE deltas
        and concatenate), and returns the assistant text. Tools are not
        offered, so this never recurses back into MCP.
        """
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("'prompt' must be a non-empty string")
        model_override = arguments.get("model")
        try:
            from deepseek_tui.client.deepseek import DeepSeekClient
            from deepseek_tui.config.models import Config
            from deepseek_tui.protocol.messages import Message
            from deepseek_tui.protocol.requests import MessageRequest
            from deepseek_tui.protocol.responses import StreamTextDelta

            cfg = Config()
            client = DeepSeekClient.from_config(cfg)
            request = MessageRequest(
                model=(
                    model_override
                    if isinstance(model_override, str) and model_override
                    else cfg.default_text_model
                ),
                messages=[Message.user(prompt)],
                stream=True,
            )
            chunks: list[str] = []
            async for event in client.stream_chat_completion(request):
                if isinstance(event, StreamTextDelta):
                    chunks.append(event.text)
            await client.close()
            return {
                "content": [{"type": "text", "text": "".join(chunks)}],
                "isError": False,
            }
        except Exception as exc:  # noqa: BLE001 — surface to MCP caller
            return {
                "content": [{"type": "text", "text": f"deepseek meta-tool failed: {exc}"}],
                "isError": True,
            }

    def _resources_list(self) -> dict[str, Any]:
        """``resources/list`` — workspace root + each saved session JSON."""
        from deepseek_tui.config.paths import user_sessions_dir

        resources: list[dict[str, Any]] = [
            {
                "uri": f"file://{self.workspace}",
                "name": "workspace",
                "description": "Workspace root",
                "mimeType": "inode/directory",
            }
        ]
        sessions_dir = user_sessions_dir()
        if sessions_dir.exists():
            for path in sorted(sessions_dir.glob("*.json")):
                resources.append(
                    {
                        "uri": f"session://{path.stem}",
                        "name": path.stem,
                        "description": f"Saved session ({path.name})",
                        "mimeType": "application/json",
                    }
                )
        return {"resources": resources, "nextCursor": None}

    def _resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """``resources/read`` — return raw bytes for a known URI."""
        from deepseek_tui.config.paths import user_sessions_dir

        uri = params.get("uri", "")
        if not isinstance(uri, str) or not uri:
            raise ValueError("'uri' is required")
        if uri.startswith("session://"):
            stem = uri[len("session://"):]
            sessions_dir = user_sessions_dir()
            path = sessions_dir / f"{stem}.json"
            if not path.exists():
                raise ValueError(f"Session not found: {stem}")
            text = path.read_text(encoding="utf-8")
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": text,
                    }
                ]
            }
        if uri.startswith("file://"):
            file_path = Path(uri[len("file://"):])
            if not file_path.exists() or file_path.is_dir():
                raise ValueError(f"File not readable: {file_path}")
            text = file_path.read_text(encoding="utf-8")
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": text,
                    }
                ]
            }
        raise ValueError(f"Unsupported URI scheme: {uri}")


async def run_mcp_server(workspace: Path) -> None:
    """Entry point for ``deepseek-tui mcp-server`` CLI."""
    server = McpStdioServer(workspace=workspace)
    await server.run()
