"""Server application — FastAPI factory, routes, SSE, broadcast.
"""

from __future__ import annotations



# Build FastAPI app fragment for Workbench runtime API.
from typing import Any

from deepseek_tui.server.approval import ApprovalBridge
from deepseek_tui.server.approval import ElevationBridge
from deepseek_tui.server.auth import RuntimeAuthMiddleware
from deepseek_tui.server.routes import build_runtime_api_router


def attach_runtime_api(
    app: Any,
    *,
    auth_token: str | None = None,
    cors_origins: list[str] | None = None,
) -> tuple[ApprovalBridge, ElevationBridge]:
    """Mount parity routes and auth middleware on an existing FastAPI app.

    This is the single construction path used by ``server.build_fastapi_app``
    (production) and by contract tests. Tests must drive the runtime through
    this same call so middleware / state wiring stays in lockstep with prod.
    """
    bridge = ApprovalBridge()
    elevation = ElevationBridge()
    app.state.approval_bridge = bridge
    app.state.elevation_bridge = elevation
    app.state.runtime_auth_token = auth_token

    @app.get("/")
    async def runtime_api_root() -> dict[str, str]:
        return {
            "service": "deepseek-runtime-api",
            "hint": (
                "HTTP API only — open DeepSeek Workbench (Electron), "
                "not this URL in a browser."
            ),
            "health": "/health",
            "threads": "/v1/threads",
        }

    app.include_router(build_runtime_api_router())
    app.add_middleware(RuntimeAuthMiddleware, auth_token=auth_token)
    if cors_origins:
        attach_cors(app, cors_origins)
    return bridge, elevation


def attach_cors(app: Any, origins: list[str]) -> None:
    from starlette.middleware.cors import CORSMiddleware

    # Bearer tokens travel in the Authorization header, not cookies, so
    # ``allow_credentials`` stays False. Combining credentials=True with a
    # user-configurable origin list would widen the cross-site attack surface
    # for no benefit on a localhost-only runtime.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# FastAPI router for app-server endpoints.
#
# Mirrors ``crates/app-server/src/lib.rs`` (783 lines). Each handler is a
# thin delegator to :class:`AppRuntime` so HTTP + stdio JSON-RPC share the
# same code path.
#
# Extended with runtime-thread lifecycle routes (mirrors Rust runtime_api.rs):
# - POST /threads          — create thread
# - GET  /threads          — list threads
# - GET  /threads/{id}     — get thread detail
# - PATCH /threads/{id}    — update thread (archive/unarchive)
# - POST /threads/{id}/fork — fork thread
# - POST /threads/{id}/turns — start turn
# - POST /threads/{id}/turns/{turn_id}/interrupt — interrupt turn
# - POST /threads/{id}/turns/{turn_id}/steer — steer turn
# - POST /threads/{id}/compact — compact thread
# - GET  /threads/{id}/events — events since seq
#
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from deepseek_tui.server.runtime import AppRuntime


