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
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.config.models import Config
from deepseek_tui.hooks.build import build_hook_dispatcher
from deepseek_tui.hooks.dispatcher import HookDispatcher
from deepseek_tui.hooks.events import (
    JobLifecycleEvent,
    ResponseDeltaEvent,
    ResponseEndEvent,
    ResponseStartEvent,
    ToolLifecycleEvent,
)
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
    from deepseek_tui.client.base import LLMClient
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
        llm_client: LLMClient | None = None,
    ) -> None:
        self.config = config or Config()
        self.working_directory = (working_directory or Path.cwd()).resolve()
        self._tool_runtime: ToolRuntime | None = tool_runtime
        self.threads = ThreadStore()
        self.hooks = hooks if hooks is not None else _build_hook_dispatcher(self.config)
        self._llm_client: LLMClient | None = llm_client

    @property
    def tool_runtime(self) -> ToolRuntime | None:
        return self._tool_runtime

    def schedule_mcp_preload(self) -> None:
        """Background MCP tool discovery — does not block HTTP serve."""
        if not getattr(self.config.features, "mcp", False):
            return
        tr = self._tool_runtime
        if tr is None:
            return
        mcp = getattr(tr, "mcp_manager", None)
        if mcp is None:
            return
        mcp.schedule_startup_preload()

    def mcp_preload_status(self) -> dict[str, Any]:
        """Current MCP warmup state for Workbench / readiness probes."""
        if not getattr(self.config.features, "mcp", False):
            return {
                "phase": "disabled",
                "warming": False,
                "ready": True,
                "enabled_servers": 0,
                "connected_servers": 0,
                "tools_count": 0,
                "from_disk_cache": False,
                "started_at_ms": None,
                "completed_at_ms": None,
                "error": None,
            }
        tr = self._tool_runtime
        if tr is None:
            return {"phase": "idle", "warming": False, "ready": False}
        mcp = getattr(tr, "mcp_manager", None)
        if mcp is None:
            return {"phase": "disabled", "warming": False, "ready": True}
        return mcp.preload_status()

    @classmethod
    async def create(
        cls,
        *,
        config: Config | None = None,
        working_directory: Path | None = None,
        mode: str = "agent",
        llm_client: LLMClient | None = None,
    ) -> AppRuntime:
        """Build an AppRuntime with a freshly-wired :class:`ToolRuntime`."""
        from deepseek_tui.tools.runtime import create_tool_runtime

        cfg = config or Config()
        wd = (working_directory or Path.cwd()).resolve()
        tool_runtime = await create_tool_runtime(
            config=cfg,
            working_directory=wd,
            mode=mode,
            start_mcp=False,
        )
        runtime = cls(
            config=cfg,
            tool_runtime=tool_runtime,
            working_directory=wd,
            llm_client=llm_client,
        )
        runtime.schedule_mcp_preload()
        return runtime

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

        Consumed by the /prompt/stream SSE route. Two modes:

        - **With** an LLMClient injected: spin up an :class:`Engine`
          over the current tool runtime, send the prompt, and stream
          every engine event through :func:`engine_event_to_sse`.
        - **Without** an LLMClient: yield the Rust-parity 3-frame
          placeholder (ResponseStart/Delta("model-selected")/ResponseEnd).

        The latter path preserves Stage 4.1.next behavior for tests and
        offline callers that have no upstream LLM configured.
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

        if self._llm_client is not None:
            async for frame in self._stream_engine_events(
                text, rec.model or self.config.default_text_model
            ):
                yield frame
            return

        for frame in _build_prompt_event_frames(response_id):
            yield frame

    async def _stream_engine_events(
        self, prompt_text: str, model: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Drive a one-shot Engine turn and yield SSE frames for each event."""
        import asyncio

        from deepseek_tui.app_server.engine_bridge import engine_event_to_sse
        from deepseek_tui.engine.engine import Engine
        from deepseek_tui.engine.events import TurnCancelledEvent, TurnCompleteEvent
        from deepseek_tui.engine.handle import EngineHandle

        assert self._llm_client is not None  # checked by caller

        from deepseek_tui.hooks.build import build_lifecycle_hook_executor

        handle = EngineHandle(hooks=self.hooks)
        hook_executor = build_lifecycle_hook_executor(self.config, self.working_directory)
        engine = Engine(
            handle=handle,
            client=self._llm_client,
            default_model=model,
            tool_runtime=self._tool_runtime,
            hook_executor=hook_executor,
        )

        # Run the engine loop in the background; it exits when the
        # single turn terminates via TurnComplete/TurnCancelled.
        engine_task = asyncio.create_task(engine.run())
        try:
            await handle.send_message(content=prompt_text, model=model)
            events_iter = handle.events()
            async for event in events_iter:
                yield engine_event_to_sse(event)
                if isinstance(event, (TurnCompleteEvent, TurnCancelledEvent)):
                    break
        finally:
            await handle.cancel()
            engine_task.cancel()
            try:
                await engine_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

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
        from deepseek_tui.mcp.execute import (
            execute_external_mcp_tool,
            is_external_mcp_tool,
            normalize_mcp_bridge_tool_name,
        )

        tool_name = normalize_mcp_bridge_tool_name(tool_name)
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
        registry = self._tool_runtime.registry
        mcp_manager = self._tool_runtime.mcp_manager

        if mcp_manager is not None and is_external_mcp_tool(
            tool_name, registry.contains(tool_name)
        ):
            try:
                result = await execute_external_mcp_tool(
                    mcp_manager, tool_name, arguments
                )
            except Exception as exc:  # noqa: BLE001
                await self.hooks.emit(
                    ToolLifecycleEvent(
                        response_id=response_id,
                        tool_name=tool_name,
                        phase="error",
                        payload={"error": str(exc)},
                    )
                )
                return {"ok": False, "error": str(exc)}
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

        try:
            tool = registry.get(tool_name)
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

    # --- App Server long-tail handlers -----------------------------------
    #
    # Mirrors a subset of Rust ``runtime_api.rs`` (runtime_api.rs:297-341)
    # that overlaps with existing CLI thread/task/skill commands. Each
    # handler is a thin delegator to a manager that already exists in the
    # Python tree (TaskManager / SkillRegistry / McpManager / SessionManager).
    # Handlers return ``{"ok": False, "error": ...}`` when the underlying
    # manager isn't wired so the routes never raise.

    async def list_skills(self) -> dict[str, Any]:
        """Mirror Rust ``list_skills`` (runtime_api.rs:657)."""
        from deepseek_tui.skills import discover_in_workspace

        skills_dir = Path(self.config.skills_dir).expanduser()  # noqa: ASYNC240 — pure path expansion, not I/O
        try:
            registry = discover_in_workspace(
                skills_dir=skills_dir,
                workspace=self.working_directory,
            )
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"skill discovery failed: {exc}"}
        return {
            "ok": True,
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "path": str(s.path),
                }
                for s in registry.skills
            ],
            "warnings": registry.warnings,
        }

    async def list_tasks(self, limit: int | None = None) -> dict[str, Any]:
        """Mirror Rust ``list_tasks`` (runtime_api.rs:954)."""
        if self._tool_runtime is None or self._tool_runtime.task_manager is None:
            return {"ok": False, "error": "task manager not configured"}
        manager = self._tool_runtime.task_manager
        summaries = await manager.list_tasks(limit=limit)
        return {
            "ok": True,
            "tasks": [_task_summary_to_dict(s) for s in summaries],
        }

    async def get_task(self, task_id: str) -> dict[str, Any]:
        """Mirror Rust ``get_task`` (runtime_api.rs:963)."""
        if self._tool_runtime is None or self._tool_runtime.task_manager is None:
            return {"ok": False, "error": "task manager not configured"}
        try:
            record = await self._tool_runtime.task_manager.get_task(task_id)
        except KeyError as exc:
            return {"ok": False, "error": f"task not found: {exc}"}
        return {"ok": True, "task": _task_record_to_dict(record)}

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Mirror Rust ``cancel_task`` (runtime_api.rs:?)."""
        if self._tool_runtime is None or self._tool_runtime.task_manager is None:
            return {"ok": False, "error": "task manager not configured"}
        try:
            record = await self._tool_runtime.task_manager.cancel_task(task_id)
        except KeyError as exc:
            return {"ok": False, "error": f"task not found: {exc}"}
        return {"ok": True, "task": _task_record_to_dict(record)}

    def _automation_manager(self) -> Any:
        if self._tool_runtime is None or self._tool_runtime.automation_manager is None:
            return None
        return self._tool_runtime.automation_manager

    async def list_automations(self) -> dict[str, Any]:
        manager = self._automation_manager()
        if manager is None:
            return {"ok": False, "error": "automation manager not configured"}
        records = manager.list_automations()
        return {
            "ok": True,
            "automations": [_automation_record_to_dict(r) for r in records],
        }

    async def create_automation(self, body: dict[str, Any]) -> dict[str, Any]:
        from deepseek_tui.tools.automation_manager import (
            AutomationStatus,
            CreateAutomationRequest,
        )

        manager = self._automation_manager()
        if manager is None:
            return {"ok": False, "error": "automation manager not configured"}
        try:
            name = _require_str(body, "name")
            prompt = _require_str(body, "prompt")
            rrule = _require_str(body, "rrule")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        cwds_raw = body.get("cwds")
        cwds = [str(p) for p in cwds_raw] if isinstance(cwds_raw, list) else []
        status_raw = body.get("status")
        status = None
        if isinstance(status_raw, str) and status_raw.strip():
            status = AutomationStatus(status_raw.strip().lower())
        req = CreateAutomationRequest(
            name=name,
            prompt=prompt,
            rrule=rrule,
            cwds=cwds,
            status=status,
            delivery=body.get("delivery") if isinstance(body.get("delivery"), dict) else None,
            digest=body.get("digest") if isinstance(body.get("digest"), dict) else None,
            next_run_at=(
                str(body["next_run_at"]).strip()
                if isinstance(body.get("next_run_at"), str) and str(body["next_run_at"]).strip()
                else None
            ),
        )
        try:
            record = manager.create_automation(req)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "automation": _automation_record_to_dict(record)}

    async def get_automation(self, automation_id: str) -> dict[str, Any]:
        manager = self._automation_manager()
        if manager is None:
            return {"ok": False, "error": "automation manager not configured"}
        try:
            record = manager.get_automation(automation_id)
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "automation": _automation_record_to_dict(record)}

    async def update_automation(
        self, automation_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        from deepseek_tui.tools.automation_manager import (
            AutomationStatus,
            UpdateAutomationRequest,
        )

        manager = self._automation_manager()
        if manager is None:
            return {"ok": False, "error": "automation manager not configured"}
        status = None
        status_raw = body.get("status")
        if isinstance(status_raw, str) and status_raw.strip():
            status = AutomationStatus(status_raw.strip().lower())
        req = UpdateAutomationRequest(
            name=_pick_str(body, "name"),
            prompt=_pick_str(body, "prompt"),
            rrule=_pick_str(body, "rrule"),
            cwds=[str(p) for p in body["cwds"]] if isinstance(body.get("cwds"), list) else None,
            status=status,
            delivery=body.get("delivery") if isinstance(body.get("delivery"), dict) else None,
            digest=body.get("digest") if isinstance(body.get("digest"), dict) else None,
        )
        try:
            record = manager.update_automation(automation_id, req)
        except (KeyError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "automation": _automation_record_to_dict(record)}

    async def delete_automation(self, automation_id: str) -> dict[str, Any]:
        manager = self._automation_manager()
        if manager is None:
            return {"ok": False, "error": "automation manager not configured"}
        try:
            record = manager.delete_automation(automation_id)
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "automation": _automation_record_to_dict(record)}

    async def run_automation(self, automation_id: str) -> dict[str, Any]:
        manager = self._automation_manager()
        if manager is None:
            return {"ok": False, "error": "automation manager not configured"}
        if self._tool_runtime is None or self._tool_runtime.task_manager is None:
            return {"ok": False, "error": "task manager not configured"}
        try:
            run = await manager.run_now(automation_id, self._tool_runtime.task_manager)
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "run": _automation_run_to_dict(run)}

    async def pause_automation(self, automation_id: str) -> dict[str, Any]:
        manager = self._automation_manager()
        if manager is None:
            return {"ok": False, "error": "automation manager not configured"}
        try:
            record = manager.pause_automation(automation_id)
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "automation": _automation_record_to_dict(record)}

    async def resume_automation(self, automation_id: str) -> dict[str, Any]:
        manager = self._automation_manager()
        if manager is None:
            return {"ok": False, "error": "automation manager not configured"}
        try:
            record = manager.resume_automation(automation_id)
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "automation": _automation_record_to_dict(record)}

    async def fire_trigger(self, body: dict[str, Any]) -> dict[str, Any]:
        from deepseek_tui.automation.pipeline import fire_http_trigger

        if self._tool_runtime is None or self._tool_runtime.task_manager is None:
            return {"ok": False, "error": "task manager not configured"}
        prompt = _require_str(body, "prompt")
        outcome = await fire_http_trigger(
            prompt=prompt,
            task_manager=self._tool_runtime.task_manager,
            digest=body.get("digest") if isinstance(body.get("digest"), dict) else None,
            delivery=body.get("delivery") if isinstance(body.get("delivery"), dict) else None,
            workspace=_pick_str(body, "workspace"),
            triage_policy=str(body.get("triage_policy", "skip")),
            triage_metadata=(
                body.get("triage_metadata")
                if isinstance(body.get("triage_metadata"), dict)
                else None
            ),
        )
        return {"ok": True, **outcome}

    async def list_automation_runs(
        self, automation_id: str, *, limit: int | None = None
    ) -> dict[str, Any]:
        manager = self._automation_manager()
        if manager is None:
            return {"ok": False, "error": "automation manager not configured"}
        try:
            manager.get_automation(automation_id)
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}
        runs = manager.list_runs(automation_id, limit=limit)
        return {
            "ok": True,
            "runs": [_automation_run_to_dict(r) for r in runs],
        }

    async def list_mcp_servers(self) -> dict[str, Any]:
        """Mirror Rust ``list_mcp_servers`` (runtime_api.rs:678)."""
        if self._tool_runtime is None or self._tool_runtime.mcp_manager is None:
            return {"ok": False, "error": "mcp manager not configured"}
        manager = self._tool_runtime.mcp_manager
        out: list[dict[str, Any]] = []
        for name in manager.server_names:
            cfg = manager._configs.get(name)  # noqa: SLF001
            out.append(
                {
                    "name": name,
                    "enabled": bool(getattr(cfg, "enabled", False)),
                    "transport": _transport_label(cfg),
                }
            )
        return {"ok": True, "servers": out}

    async def list_mcp_tools(self) -> dict[str, Any]:
        """Mirror Rust ``list_mcp_tools`` (runtime_api.rs:708)."""
        if self._tool_runtime is None or self._tool_runtime.mcp_manager is None:
            return {"ok": False, "error": "mcp manager not configured"}
        manager = self._tool_runtime.mcp_manager
        tools: list[dict[str, Any]] = []
        for name in manager.server_names:
            try:
                client = await manager._ensure_client(name)  # noqa: SLF001
            except Exception:  # noqa: BLE001
                continue
            try:
                listed = await client.list_tools()
            except Exception:  # noqa: BLE001
                continue
            for tool in listed:
                tools.append(
                    {
                        "server": name,
                        "name": tool.name,
                        "description": tool.description,
                    }
                )
        return {"ok": True, "tools": tools}

    async def workspace_status(self) -> dict[str, Any]:
        """Mirror Rust ``workspace_status`` (runtime_api.rs:?).

        Returns the current working directory, model, sandbox/approval
        configuration, and minimal counts. Used by the TUI / dashboards
        for a quick read-only header.
        """
        return {
            "ok": True,
            "runtime_api": {
                "mode": "http",
                "service": "deepseek-runtime-api",
                "python_version": platform.python_version(),
            },
            "workspace": {
                "cwd": str(self.working_directory),
                "model": self.config.model or self.config.default_text_model,
                "provider": self.config.provider,
                "approval_policy": self.config.approval_policy,
                "sandbox_mode": self.config.sandbox_mode,
                "thread_count": self.threads.count(),
            },
        }

    async def mcp_startup(self) -> dict[str, Any]:
        """Start every enabled MCP server and summarize results.

        Mirrors Rust ``Runtime::mcp_startup`` (core/src/lib.rs:1192-1237).
        Emits ``GenericEventFrame`` hook events for each startup update and
        the final complete summary.
        """
        from deepseek_tui.hooks.frames import generic_event_frame
        from deepseek_tui.mcp.client import McpError
        from deepseek_tui.protocol.events import (
            McpStartupCompleteEventFrame,
            McpStartupUpdateEventFrame,
        )

        if self._tool_runtime is None or self._tool_runtime.mcp_manager is None:
            return {
                "ok": True,
                "summary": {"servers": [], "note": "mcp-disabled"},
            }
        manager = self._tool_runtime.mcp_manager

        async def _on_update(update: object) -> None:
            from deepseek_tui.protocol.mcp_lifecycle import McpStartupUpdateEvent

            if not isinstance(update, McpStartupUpdateEvent):
                return
            frame = McpStartupUpdateEventFrame(update=update)
            await self.hooks.emit(generic_event_frame(frame))

        try:
            summary = await manager.start_all(_on_update, fail_on_required=True)
        except McpError as exc:
            return {"ok": False, "error": str(exc), "summary": {"servers": []}}

        manager.schedule_startup_preload(force=True)

        complete = McpStartupCompleteEventFrame(summary=summary)
        await self.hooks.emit(generic_event_frame(complete))

        summaries: list[dict[str, Any]] = []
        ready = set(summary.ready)
        failed_map = {f.server_name: f.error for f in summary.failed}
        for name in manager.server_names:
            cfg = manager._configs.get(name)  # noqa: SLF001
            if cfg is None or not cfg.enabled:
                summaries.append(
                    {"name": name, "status": "disabled", "transport": _transport_label(cfg)}
                )
            elif name in ready:
                summaries.append(
                    {
                        "name": name,
                        "status": "started",
                        "transport": _transport_label(cfg),
                    }
                )
            else:
                summaries.append(
                    {
                        "name": name,
                        "status": "failed",
                        "transport": _transport_label(cfg),
                        "error": failed_map.get(name, "startup failed"),
                    }
                )
        return {
            "ok": not summary.failed,
            "summary": {
                "servers": summaries,
                "ready": summary.ready,
                "failed": [f.model_dump() for f in summary.failed],
                "cancelled": summary.cancelled,
            },
        }


