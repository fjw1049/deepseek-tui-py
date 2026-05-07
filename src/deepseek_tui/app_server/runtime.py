"""Application runtime — single orchestration entry for the app-server.

Mirrors ``deepseek_core::Runtime`` (crates/core/src/runtime.rs) — not
line-by-line, but in role: the app-server's handlers never construct an
:class:`Engine` directly. They go through this class so config, thread
storage, and the Stage 3 tool runtime are shared across every request.

Scope for Stage 4.1:

- In-memory thread store keyed by ``thread_id``
- Lazy :class:`ToolRuntime` construction (one per AppRuntime lifetime)
- Thin handlers for the 7 HTTP endpoints: healthz / thread / app /
  prompt / tool / jobs / mcp_startup
- MCP startup is best-effort (Stage 4.3 wires real MCP)

Stage 4.2 adds a :class:`HookDispatcher` that fans lifecycle events
(Response*, ToolLifecycle, ApprovalLifecycle, JobLifecycle) to any
sinks configured via ``config.hooks`` (stdout / JSONL file / webhooks).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.config.models import Config
from deepseek_tui.hooks.dispatcher import HookDispatcher
from deepseek_tui.hooks.events import (
    JobLifecycleEvent,
    ResponseDeltaEvent,
    ResponseEndEvent,
    ResponseStartEvent,
    ToolLifecycleEvent,
)
from deepseek_tui.hooks.sinks import JsonlHookSink, StdoutHookSink, WebhookHookSink
from deepseek_tui.protocol.events import (
    ResponseDeltaEvent as ResponseDeltaFrame,
)
from deepseek_tui.protocol.events import (
    ResponseEndEvent as ResponseEndFrame,
)
from deepseek_tui.protocol.events import (
    ResponseStartEvent as ResponseStartFrame,
)
from deepseek_tui.protocol.messages import Message

if TYPE_CHECKING:
    from deepseek_tui.tools.runtime import ToolRuntime


@dataclass(slots=True)
class ThreadRecord:
    thread_id: str
    name: str | None = None
    messages: list[Message] = field(default_factory=list)
    status: str = "active"
    model: str | None = None


class ThreadStore:
    """In-memory thread store.

    Stage 4.1 scope: volatile. Stage 4.2+ may swap for a JSON-backed one.
    """

    def __init__(self) -> None:
        self._threads: dict[str, ThreadRecord] = {}

    def create(self, *, name: str | None = None, model: str | None = None) -> ThreadRecord:
        tid = f"thread_{uuid.uuid4().hex[:12]}"
        rec = ThreadRecord(thread_id=tid, name=name, model=model)
        self._threads[tid] = rec
        return rec

    def get(self, thread_id: str) -> ThreadRecord | None:
        return self._threads.get(thread_id)

    def list_all(self) -> list[ThreadRecord]:
        return sorted(self._threads.values(), key=lambda t: t.thread_id, reverse=True)

    def append_message(self, thread_id: str, message: Message) -> ThreadRecord:
        rec = self._threads.get(thread_id)
        if rec is None:
            raise KeyError(f"Unknown thread: {thread_id}")
        rec.messages.append(message)
        return rec

    def archive(self, thread_id: str) -> ThreadRecord:
        rec = self._threads.get(thread_id)
        if rec is None:
            raise KeyError(f"Unknown thread: {thread_id}")
        rec.status = "archived"
        return rec

    def count(self) -> int:
        return len(self._threads)


class AppRuntime:
    """App-level orchestration shared across HTTP / stdio handlers.

    One instance lives for the whole server process. Handlers are pure
    delegators — business logic lives here so the same routing table can
    back HTTP + stdio JSON-RPC without duplication.
    """

    def __init__(
        self,
        config: Config | None = None,
        tool_runtime: ToolRuntime | None = None,
        working_directory: Path | None = None,
        hooks: HookDispatcher | None = None,
    ) -> None:
        self.config = config or Config()
        self.working_directory = (working_directory or Path.cwd()).resolve()
        self._tool_runtime: ToolRuntime | None = tool_runtime
        self.threads = ThreadStore()
        self.hooks = hooks if hooks is not None else _build_hook_dispatcher(self.config)

    @classmethod
    async def create(
        cls,
        *,
        config: Config | None = None,
        working_directory: Path | None = None,
        mode: str = "agent",
    ) -> AppRuntime:
        """Build an AppRuntime with a freshly-wired :class:`ToolRuntime`."""
        from deepseek_tui.tools.runtime import create_tool_runtime

        cfg = config or Config()
        wd = (working_directory or Path.cwd()).resolve()
        tool_runtime = await create_tool_runtime(
            config=cfg, working_directory=wd, mode=mode
        )
        return cls(config=cfg, tool_runtime=tool_runtime, working_directory=wd)

    async def shutdown(self) -> None:
        if self._tool_runtime is not None:
            await self._tool_runtime.shutdown()
        # Webhook sinks own httpx clients; close them if present.
        for sink in self.hooks.sinks:
            close = getattr(sink, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    pass

    # --- handlers ----------------------------------------------------------

    async def healthz(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "protocol": "v2",
            "service": "deepseek-app-server",
        }

    async def handle_thread(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Dispatch ThreadRequest variants.

        Accepts the Stage 1.4 tagged-union JSON shape. The ``op`` field
        (or fallback ``method``) selects the variant.
        """
        op = payload.get("op") or payload.get("method") or "start"
        if op == "start":
            rec = self.threads.create(
                name=_pick_str(payload, "name"),
                model=_pick_str(payload, "model"),
            )
            return _thread_response(
                rec,
                status="started",
                cwd=str(self.working_directory),
                model_provider=self.config.provider,
                approval_policy=self.config.approval_policy,
                sandbox=self.config.sandbox_mode,
            )
        if op == "list":
            threads = self.threads.list_all()
            return {
                "thread_id": "",
                "status": "ok",
                "threads": [_thread_to_dict(t) for t in threads],
                "thread": None,
                "model": None,
                "model_provider": None,
                "cwd": str(self.working_directory),
                "approval_policy": None,
                "sandbox": None,
                "events": [],
                "data": {},
            }
        if op == "read":
            tid = _require_str(payload, "thread_id")
            read_rec = self.threads.get(tid)
            if read_rec is None:
                return _thread_error(tid, f"unknown thread: {tid}")
            return _thread_response(read_rec, status="ok")
        if op == "archive":
            tid = _require_str(payload, "thread_id")
            try:
                archived = self.threads.archive(tid)
            except KeyError as exc:
                return _thread_error(tid, str(exc))
            return _thread_response(archived, status="archived")
        if op == "message":
            tid = _require_str(payload, "thread_id")
            text = _require_str(payload, "input")
            msg_rec = self.threads.get(tid)
            if msg_rec is None:
                return _thread_error(tid, f"unknown thread: {tid}")
            msg_rec.messages.append(Message.user(text))
            return _thread_response(msg_rec, status="ok")
        return _thread_error("", f"unknown op: {op}")

    async def handle_prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Prompt handler — records prompt, emits 3 event frames.

        Mirrors Rust ``Runtime::handle_prompt`` (core/src/lib.rs:925-999):
        ResponseStart → ResponseDelta("model-selected") → ResponseEnd.
        Full LLM streaming lands via /prompt/stream.
        """
        text = _pick_str(payload, "input") or _pick_str(payload, "prompt")
        if text is None:
            return {
                "output": "missing 'input' or 'prompt'",
                "model": "unknown",
                "events": [],
            }
        thread_id = _pick_str(payload, "thread_id")
        if thread_id is not None:
            rec = self.threads.get(thread_id)
            if rec is None:
                return {
                    "output": f"unknown thread: {thread_id}",
                    "model": "unknown",
                    "events": [],
                }
        else:
            rec = self.threads.create(model=_pick_str(payload, "model"))
        rec.messages.append(Message.user(text))

        model = rec.model or self.config.default_text_model
        response_id = f"resp-{uuid.uuid4().hex[:12]}"
        await self._emit_prompt_hooks(response_id)
        events = _build_prompt_event_frames(response_id)
        output_payload = {
            "provider": self.config.provider,
            "model": model,
            "prompt": text,
            "response_id": response_id,
            "thread_id": rec.thread_id,
        }
        return {
            "output": json.dumps(output_payload),
            "model": model,
            "events": events,
        }

    async def stream_prompt(
        self, payload: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Async-iterator variant of handle_prompt — yields each EventFrame.

        Consumed by the /prompt/stream SSE route. Yields typed event dicts
        in the same order as ``handle_prompt`` would pack into the events
        list, so clients can stream or batch identically.
        """
        text = _pick_str(payload, "input") or _pick_str(payload, "prompt")
        if text is None:
            yield {"event": "error", "message": "missing 'input' or 'prompt'"}
            return
        thread_id = _pick_str(payload, "thread_id")
        if thread_id is not None:
            rec = self.threads.get(thread_id)
            if rec is None:
                yield {"event": "error", "message": f"unknown thread: {thread_id}"}
                return
        else:
            rec = self.threads.create(model=_pick_str(payload, "model"))
        rec.messages.append(Message.user(text))

        response_id = f"resp-{uuid.uuid4().hex[:12]}"
        await self._emit_prompt_hooks(response_id)
        for frame in _build_prompt_event_frames(response_id):
            yield frame

    async def _emit_prompt_hooks(self, response_id: str) -> None:
        """Fan-out the 3 response-lifecycle hook events (Rust parity).

        Kept separate from event-frame construction so HTTP responses and
        SSE streams share the same hook emission path.
        """
        await self.hooks.emit(ResponseStartEvent(response_id=response_id))
        await self.hooks.emit(
            ResponseDeltaEvent(response_id=response_id, delta="model-selected")
        )
        await self.hooks.emit(ResponseEndEvent(response_id=response_id))

    async def handle_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a single tool call through the registry.

        Payload shape follows Rust ``ToolCallRequest``::

            {"call": {"name": "...", "arguments": {...}}, "cwd": "..."}
        """
        call = payload.get("call")
        if not isinstance(call, dict):
            return {"ok": False, "error": "missing 'call' object"}
        tool_name = call.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            return {"ok": False, "error": "call.name required"}
        arguments = call.get("arguments") or call.get("input") or {}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "call.arguments must be an object"}

        if self._tool_runtime is None:
            return {"ok": False, "error": "tool runtime not initialized"}
        response_id = f"tool-{uuid.uuid4().hex[:12]}"
        await self.hooks.emit(
            ToolLifecycleEvent(
                response_id=response_id,
                tool_name=tool_name,
                phase="precheck",
                payload={"arguments": arguments},
            )
        )
        try:
            tool = self._tool_runtime.registry.get(tool_name)
        except Exception as exc:  # noqa: BLE001 — registry raises ToolError
            await self.hooks.emit(
                ToolLifecycleEvent(
                    response_id=response_id,
                    tool_name=tool_name,
                    phase="error",
                    payload={"error": str(exc)},
                )
            )
            return {"ok": False, "error": str(exc)}
        try:
            result = await tool.execute(arguments, self._tool_runtime.context)
        except Exception as exc:  # noqa: BLE001 — surface to caller
            await self.hooks.emit(
                ToolLifecycleEvent(
                    response_id=response_id,
                    tool_name=tool_name,
                    phase="error",
                    payload={"error": f"{type(exc).__name__}: {exc}"},
                )
            )
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        await self.hooks.emit(
            ToolLifecycleEvent(
                response_id=response_id,
                tool_name=tool_name,
                phase="complete",
                payload={"success": result.success},
            )
        )
        return {
            "ok": result.success,
            "content": result.content,
            "metadata": result.metadata,
        }

    async def handle_app(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Dispatch AppRequest variants (capabilities / config.* / models)."""
        op = payload.get("op") or payload.get("method") or "capabilities"
        if op == "capabilities":
            return {
                "ok": True,
                "capabilities": {
                    "threads": True,
                    "tools": True,
                    "subagents": self.config.features.subagents,
                    "tasks": self.config.features.tasks,
                    "mcp": self.config.features.mcp,
                },
                "data": {},
            }
        if op == "models":
            return {
                "ok": True,
                "models": [self.config.default_text_model],
                "data": {},
            }
        if op == "config.list":
            return {
                "ok": True,
                "config": self.config.model_dump(mode="json"),
                "data": {},
            }
        if op == "config.get":
            key = _require_str(payload, "key")
            value = _dotted_get(self.config.model_dump(mode="json"), key)
            return {"ok": value is not None, "key": key, "value": value, "data": {}}
        if op == "config.set":
            return {
                "ok": False,
                "error": "config.set not supported (read-only runtime)",
            }
        if op == "threads.loaded":
            return {
                "ok": True,
                "count": self.threads.count(),
                "data": {},
            }
        return {"ok": False, "error": f"unknown op: {op}"}

    async def jobs(self) -> dict[str, Any]:
        """Snapshot of background jobs (tasks + subagents)."""
        task_count = 0
        subagent_count = 0
        if self._tool_runtime is not None:
            if self._tool_runtime.task_manager is not None:
                counts = await self._tool_runtime.task_manager.counts()
                task_count = counts.queued + counts.running
            if self._tool_runtime.subagent_manager is not None:
                subagent_count = self._tool_runtime.subagent_manager.running_count()
        await self.hooks.emit(
            JobLifecycleEvent(
                job_id="app-snapshot",
                phase="snapshot",
                detail=f"tasks={task_count} subagents={subagent_count}",
            )
        )
        return {
            "ok": True,
            "jobs": {
                "tasks_active": task_count,
                "subagents_running": subagent_count,
            },
            "data": {},
        }

    async def mcp_startup(self) -> dict[str, Any]:
        """MCP startup summary. Stage 4.3 will plug in the real manager."""
        return {
            "ok": True,
            "summary": {"servers": [], "note": "stage-4.3-pending"},
        }


# --- helpers ---------------------------------------------------------------


def _pick_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _require_str(data: dict[str, Any], key: str) -> str:
    value = _pick_str(data, key)
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _thread_to_dict(rec: ThreadRecord) -> dict[str, Any]:
    return {
        "id": rec.thread_id,
        "name": rec.name,
        "status": rec.status,
        "model": rec.model,
        "message_count": len(rec.messages),
    }


def _thread_response(
    rec: ThreadRecord,
    *,
    status: str,
    cwd: str | None = None,
    model_provider: str | None = None,
    approval_policy: str | None = None,
    sandbox: str | None = None,
) -> dict[str, Any]:
    return {
        "thread_id": rec.thread_id,
        "status": status,
        "thread": _thread_to_dict(rec),
        "threads": [],
        "model": rec.model,
        "model_provider": model_provider,
        "cwd": cwd,
        "approval_policy": approval_policy,
        "sandbox": sandbox,
        "events": [],
        "data": {},
    }


def _thread_error(thread_id: str, message: str) -> dict[str, Any]:
    return {
        "thread_id": thread_id or "error",
        "status": f"error:{message}",
        "thread": None,
        "threads": [],
        "model": None,
        "model_provider": None,
        "cwd": None,
        "approval_policy": None,
        "sandbox": None,
        "events": [],
        "data": {},
    }


