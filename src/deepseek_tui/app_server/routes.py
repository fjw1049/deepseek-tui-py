"""FastAPI router for the 7 app-server endpoints.

Mirrors ``crates/app-server/src/lib.rs`` (783 lines). Each handler is a
thin delegator to :class:`AppRuntime` so HTTP + stdio JSON-RPC share the
same code path.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from deepseek_tui.app_server.runtime import AppRuntime
from deepseek_tui.app_server.sse import iter_sse


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

    return router


def _get_runtime(request: Request) -> AppRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, AppRuntime):
        raise RuntimeError("AppRuntime not attached to app.state.runtime")
    return runtime


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
