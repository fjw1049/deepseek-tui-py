"""App server entry points — HTTP (FastAPI/uvicorn) and stdio JSON-RPC.

Mirrors ``crates/app-server/src/lib.rs`` (783 lines). The HTTP path uses
FastAPI + uvicorn. The stdio path speaks newline-delimited JSON-RPC 2.0.
Both call into the same :class:`AppRuntime` so state stays consistent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepseek_tui.app_server.routes import (
    build_router,
    stdio_app,
    stdio_healthz,
    stdio_jobs,
    stdio_mcp_startup,
    stdio_prompt,
    stdio_thread,
    stdio_tool,
)
from deepseek_tui.app_server.runtime import AppRuntime
from deepseek_tui.config.models import Config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppServerOptions:
    host: str = "127.0.0.1"
    port: int = 8787
    config_path: Path | None = None
    working_directory: Path | None = None


def build_fastapi_app(runtime: AppRuntime) -> Any:
    """Construct a FastAPI app with the 7 routes attached.

    Separate from :func:`run_http` so tests can exercise it in-process
    via ``httpx.ASGITransport`` without opening a socket.
    """
    from fastapi import FastAPI

    app = FastAPI(title="deepseek-app-server", version="0.1.0")
    app.state.runtime = runtime

    # Wire durable thread manager so /threads/* routes are reachable.
    # RuntimeThreadManagerConfig.data_dir defaults next to the config file.
    from deepseek_tui.app_server.runtime_threads import RuntimeThreadManagerConfig
    from deepseek_tui.app_server.thread_manager import RuntimeThreadManager
    from deepseek_tui.config.paths import user_tasks_dir, user_threads_dir

    _mgr_cfg = RuntimeThreadManagerConfig(
        data_dir=user_threads_dir(),
        task_data_dir=user_tasks_dir(),
    )
    app.state.thread_manager = RuntimeThreadManager(
        config=runtime.config,
        workspace=Path.cwd(),
        manager_cfg=_mgr_cfg,
    )

    # Per-request access log: method/path/status/duration. ``uvicorn.access``
    # is silenced in :mod:`logging_setup` so this is the single source of
    # truth for HTTP traffic during real-API testing.
    @app.middleware("http")
    async def _access_log(request: Any, call_next: Any) -> Any:
        started = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "http_access method=%s path=%s status=%d duration_ms=%d",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    # Mount the same router twice: at root for legacy callers and at ``/v1``
    # for Rust-parity callers. Rust's ``runtime_api`` exposes everything
    # under ``/v1/...`` (see runtime_api.rs:295-344). Keeping both prefixes
    # working avoids breaking existing Python integration tests while
    # giving cross-language clients the URL shape they expect.
    app.include_router(build_router())
    app.include_router(build_router(), prefix="/v1")
    return app


async def run_http(
    options: AppServerOptions, *, config: Config | None = None
) -> None:
    """Serve the 7 endpoints over HTTP via uvicorn."""
    import uvicorn

    # Wire rotating-file logging up before AppRuntime spins up so the
    # very first router import lands in the file too. Safe to call even
    # if the CLI already configured logging — duplicate handlers are
    # cleaned out by :func:`setup_logging` itself.
    from deepseek_tui.logging_setup import setup_logging

    setup_logging(config)

    logger.info(
        "app_server_start host=%s port=%d", options.host, options.port
    )
    runtime = await AppRuntime.create(
        config=config, working_directory=options.working_directory
    )
    app = build_fastapi_app(runtime)
    server_cfg = uvicorn.Config(
        app, host=options.host, port=options.port, log_level="info"
    )
    server = uvicorn.Server(server_cfg)
    try:
        await server.serve()
    finally:
        logger.info("app_server_stop")
        await runtime.shutdown()


async def run_stdio(
    config_path: Path | None = None, *, config: Config | None = None
) -> None:
    """Speak newline-delimited JSON-RPC 2.0 on stdin/stdout.

    Method → AppRuntime mapping mirrors the HTTP routes 1:1.
    """
    runtime = await AppRuntime.create(config=config)
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_event_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    writer_transport, writer_protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, loop)

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            try:
                request = json.loads(line_str)
            except json.JSONDecodeError as e:
                _send(writer, _rpc_error(None, -32700, f"Parse error: {e}"))
                await writer.drain()
                continue

            if not isinstance(request, dict):
                _send(writer, _rpc_error(None, -32600, "Invalid Request"))
                await writer.drain()
                continue

            method = request.get("method")
            params = request.get("params", {}) or {}
            req_id = request.get("id")

            try:
                result, should_exit = await _dispatch_stdio(runtime, method, params)
                _send(writer, _rpc_result(req_id, result))
                await writer.drain()
                if should_exit:
                    break
            except ValueError as exc:
                _send(writer, _rpc_error(req_id, -32602, str(exc)))
                await writer.drain()
            except Exception as exc:  # noqa: BLE001
                _send(
                    writer, _rpc_error(req_id, -32603, f"Internal error: {exc}")
                )
                await writer.drain()
    finally:
        await runtime.shutdown()


async def _dispatch_stdio(
    runtime: AppRuntime, method: str | None, params: Any
) -> tuple[Any, bool]:
    if method == "exit":
        return {"status": "ok"}, True
    handlers = {
        "healthz": stdio_healthz,
        "thread": stdio_thread,
        "app": stdio_app,
        "prompt": stdio_prompt,
        "tool": stdio_tool,
        "jobs": stdio_jobs,
        "mcp/startup": stdio_mcp_startup,
        "mcp_startup": stdio_mcp_startup,
    }
    handler = handlers.get(method or "")
    if handler is None:
        raise ValueError(f"Unknown method: {method!r}")
    payload: dict[str, Any] = params if isinstance(params, dict) else {}
    result = await handler(runtime, payload)
    return result, False


def _send(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))


def _rpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }
