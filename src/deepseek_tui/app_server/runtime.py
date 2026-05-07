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
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.config.models import Config
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
    ) -> None:
        self.config = config or Config()
        self.working_directory = (working_directory or Path.cwd()).resolve()
        self._tool_runtime: ToolRuntime | None = tool_runtime
        self.threads = ThreadStore()

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
        """Minimal prompt handler — records the prompt on a fresh thread.

        Stage 4.1 scope: does NOT yet call the LLM. The Engine path is
        exercised when the client wires an LLM + approval handler — left
        to a caller-side integration to keep 4.1 hermetic.
        """
        text = _pick_str(payload, "input") or _pick_str(payload, "prompt")
        if text is None:
            return {
                "output": "missing 'input' or 'prompt'",
                "model": "unknown",
                "events": [],
            }
        rec = self.threads.create(model=_pick_str(payload, "model"))
        rec.messages.append(Message.user(text))
        return {
            "output": f"accepted on {rec.thread_id}",
            "model": rec.model or self.config.default_text_model,
            "events": [],
        }

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
        try:
            tool = self._tool_runtime.registry.get(tool_name)
        except Exception as exc:  # noqa: BLE001 — registry raises ToolError
            return {"ok": False, "error": str(exc)}
        try:
            result = await tool.execute(arguments, self._tool_runtime.context)
        except Exception as exc:  # noqa: BLE001 — surface to caller
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
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