# --- helpers ---------------------------------------------------------------


def _pick_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _transport_label(cfg: Any) -> str:
    """Describe an MCP server config's transport for the startup summary."""
    if cfg is None:
        return "unknown"
    if getattr(cfg, "url", None):
        return "sse"
    if getattr(cfg, "command", None):
        return "stdio"
    return "unknown"


def _require_str(data: dict[str, Any], key: str) -> str:
    value = _pick_str(data, key)
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _automation_record_to_dict(record: Any) -> dict[str, Any]:
    return record.to_dict()


def _automation_run_to_dict(run: Any) -> dict[str, Any]:
    return run.to_dict()


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


def _task_summary_to_dict(summary: Any) -> dict[str, Any]:
    """Best-effort serialisation for TaskSummary."""
    fields = (
        "id",
        "title",
        "status",
        "created_at",
        "updated_at",
        "agent_type",
        "model",
    )
    return {f: getattr(summary, f, None) for f in fields}


def _task_record_to_dict(record: Any) -> dict[str, Any]:
    """Best-effort serialisation for TaskRecord."""
    base = _task_summary_to_dict(record)
    timeline: list[Any] = []
    for ev in getattr(record, "timeline", []) or []:
        dump = getattr(ev, "model_dump", None)
        timeline.append(dump() if callable(dump) else ev)
    base["timeline"] = timeline
    artifacts: list[Any] = []
    for art in getattr(record, "artifacts", []) or []:
        dump = getattr(art, "model_dump", None)
        artifacts.append(dump() if callable(dump) else art)
    base["artifacts"] = artifacts
    return base


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
    """Construct a HookDispatcher from ``config.hooks``."""
    return build_hook_dispatcher(config)