def _dotted_get(data: Any, key: str) -> Any:
    current: Any = data
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _build_prompt_event_frames(response_id: str) -> list[dict[str, Any]]:
    """Build the 3-frame response envelope Rust emits for every prompt.

    Mirrors Rust ``Runtime::handle_prompt`` (lib.rs:938-953).
    """
    return [
        ResponseStartFrame(response_id=response_id).model_dump(),
        ResponseDeltaFrame(
            response_id=response_id, delta="model-selected"
        ).model_dump(),
        ResponseEndFrame(response_id=response_id).model_dump(),
    ]


def _build_hook_dispatcher(config: Config) -> HookDispatcher:
    """Construct a HookDispatcher from ``config.hooks``.

    Mirrors Rust ``build_state`` (app-server/src/lib.rs:264-287) — stdout
    + jsonl by default, webhooks per URL. Stage 4.2 scope.
    """
    dispatcher = HookDispatcher()
    hooks_cfg = config.hooks
    if hooks_cfg.stdout:
        dispatcher.add_sink(StdoutHookSink())
    if hooks_cfg.jsonl_path is not None:
        dispatcher.add_sink(JsonlHookSink(hooks_cfg.jsonl_path.expanduser()))
    for url in hooks_cfg.webhook_urls:
        if url.strip():
            dispatcher.add_sink(WebhookHookSink(url))
    return dispatcher