def build_router() -> APIRouter:
    """Build the FastAPI router. Caller must set ``app.state.runtime``."""
    router = APIRouter()

    @router.get("/healthz")
    async def healthz(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        return await runtime.healthz()

    @router.post("/thread")
    async def thread(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        payload = await _body(request)
        return await runtime.handle_thread(payload)

    @router.post("/app")
    async def app(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        payload = await _body(request)
        return await runtime.handle_app(payload)

    @router.post("/prompt")
    async def prompt(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        payload = await _body(request)
        return await runtime.handle_prompt(payload)

    @router.post("/prompt/stream")
    async def prompt_stream(request: Request) -> StreamingResponse:
        runtime = _get_runtime(request)
        payload = await _body(request)
        generator = iter_sse(runtime.stream_prompt(payload))
        return StreamingResponse(generator, media_type="text/event-stream")

    @router.post("/tool")
    async def tool(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        payload = await _body(request)
        return await runtime.handle_tool(payload)

    @router.get("/jobs")
    async def jobs(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        return await runtime.jobs()

    @router.post("/mcp/startup")
    async def mcp_startup(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        return await runtime.mcp_startup()

    # --- Runtime Thread lifecycle routes ------------------------------------

    @router.post("/threads")
    async def create_thread(request: Request) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        payload = await _body(request)
        from deepseek_tui.server.threads import CreateThreadRequest

        req = CreateThreadRequest.model_validate(payload)
        thread = await manager.create_thread(req)
        return {"ok": True, "thread": thread.model_dump(mode="json")}

    @router.get("/threads")
    async def list_threads(request: Request) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        include_archived = request.query_params.get("include_archived", "false") == "true"
        limit_str = request.query_params.get("limit")
        limit = int(limit_str) if limit_str else None
        threads = await manager.list_threads(include_archived=include_archived, limit=limit)
        return {
            "ok": True,
            "threads": [t.model_dump(mode="json") for t in threads],
        }

    @router.get("/threads/{thread_id}")
    async def get_thread_detail(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        try:
            detail = await manager.get_thread_detail(thread_id)
        except FileNotFoundError:
            return {"ok": False, "error": f"thread not found: {thread_id}"}
        return {"ok": True, "detail": detail.model_dump(mode="json")}

    @router.patch("/threads/{thread_id}")
    async def update_thread(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        payload = await _body(request)
        from deepseek_tui.server.threads import UpdateThreadRequest

        req = UpdateThreadRequest.model_validate(payload)
        try:
            thread = await manager.update_thread(thread_id, req)
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "thread": thread.model_dump(mode="json")}

    @router.post("/threads/{thread_id}/fork")
    async def fork_thread(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        payload = await _body(request)
        through_item_id = payload.get("through_item_id") if isinstance(payload, dict) else None
        try:
            forked = await manager.fork_thread(thread_id, through_item_id=through_item_id)
        except FileNotFoundError:
            return {"ok": False, "error": f"thread not found: {thread_id}"}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "thread": forked.model_dump(mode="json")}

    @router.post("/threads/{thread_id}/turns")
    async def start_turn(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        payload = await _body(request)
        from deepseek_tui.server.threads import StartTurnRequest

        req = StartTurnRequest.model_validate(payload)
        try:
            turn = await manager.start_turn(thread_id, req)
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "turn": turn.model_dump(mode="json")}

    @router.post("/threads/{thread_id}/turns/{turn_id}/interrupt")
    async def interrupt_turn(
        request: Request, thread_id: str, turn_id: str
    ) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        try:
            turn = await manager.interrupt_turn(thread_id, turn_id)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "turn": turn.model_dump(mode="json")}

    @router.post("/threads/{thread_id}/turns/{turn_id}/steer")
    async def steer_turn(
        request: Request, thread_id: str, turn_id: str
    ) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        payload = await _body(request)
        from deepseek_tui.server.threads import SteerTurnRequest

        req = SteerTurnRequest.model_validate(payload)
        try:
            turn = await manager.steer_turn(thread_id, turn_id, req)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "turn": turn.model_dump(mode="json")}

    @router.post("/threads/{thread_id}/compact")
    async def compact_thread(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        payload = await _body(request)
        from deepseek_tui.server.threads import CompactThreadRequest

        req = CompactThreadRequest.model_validate(payload)
        try:
            turn = await manager.compact_thread(thread_id, req)
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "turn": turn.model_dump(mode="json")}

    @router.get("/threads/{thread_id}/events")
    async def get_events(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        since_str = request.query_params.get("since_seq")
        since_seq = int(since_str) if since_str else None
        events = manager.events_since(thread_id, since_seq)
        return {
            "ok": True,
            "events": [e.model_dump(mode="json") for e in events],
        }

    @router.get("/threads/{thread_id}/events/stream")
    async def stream_events(request: Request, thread_id: str) -> StreamingResponse:
        """Long-poll friendly SSE wrapper over ``events_since``.

        Rust ``GET /v1/threads/{id}/events`` returns SSE; the JSON variant
        above is kept for clients that already integrated with the Python
        snapshot semantics. New clients should target this stream endpoint.
        """
        manager = _get_thread_manager(request)
        if manager is None:
            async def _empty() -> Any:
                yield (
                    'event: error\ndata: '
                    '{"error":"runtime thread manager not configured"}\n\n'
                )
            return StreamingResponse(_empty(), media_type="text/event-stream")

        since_str = request.query_params.get("since_seq")
        since_seq = int(since_str) if since_str else None

        import asyncio as _asyncio
        import json as _json

        async def _generator() -> Any:
            current = since_seq
            # 30 ticks at 100ms = ~3s window per HTTP keepalive. Enough for
            # most short turns; clients that want continuous streams should
            # reconnect with the last seen seq.
            for _ in range(30):
                events = manager.events_since(thread_id, current)
                for ev in events:
                    payload = ev.model_dump(mode="json")
                    current = payload.get("seq", current)
                    yield (
                        f"event: {payload.get('event', 'event')}\n"
                        f"data: {_json.dumps(payload)}\n\n"
                    )
                await _asyncio.sleep(0.1)
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(_generator(), media_type="text/event-stream")

    @router.post("/threads/{thread_id}/resume")
    async def resume_thread(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        try:
            detail = await manager.resume_thread(thread_id)
        except FileNotFoundError:
            return {"ok": False, "error": f"thread not found: {thread_id}"}
        return {"ok": True, "detail": detail.model_dump(mode="json")}

    @router.get("/threads/summary")
    async def threads_summary(request: Request) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        return {"ok": True, **(await manager.threads_summary())}

    # --- App-Server long-tail (skills / tasks / mcp / workspace) ---------
    #
    # Mirrors a subset of Rust ``runtime_api.rs`` routes that overlap with
    # CLI thread/task/skill commands. Each handler is a thin delegator to
    # :class:`AppRuntime` and returns ``{"ok": False, "error": ...}`` when
    # the underlying manager isn't wired (no exceptions across HTTP).

    @router.get("/skills")
    async def list_skills(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        return await runtime.list_skills()

    @router.get("/tasks")
    async def list_tasks(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        limit_str = request.query_params.get("limit")
        limit = int(limit_str) if limit_str else None
        return await runtime.list_tasks(limit=limit)

    @router.get("/tasks/{task_id}")
    async def get_task(request: Request, task_id: str) -> dict[str, Any]:
        runtime = _get_runtime(request)
        return await runtime.get_task(task_id)

    @router.post("/tasks/{task_id}/cancel")
    async def cancel_task(request: Request, task_id: str) -> dict[str, Any]:
        runtime = _get_runtime(request)
        return await runtime.cancel_task(task_id)

    @router.get("/apps/mcp/servers")
    async def list_mcp_servers_route(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        return await runtime.list_mcp_servers()

    @router.get("/apps/mcp/tools")
    async def list_mcp_tools_route(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        return await runtime.list_mcp_tools()

    @router.get("/workspace/status")
    async def workspace_status_route(request: Request) -> dict[str, Any]:
        runtime = _get_runtime(request)
        return await runtime.workspace_status()

    return router


def _get_runtime(request: Request) -> AppRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, AppRuntime):
        raise RuntimeError("AppRuntime not attached to app.state.runtime")
    return runtime


def _get_thread_manager(request: Request) -> Any:
    """Get the RuntimeThreadManager from app state, or None."""
    return getattr(request.app.state, "thread_manager", None)


async def _body(request: Request) -> dict[str, Any]:
    if request.headers.get("content-length", "0") == "0":
        return {}
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# --- legacy stdio dispatchers (used by server.py::run_stdio) ---------------
#
# The in-proc stdio JSON-RPC path re-uses the same AppRuntime by calling
# these shims directly. Each accepts (runtime, payload) so server.py can
# pass the process-wide runtime through.


async def stdio_healthz(runtime: AppRuntime, _payload: dict[str, Any]) -> dict[str, Any]:
    return await runtime.healthz()


async def stdio_thread(runtime: AppRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    return await runtime.handle_thread(payload)


async def stdio_app(runtime: AppRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    return await runtime.handle_app(payload)


async def stdio_prompt(runtime: AppRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    return await runtime.handle_prompt(payload)


async def stdio_tool(runtime: AppRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    return await runtime.handle_tool(payload)


async def stdio_jobs(runtime: AppRuntime, _payload: dict[str, Any]) -> dict[str, Any]:
    return await runtime.jobs()


async def stdio_mcp_startup(
    runtime: AppRuntime, _payload: dict[str, Any]
) -> dict[str, Any]:
    return await runtime.mcp_startup()


# App server entry points — HTTP (FastAPI/uvicorn) and stdio JSON-RPC.
#
# Mirrors ``crates/app-server/src/lib.rs`` (783 lines). The HTTP path uses
# FastAPI + uvicorn. The stdio path speaks newline-delimited JSON-RPC 2.0.
# Both call into the same :class:`AppRuntime` so state stays consistent.
#
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepseek_tui.server.runtime import AppRuntime
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

    from deepseek_tui.server.threads import RuntimeThreadManagerConfig
    from deepseek_tui.server.threads import RuntimeThreadManager
    from deepseek_tui.config.paths import user_tasks_dir, user_threads_dir

    _mgr_cfg = RuntimeThreadManagerConfig(
        data_dir=user_threads_dir(),
        task_data_dir=user_tasks_dir(),
    )

    approval_bridge = None
    if http_mode:
        from deepseek_tui.server.auth import (
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
    from deepseek_tui.utils import setup_logging

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
        from deepseek_tui.server.auth import (
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


# SSE (Server-Sent Events) support for streaming responses.
#
# Mirrors the SSE framing used by Rust app-server. Each envelope contains
# an ``event:`` field (the tagged-union discriminator) and a ``data:``
# field (the payload JSON), terminated by a blank line.
#
import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any


def format_sse(payload: dict[str, Any]) -> str:
    """Render one SSE envelope from a plain dict.

    If ``payload['event']`` is present it becomes the ``event:`` field;
    everything else is JSON-encoded under ``data:``.
    """
    event_name = payload.get("event")
    if isinstance(event_name, str) and event_name:
        return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
    return f"data: {json.dumps(payload)}\n\n"


async def iter_sse(source: AsyncIterable[dict[str, Any]]) -> AsyncIterator[str]:
    """Lift an async iterable of event dicts into SSE-framed strings."""
    async for envelope in source:
        yield format_sse(envelope)


# Async broadcast channel — one sender, multiple receivers.
#
# Mirrors Rust ``tokio::sync::broadcast`` semantics with bounded capacity.
# Each subscriber gets its own asyncio.Queue; when full, oldest items are
# dropped (lagging receiver behaviour).
#
import asyncio
import logging
from typing import Generic, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


# AsyncBroadcast moved to server/threads.py to avoid circular imports
