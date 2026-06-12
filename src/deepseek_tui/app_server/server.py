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
    http_mode: bool = False
    auth_token: str | None = None
    insecure_no_auth: bool = False
    cors_origins: list[str] | None = None


def build_fastapi_app(
    runtime: AppRuntime,
    *,
    http_mode: bool = False,
    auth_token: str | None = None,
    insecure_no_auth: bool = False,
    cors_origins: list[str] | None = None,
) -> Any:
    """Construct a FastAPI app with routes attached.

    When ``http_mode`` is True, mount Rust-parity Workbench routes (bare JSON +
    long-lived SSE) and keep legacy envelope routes under ``/legacy`` only.
    """
    from fastapi import FastAPI

    app = FastAPI(
        title="deepseek-runtime-api" if http_mode else "deepseek-app-server",
        version="0.1.0",
    )
    app.state.runtime = runtime

    from deepseek_tui.app_server.runtime_threads import RuntimeThreadManagerConfig
    from deepseek_tui.app_server.thread_manager import RuntimeThreadManager
    from deepseek_tui.config.paths import user_tasks_dir, user_threads_dir

    _mgr_cfg = RuntimeThreadManagerConfig(
        data_dir=user_threads_dir(),
        task_data_dir=user_tasks_dir(),
    )

    approval_bridge = None
    if http_mode:
        from deepseek_tui.app_server.runtime_api import attach_runtime_api
        from deepseek_tui.app_server.runtime_api.auth import (
            env_runtime_token,
            resolve_runtime_auth,
        )

        resolved = resolve_runtime_auth(
            auth_token,
            env_runtime_token(),
            insecure_no_auth=insecure_no_auth,
        )
        approval_bridge, elevation_bridge = attach_runtime_api(
            app,
            config=runtime.config,
            auth_token=resolved.token,
            cors_origins=cors_origins,
        )
        app.state.runtime_auth = resolved
    else:
        elevation_bridge = None

    app.state.thread_manager = RuntimeThreadManager(
        config=runtime.config,
        workspace=Path.cwd(),
        manager_cfg=_mgr_cfg,
        approval_bridge=approval_bridge,
        elevation_bridge=elevation_bridge,
        shared_tool_runtime=runtime.tool_runtime,
    )

    # Per-request access log: method/path/status/duration. ``uvicorn.access``
    # is silenced in :mod:`logging_setup` so this is the single source of
    # truth for HTTP traffic during real-API testing.
    @app.middleware("http")
    async def _access_log(request: Any, call_next: Any) -> Any:
        started = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        # Defense-in-depth: starlette ``request.url.path`` is already path-only,
        # but explicitly strip any '?' that might leak through if the upstream
        # contract changes. SSE clients pass ?token=... so this matters.
        raw_path = request.url.path
        safe_path = raw_path.split("?", 1)[0]
        logger.info(
            "http_access method=%s path=%s status=%d duration_ms=%d",
            request.method,
            safe_path,
            response.status_code,
            elapsed_ms,
        )
        return response

    if http_mode:
        app.include_router(build_router(), prefix="/legacy")
    else:
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
        "app_server_start host=%s port=%d http_mode=%s",
        options.host,
        options.port,
        options.http_mode,
    )
    runtime = await AppRuntime.create(
        config=config, working_directory=options.working_directory
    )
    app = build_fastapi_app(
        runtime,
        http_mode=options.http_mode,
        auth_token=options.auth_token,
        insecure_no_auth=options.insecure_no_auth,
        cors_origins=options.cors_origins,
    )
    if options.http_mode:
        from deepseek_tui.app_server.runtime_api.auth import (
            runtime_token_file,
            write_runtime_token_file,
        )

        auth = getattr(app.state, "runtime_auth", None)
        if auth is not None and auth.generated and auth.token:
            token_path = write_runtime_token_file(auth.token)
            logger.info(
                "runtime_api_auth generated bearer token written to %s", token_path
            )
            print(
                "Runtime API auth: generated bearer token (written to "
                f"{token_path}, mode 0600)."
            )
            print("  Read the file or set DEEPSEEK_RUNTIME_TOKEN for a stable token.")
        elif auth is not None and auth.token:
            # Only seed the cache when missing — never overwrite an existing
            # non-empty file. Two concurrent spawn attempts (e.g., CLI + GUI)
            # would otherwise race and clobber each other's tokens.
            token_path = runtime_token_file()
            try:
                if not token_path.exists() or not token_path.read_text(
                    encoding="utf-8"
                ).strip():
                    token_path = write_runtime_token_file(auth.token)
                    logger.info(
                        "runtime_api_auth bearer token written to %s", token_path
                    )
            except OSError as exc:  # noqa: BLE001
                logger.warning("runtime_api_auth token file write failed: %s", exc)
            print(
                "Runtime API auth: bearer token required for /v1/* routes "
                f"(cached at {token_path})."
            )
        else:
            logger.warning("runtime_api_auth disabled (--insecure)")
            print("Runtime API auth: disabled by explicit insecure mode.")
            # Surface that any cached token file is being ignored so users
            # don't assume the file's presence implies the runtime is secured.
            cached_path = runtime_token_file()
            if cached_path.exists():
                print(
                    f"  Note: ignoring cached token at {cached_path} while "
                    "--insecure is in effect."
                )
        print(f"Runtime API listening on http://{options.host}:{options.port}")
    server_cfg = uvicorn.Config(
        app,
        host=options.host,
        port=options.port,
        log_level="info",
        # Our ``_access_log`` middleware is the single source of truth and
        # strips query strings (SSE ?token=). Disable uvicorn's default access
        # log so bearer tokens never land in stderr.
        access_log=not options.http_mode,
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
