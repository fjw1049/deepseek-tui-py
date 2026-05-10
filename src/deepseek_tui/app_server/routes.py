"""FastAPI router for app-server endpoints.

Mirrors ``crates/app-server/src/lib.rs`` (783 lines). Each handler is a
thin delegator to :class:`AppRuntime` so HTTP + stdio JSON-RPC share the
same code path.

Extended with runtime-thread lifecycle routes (mirrors Rust runtime_api.rs):
- POST /threads          — create thread
- GET  /threads          — list threads
- GET  /threads/{id}     — get thread detail
- PATCH /threads/{id}    — update thread (archive/unarchive)
- POST /threads/{id}/fork — fork thread
- POST /threads/{id}/turns — start turn
- POST /threads/{id}/turns/{turn_id}/interrupt — interrupt turn
- POST /threads/{id}/turns/{turn_id}/steer — steer turn
- POST /threads/{id}/compact — compact thread
- GET  /threads/{id}/events — events since seq
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

    # --- Runtime Thread lifecycle routes ------------------------------------

    @router.post("/threads")
    async def create_thread(request: Request) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        payload = await _body(request)
        from deepseek_tui.app_server.runtime_threads import CreateThreadRequest

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
        from deepseek_tui.app_server.runtime_threads import UpdateThreadRequest

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
        try:
            forked = await manager.fork_thread(thread_id)
        except FileNotFoundError:
            return {"ok": False, "error": f"thread not found: {thread_id}"}
        return {"ok": True, "thread": forked.model_dump(mode="json")}

    @router.post("/threads/{thread_id}/turns")
    async def start_turn(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _get_thread_manager(request)
        if manager is None:
            return {"ok": False, "error": "runtime thread manager not configured"}
        payload = await _body(request)
        from deepseek_tui.app_server.runtime_threads import StartTurnRequest

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
        from deepseek_tui.app_server.runtime_threads import SteerTurnRequest

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
        from deepseek_tui.app_server.runtime_threads import CompactThreadRequest

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
