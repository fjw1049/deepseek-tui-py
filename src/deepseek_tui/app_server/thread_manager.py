"""RuntimeThreadManager — orchestrates Engine lifecycles for HTTP threads.

Mirrors Rust ``RuntimeThreadManager`` (runtime_threads.rs:594-2488).
Manages active engines, turn monitoring, LRU eviction, and restart recovery.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.app_server.broadcast import AsyncBroadcast
from deepseek_tui.app_server.runtime_threads import (
    EVENT_CHANNEL_CAPACITY,
    RUNTIME_RESTART_REASON,
    SUMMARY_LIMIT,
    CompactThreadRequest,
    CreateThreadRequest,
    RuntimeEventRecord,
    RuntimeThreadManagerConfig,
    RuntimeThreadStore,
    RuntimeTurnStatus,
    StartTurnRequest,
    SteerTurnRequest,
    ThreadDetail,
    ThreadRecord,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
    UpdateThreadRequest,
    duration_ms,
    file_change_completion_detail,
    reconstruct_messages_from_turns,
    tool_kind_for_name,
    tool_item_metadata,
    todo_tool_metadata_from_result,
)
from deepseek_tui.app_server.session_import import ImportTuiSessionRequest
from deepseek_tui.config.models import Config
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ElevationRequiredEvent,
    ErrorEvent,
    StatusEvent,
    SubAgentMailboxEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.tools.subagent.mailbox import MailboxMessage
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.utils import summarize_text

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.engine.engine import Engine
    from deepseek_tui.engine.handle import ApprovalHandler

logger = logging.getLogger(__name__)

__all__ = ["RuntimeThreadManager"]


def _mailbox_message_payload(msg: MailboxMessage) -> dict[str, Any]:
    """JSON-serializable mailbox envelope for Workbench sub-agent cards."""
    return {
        "kind": msg.kind.value,
        "agent_id": msg.agent_id,
        "agent_type": msg.agent_type,
        "status": msg.status,
        "tool_name": msg.tool_name,
        "step": msg.step,
        "ok": msg.ok,
        "parent_id": msg.parent_id,
        "summary": msg.summary,
        "error": msg.error,
        "model": msg.model,
        "usage": msg.usage,
    }


# --- internal state types ----------------------------------------------------


class _ActiveTurnState:
    __slots__ = ("turn_id", "interrupt_requested", "auto_approve", "trust_mode")

    def __init__(
        self,
        turn_id: str,
        auto_approve: bool = False,
        trust_mode: bool = False,
    ) -> None:
        self.turn_id = turn_id
        self.interrupt_requested = False
        self.auto_approve = auto_approve
        self.trust_mode = trust_mode


class _ActiveThreadState:
    __slots__ = ("handle", "engine", "engine_task", "active_turn")

    def __init__(
        self,
        handle: EngineHandle,
        engine: Engine,
        engine_task: asyncio.Task[None],
    ) -> None:
        self.handle = handle
        self.engine = engine
        self.engine_task: asyncio.Task[None] = engine_task
        self.active_turn: _ActiveTurnState | None = None


class _ApprovalDecision:
    APPROVE = "approve"
    DENY = "deny"
    RETRY_FULL_ACCESS = "retry_full_access"


@dataclass(slots=True)
class _PendingUserInputRecord:
    thread_id: str
    turn_id: str | None
    questions: list[dict[str, Any]]


# --- RuntimeThreadManager ----------------------------------------------------


class RuntimeThreadManager:
    """Manages active engine threads, lifecycle, and event persistence.

    Mirrors Rust ``RuntimeThreadManager`` (line 594-2488).
    """

    def __init__(
        self,
        config: Config,
        workspace: Path,
        manager_cfg: RuntimeThreadManagerConfig,
        llm_client: LLMClient | None = None,
        approval_bridge: Any | None = None,
        elevation_bridge: Any | None = None,
    ) -> None:
        self.config = config
        self.workspace = workspace.resolve()
        self.manager_cfg = manager_cfg
        self.store = RuntimeThreadStore(manager_cfg.data_dir)
        self._llm_client = llm_client
        self._approval_bridge = approval_bridge
        self._elevation_bridge = elevation_bridge

        self._active: dict[str, _ActiveThreadState] = {}
        self._lru: OrderedDict[str, None] = OrderedDict()
        self._active_lock = asyncio.Lock()
        self._pending_user_inputs: dict[str, _PendingUserInputRecord] = {}

        self.event_bus: AsyncBroadcast[RuntimeEventRecord] = AsyncBroadcast(
            capacity=EVENT_CHANNEL_CAPACITY
        )
        self._cancel_event = asyncio.Event()

        self._recover_interrupted_state()

    @staticmethod
    def _sync_trust_mode(engine: Engine, trust_mode: bool) -> None:
        """Mirror thread / turn trust onto ToolContext (TUI session parity)."""
        engine.tool_context.trust_mode = trust_mode

    def _trust_mode_for_thread(
        self, thread: ThreadRecord, state: _ActiveThreadState | None
    ) -> bool:
        if state is not None and state.active_turn is not None:
            return state.active_turn.trust_mode
        return thread.trust_mode

    async def jobs_snapshot(
        self, thread_id: str | None = None
    ) -> dict[str, object]:
        """Shell background jobs + durable task counts for Workbench /v1/jobs."""
        shell_jobs: list[dict[str, object]] = []
        task_counts = {"queued": 0, "running": 0}
        async with self._active_lock:
            if thread_id and thread_id in self._active:
                pairs = [(thread_id, self._active[thread_id])]
            else:
                pairs = list(self._active.items())
            for tid, state in pairs:
                store = state.engine.tool_context.metadata.get("shell_processes")
                if isinstance(store, dict):
                    for job_id, proc in store.items():
                        pid = getattr(proc, "pid", None)
                        rc = getattr(proc, "returncode", None)
                        shell_jobs.append(
                            {
                                "id": job_id,
                                "pid": pid,
                                "status": "running" if rc is None else "exited",
                                "returncode": rc,
                                "thread_id": tid,
                            }
                        )
                tm = getattr(state.engine, "task_manager", None)
                if tm is not None:
                    counts = await tm.counts()
                    task_counts["queued"] += counts.queued
                    task_counts["running"] += counts.running

        return {
            "shell_jobs": shell_jobs,
            "tasks": task_counts,
            "hint": (
                "Foreground exec_shell timed out? Use task_shell_start for durable "
                "background work, then task_shell_wait."
            ),
        }

    # --- public lifecycle ----------------------------------------------------

    def shutdown(self) -> None:
        self._cancel_event.set()
        if self._approval_bridge is not None:
            self._approval_bridge.cancel_all()
        if self._elevation_bridge is not None:
            self._elevation_bridge.cancel_all()

    @property
    def is_shutdown(self) -> bool:
        return self._cancel_event.is_set()

    def subscribe_events(self) -> asyncio.Queue[RuntimeEventRecord]:
        return self.event_bus.subscribe()

    # --- thread CRUD ---------------------------------------------------------

    async def create_thread(self, req: CreateThreadRequest) -> ThreadRecord:
        now = datetime.now(timezone.utc)
        model = (
            (req.model or "").strip()
            or self.config.default_text_model
        )
        workspace = req.workspace or str(self.workspace)
        mode = (req.mode or "").strip() or "agent"
        allow_shell = req.allow_shell if req.allow_shell is not None else self.config.allow_shell
        trust_mode = req.trust_mode if req.trust_mode is not None else False
        auto_approve = req.auto_approve if req.auto_approve is not None else False

        thread = ThreadRecord(
            id=f"thr_{uuid.uuid4().hex[:8]}",
            created_at=now,
            updated_at=now,
            model=model,
            workspace=workspace,
            mode=mode,
            allow_shell=allow_shell,
            trust_mode=trust_mode,
            auto_approve=auto_approve,
            archived=req.archived,
            system_prompt=req.system_prompt,
            task_id=req.task_id,
        )
        self.store.save_thread(thread)
        await self._emit_event(
            thread.id, None, None, "thread.started", {"thread": thread.model_dump(mode="json")}
        )
        return thread

    async def import_tui_session(self, req: ImportTuiSessionRequest) -> ThreadRecord:
        """Create a Workbench thread from a TUI session JSON snapshot."""
        from deepseek_tui.app_server.session_import import (
            import_messages_into_store,
            load_tui_session_messages,
            resolve_tui_session_path,
        )

        path = resolve_tui_session_path(session_id=req.session_id, path=req.path)
        metadata, messages = load_tui_session_messages(path)
        if not messages:
            raise ValueError("Session has no importable user/assistant messages")

        meta_model = metadata.get("model") if isinstance(metadata.get("model"), str) else None
        meta_workspace = (
            metadata.get("workspace") if isinstance(metadata.get("workspace"), str) else None
        )
        meta_title = metadata.get("title") if isinstance(metadata.get("title"), str) else None
        session_id = metadata.get("id") if isinstance(metadata.get("id"), str) else path.stem

        thread = await self.create_thread(
            CreateThreadRequest(
                model=req.model or meta_model,
                workspace=req.workspace or meta_workspace or str(self.workspace),
                mode=req.mode,
            )
        )
        title = (req.title or meta_title or f"TUI {session_id[:8]}").strip()
        thread.source_session_id = session_id
        thread.source_session_path = str(path.resolve())
        if title:
            thread.title = title
            thread.updated_at = datetime.now(timezone.utc)
            self.store.save_thread(thread)
        import_messages_into_store(
            self.store,
            thread_id=thread.id,
            messages=messages,
        )
        turns = self.store.list_turns_for_thread(thread.id)
        if turns:
            thread.latest_turn_id = turns[-1].id
            thread.updated_at = datetime.now(timezone.utc)
            self.store.save_thread(thread)

        await self._emit_event(
            thread.id,
            None,
            None,
            "thread.imported",
            {
                "thread": thread.model_dump(mode="json"),
                "source": "tui_session",
                "session_path": str(path),
                "message_count": len(messages),
            },
        )
        return thread

    async def list_threads(
        self, include_archived: bool = False, limit: int | None = None
    ) -> list[ThreadRecord]:
        threads = self.store.list_threads()
        if not include_archived:
            threads = [t for t in threads if not t.archived]
        if limit is not None:
            threads = threads[:limit]
        return threads

    async def get_thread(self, thread_id: str) -> ThreadRecord:
        return self.store.load_thread(thread_id)

    async def is_thread_turn_active(self, thread_id: str) -> bool:
        """Lightweight running check for background turn-completion polling."""
        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is not None and state.active_turn is not None:
                return True
        thread = self.store.load_thread(thread_id)
        turn_id = thread.latest_turn_id
        if not turn_id:
            return False
        turn = self.store.load_turn(turn_id)
        return turn.status in (
            RuntimeTurnStatus.QUEUED,
            RuntimeTurnStatus.IN_PROGRESS,
        )

    async def update_thread(self, thread_id: str, req: UpdateThreadRequest) -> ThreadRecord:
        if req.archived is None and req.title is None:
            raise ValueError("At least one thread field is required")
        thread = self.store.load_thread(thread_id)
        changed = False
        changes: dict[str, Any] = {}
        if req.archived is not None and thread.archived != req.archived:
            thread.archived = req.archived
            changed = True
            changes["archived"] = thread.archived
        if req.title is not None:
            normalized = req.title.strip()
            title = normalized or None
            if thread.title != title:
                thread.title = title
                changed = True
                changes["title"] = thread.title
        if changed:
            thread.updated_at = datetime.now(timezone.utc)
            self.store.save_thread(thread)
            await self._emit_event(
                thread.id,
                None,
                None,
                "thread.updated",
                {
                    "thread": thread.model_dump(mode="json"),
                    "changes": changes,
                },
            )
        return thread

    async def resolve_user_input(
        self,
        request_id: str,
        *,
        answers: list[dict[str, Any]] | None = None,
        cancelled: bool = False,
    ) -> bool:
        async with self._active_lock:
            for state in self._active.values():
                if request_id not in state.handle.pending_user_inputs:
                    continue
                if cancelled:
                    resolved = state.handle.resolve_user_input(
                        request_id, {"cancelled": True}
                    )
                else:
                    resolved = state.handle.resolve_user_input(
                        request_id, {"answers": answers or []}
                    )
                if resolved:
                    self._pending_user_inputs.pop(request_id, None)
                return resolved
        return False

    async def list_pending_user_inputs(
        self, thread_id: str | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async with self._active_lock:
            for tid, state in self._active.items():
                if thread_id and tid != thread_id:
                    continue
                for request_id, fut in state.handle.pending_user_inputs.items():
                    if fut.done():
                        continue
                    meta = self._pending_user_inputs.get(request_id)
                    questions = meta.questions if meta is not None else []
                    out.append(
                        {
                            "request_id": request_id,
                            "id": request_id,
                            "thread_id": tid,
                            "turn_id": meta.turn_id if meta else None,
                            "questions": questions,
                        }
                    )
        return out

    async def get_thread_detail(self, thread_id: str) -> ThreadDetail:
        thread = self.store.load_thread(thread_id)
        turns = self.store.list_turns_for_thread(thread_id)
        items: list[TurnItemRecord] = []
        for turn in turns:
            items.extend(self.store.list_items_for_turn(turn.id))
        latest_seq = await self.store.current_seq()
        return ThreadDetail(thread=thread, turns=turns, items=items, latest_seq=latest_seq)

    async def get_thread_context_breakdown(self, thread_id: str) -> dict[str, int]:
        """Context window estimate for Workbench / HTTP clients.

        Uses the live engine when the thread is already loaded (same numbers
        as TUI ``/context``). Otherwise reconstructs messages from the store
        and estimates with the default tool registry for that thread mode.
        """
        from pathlib import Path

        from deepseek_tui.engine.context import estimate_context_breakdown
        from deepseek_tui.tools.builder import build_default_registry

        thread = self.store.load_thread(thread_id)
        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is not None:
                return state.engine.context_breakdown(thread.model)

        messages = reconstruct_messages_from_turns(self.store, thread_id)
        workspace = Path(thread.workspace).expanduser().resolve()
        mode = (thread.mode or "agent").strip() or "agent"
        registry = build_default_registry(self.config, mode=mode)
        try:
            api_tools = registry.to_api_tools()
        except Exception:  # noqa: BLE001
            api_tools = []

        return estimate_context_breakdown(
            model=thread.model,
            messages=messages or None,
            system_prompt_override=thread.system_prompt,
            api_tools=api_tools,
            workspace=workspace,
            mode=mode,
        )

    async def resume_thread(self, thread_id: str) -> ThreadDetail:
        """Touch a thread so its engine is loaded and return its detail.

        Mirrors Rust ``RuntimeThreadManager::resume_thread`` (runtime_threads.rs:809-813).
        The Rust version does ``ensure_engine_loaded`` to re-hydrate the
        engine task; here we drive the same path through ``_ensure_engine_loaded``
        so the LRU cache + engine task wake up before clients hit the next
        ``/threads/{id}/turns`` request. Re-emits a ``thread.resumed``
        event for parity with Rust's event timeline.
        """
        thread = self.store.load_thread(thread_id)
        await self._ensure_engine_loaded(thread)
        await self._emit_event(
            thread.id,
            None,
            None,
            "thread.resumed",
            {"thread": thread.model_dump(mode="json")},
        )
        return await self.get_thread_detail(thread_id)

    async def threads_summary(self) -> dict[str, Any]:
        """Compact roll-up over all threads.

        Mirrors Rust ``GET /v1/threads/summary`` (runtime_api.rs:568-648).
        Returns aggregate counts + last-updated id so dashboards / TUI
        sidebars can render a header without paginating the full list.
        Python's ``ThreadRecord`` doesn't carry a status enum (Rust does),
        so we expose ``active`` vs ``archived`` and a per-mode breakdown.
        """
        threads = self.store.list_threads()
        active = 0
        archived = 0
        modes: dict[str, int] = {}
        latest_id: str | None = None
        latest_ts = None
        for t in threads:
            if t.archived:
                archived += 1
            else:
                active += 1
            modes[t.mode] = modes.get(t.mode, 0) + 1
            ts = t.updated_at
            if latest_ts is None or (ts is not None and ts > latest_ts):
                latest_ts = ts
                latest_id = t.id
        return {
            "total": len(threads),
            "active": active,
            "archived": archived,
            "modes": modes,
            "latest_thread_id": latest_id,
            "latest_updated_at": latest_ts.isoformat() if latest_ts else None,
        }

    async def fork_thread(self, thread_id: str) -> ThreadRecord:
        source = self.store.load_thread(thread_id)
        now = datetime.now(timezone.utc)
        forked = source.model_copy(
            update={
                "id": f"thr_{uuid.uuid4().hex[:8]}",
                "created_at": now,
                "updated_at": now,
                "latest_turn_id": None,
                "archived": False,
            }
        )
        self.store.save_thread(forked)

        source_turns = self.store.list_turns_for_thread(source.id)
        for source_turn in source_turns:
            cloned_turn = source_turn.model_copy(
                update={
                    "id": f"turn_{uuid.uuid4().hex[:8]}",
                    "thread_id": forked.id,
                    "item_ids": [],
                }
            )
            self.store.save_turn(cloned_turn)

            items = self.store.list_items_for_turn(source_turn.id)
            for item in items:
                cloned_item = item.model_copy(
                    update={
                        "id": f"item_{uuid.uuid4().hex[:8]}",
                        "turn_id": cloned_turn.id,
                    }
                )
                self.store.save_item(cloned_item)
                cloned_turn.item_ids.append(cloned_item.id)
            self.store.save_turn(cloned_turn)
            forked.latest_turn_id = cloned_turn.id
            forked.updated_at = now
            self.store.save_thread(forked)

        await self._emit_event(
            forked.id,
            None,
            None,
            "thread.forked",
            {"thread": forked.model_dump(mode="json"), "source_thread_id": source.id},
        )
        return forked

    # --- turn lifecycle ------------------------------------------------------

    async def start_turn(self, thread_id: str, req: StartTurnRequest) -> TurnRecord:
        prompt = req.prompt.strip()
        if not prompt:
            raise ValueError("prompt is required")

        thread = self.store.load_thread(thread_id)
        handle, engine_task = await self._ensure_engine_loaded(thread)

        effective_mode = (req.mode or thread.mode or "agent").strip() or "agent"

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is not None and state.active_turn is not None:
                raise ValueError("Thread already has an active turn")
            if state is not None:
                state.engine.mode = effective_mode

        now = datetime.now(timezone.utc)
        turn_id = f"turn_{uuid.uuid4().hex[:8]}"
        auto_approve = req.auto_approve if req.auto_approve is not None else thread.auto_approve
        trust_mode = req.trust_mode if req.trust_mode is not None else thread.trust_mode

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is None:
                raise RuntimeError("Thread engine not loaded")
            state.active_turn = _ActiveTurnState(
                turn_id=turn_id, auto_approve=auto_approve, trust_mode=trust_mode
            )
            self._sync_trust_mode(state.engine, trust_mode)
            self._touch_lru(thread_id)

        turn = TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary=req.input_summary or summarize_text(prompt, SUMMARY_LIMIT),
            created_at=now,
            started_at=now,
        )

        user_item_id = f"item_{uuid.uuid4().hex[:8]}"
        user_item = TurnItemRecord(
            id=user_item_id,
            turn_id=turn_id,
            kind=TurnItemKind.USER_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary=summarize_text(prompt, SUMMARY_LIMIT),
            detail=prompt,
            started_at=now,
            ended_at=now,
        )
        turn.item_ids.append(user_item_id)
        self.store.save_item(user_item)
        self.store.save_turn(turn)

        thread.latest_turn_id = turn_id
        thread.updated_at = now
        self.store.save_thread(thread)

        await self._emit_event(
            thread_id, turn_id, None, "turn.started", {"turn": turn.model_dump(mode="json")}
        )
        await self._emit_event(
            thread_id, turn_id, user_item_id, "item.completed",
            {"item": user_item.model_dump(mode="json")},
        )

        model = req.model or thread.model
        monitor_task = asyncio.create_task(
            self._monitor_turn_safe(thread_id, turn_id, handle),
            name=f"monitor-{turn_id}",
        )
        await handle.send_message(content=prompt, model=model)
        # Monitor runs concurrently; ensure task is referenced until turn ends.
        del monitor_task

        return turn

    async def interrupt_turn(self, thread_id: str, turn_id: str) -> TurnRecord:
        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is None:
                raise ValueError("Thread is not loaded")
            if state.active_turn is None or state.active_turn.turn_id != turn_id:
                raise ValueError(f"Turn {turn_id} is not active on thread {thread_id}")
            state.active_turn.interrupt_requested = True
            await state.handle.cancel(reason="interrupt_requested")
            self._touch_lru(thread_id)

        await self._emit_event(
            thread_id, turn_id, None, "turn.interrupt_requested",
            {"thread_id": thread_id, "turn_id": turn_id},
        )
        return self.store.load_turn(turn_id)

    async def steer_turn(
        self, thread_id: str, turn_id: str, req: SteerTurnRequest
    ) -> TurnRecord:
        prompt = req.prompt.strip()
        if not prompt:
            raise ValueError("prompt is required")

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is None:
                raise ValueError("Thread is not loaded")
            if state.active_turn is None or state.active_turn.turn_id != turn_id:
                raise ValueError(f"Turn {turn_id} is not active on thread {thread_id}")
            handle = state.handle
            self._touch_lru(thread_id)

        await handle.steer(prompt)

        now = datetime.now(timezone.utc)
        turn = self.store.load_turn(turn_id)
        turn.steer_count += 1
        self.store.save_turn(turn)

        item = TurnItemRecord(
            id=f"item_{uuid.uuid4().hex[:8]}",
            turn_id=turn_id,
            kind=TurnItemKind.USER_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary=summarize_text(prompt, SUMMARY_LIMIT),
            detail=prompt,
            started_at=now,
            ended_at=now,
        )
        turn.item_ids.append(item.id)
        self.store.save_item(item)
        self.store.save_turn(turn)

        await self._emit_event(
            thread_id, turn_id, item.id, "turn.steered",
            {"thread_id": thread_id, "turn_id": turn_id, "input": prompt},
        )
        return turn

    async def compact_thread(self, thread_id: str, req: CompactThreadRequest) -> TurnRecord:
        thread = self.store.load_thread(thread_id)
        await self._ensure_engine_loaded(thread)

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is None:
                raise RuntimeError("Thread engine not loaded")
            if state.active_turn is not None:
                raise ValueError("Thread already has an active turn")

        now = datetime.now(timezone.utc)
        turn_id = f"turn_{uuid.uuid4().hex[:8]}"

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is None:
                raise RuntimeError("Thread engine not loaded")
            state.active_turn = _ActiveTurnState(
                turn_id=turn_id,
                auto_approve=thread.auto_approve,
                trust_mode=thread.trust_mode,
            )
            self._touch_lru(thread_id)
            engine = state.engine

        turn = TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary=(
                summarize_text(req.reason, SUMMARY_LIMIT) if req.reason
                else "Manual context compaction"
            ),
            created_at=now,
            started_at=now,
        )
        self.store.save_turn(turn)

        thread.latest_turn_id = turn_id
        thread.updated_at = now
        self.store.save_thread(thread)

        await self._emit_event(
            thread_id, turn_id, None, "turn.started",
            {"turn": turn.model_dump(mode="json"), "manual_compaction": True},
        )

        before_count = len(engine.session_messages)
        if before_count == 0:
            summary_text = "Nothing to compact — session is empty."
            engine.session_messages.clear()
        else:
            compacted = await engine._emergency_compact(list(engine.session_messages))
            engine.session_messages[:] = compacted
            summary_text = (
                f"Context compacted: {before_count} → {len(compacted)} messages."
            )

        item_id = f"item_{uuid.uuid4().hex[:8]}"
        item = TurnItemRecord(
            id=item_id,
            turn_id=turn_id,
            kind=TurnItemKind.CONTEXT_COMPACTION,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary=summarize_text(summary_text, SUMMARY_LIMIT),
            detail=summary_text,
            started_at=now,
            ended_at=now,
        )
        turn.item_ids.append(item_id)
        self.store.save_item(item)
        self.store.save_turn(turn)

        ended_at = datetime.now(timezone.utc)
        turn.status = RuntimeTurnStatus.COMPLETED
        turn.ended_at = ended_at
        if turn.started_at:
            turn.duration_ms = duration_ms(turn.started_at, ended_at)
        self.store.save_turn(turn)

        thread.updated_at = ended_at
        self.store.save_thread(thread)

        await self._emit_event(
            thread_id, turn_id, item_id, "item.completed",
            {"item": item.model_dump(mode="json")},
        )
        await self._emit_event(
            thread_id, turn_id, None, "turn.completed",
            {"turn": turn.model_dump(mode="json")},
        )
        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is not None and state.active_turn is not None:
                if state.active_turn.turn_id == turn_id:
                    state.active_turn = None
        return turn

    # --- events query --------------------------------------------------------

    def events_since(
        self, thread_id: str, since_seq: int | None = None
    ) -> list[RuntimeEventRecord]:
        return self.store.events_since(thread_id, since_seq)

    # --- engine loading + LRU ------------------------------------------------

    async def _ensure_engine_loaded(
        self, thread: ThreadRecord
    ) -> tuple[EngineHandle, asyncio.Task[None]]:
        async with self._active_lock:
            state = self._active.get(thread.id)
            if state is not None:
                self._sync_trust_mode(
                    state.engine, self._trust_mode_for_thread(thread, state)
                )
                state.engine.mode = (thread.mode or "agent").strip() or "agent"
                self._touch_lru(thread.id)
                return state.handle, state.engine_task

        from deepseek_tui.engine.engine import Engine
        from deepseek_tui.execpolicy.engine import exec_policy_for_config

        handle = EngineHandle()
        workspace = Path(thread.workspace).expanduser().resolve()
        approval_handler = self._build_approval_handler(thread.id)
        engine = await Engine.create(
            handle=handle,
            client=self._get_llm_client(),
            config=self.config,
            working_directory=workspace,
            default_model=thread.model,
            mode=(thread.mode or "agent").strip() or "agent",
            task_data_dir=self.manager_cfg.task_data_dir,
            start_mcp=bool(getattr(self.config.features, "mcp", False)),
            approval_handler=approval_handler,
            exec_policy=exec_policy_for_config(self.config),
        )
        self._sync_trust_mode(engine, thread.trust_mode)
        self._sync_engine_session(engine, thread)
        engine.tool_context.metadata["runtime_thread_id"] = thread.id
        if self._elevation_bridge is not None:
            engine.tool_context.metadata["elevation_bridge"] = self._elevation_bridge
        engine_task = asyncio.create_task(engine.run(), name=f"engine-{thread.id}")

        async with self._active_lock:
            evicted = self._enforce_lru_capacity()
            self._active[thread.id] = _ActiveThreadState(
                handle=handle, engine=engine, engine_task=engine_task
            )
            self._touch_lru(thread.id)

        for evicted_state in evicted:
            await evicted_state.handle.cancel(reason="lru_eviction")
            evicted_state.engine_task.cancel()

        return handle, engine_task

    def _sync_engine_session(self, engine: Engine, thread: ThreadRecord) -> None:
        """Hydrate Engine.session_messages from durable turn items."""
        messages = reconstruct_messages_from_turns(self.store, thread.id)
        if messages:
            engine.sync_session(messages, model=thread.model)

    def _build_approval_handler(self, thread_id: str) -> ApprovalHandler:
        from deepseek_tui.app_server.runtime_api.approval_bridge import (
            HttpApprovalHandler,
        )
        from deepseek_tui.engine.handle import AutoApprovalHandler

        if self._approval_bridge is None:
            return AutoApprovalHandler()

        manager = self

        async def auto_approve() -> bool:
            async with manager._active_lock:
                state = manager._active.get(thread_id)
                if state is not None and state.active_turn is not None:
                    return state.active_turn.auto_approve
            thread = manager.store.load_thread(thread_id)
            return thread.auto_approve

        return HttpApprovalHandler(
            self._approval_bridge,
            thread_id=thread_id,
            auto_approve=auto_approve,
        )

    def _get_llm_client(self) -> LLMClient:
        if self._llm_client is not None:
            return self._llm_client
        from deepseek_tui.client.deepseek import DeepSeekClient

        return DeepSeekClient.from_config(self.config)

    def _touch_lru(self, thread_id: str) -> None:
        self._lru.pop(thread_id, None)
        self._lru[thread_id] = None

    def _enforce_lru_capacity(self) -> list[_ActiveThreadState]:
        max_active = self.manager_cfg.max_active_threads
        evicted: list[_ActiveThreadState] = []
        if max_active == 0 or len(self._active) < max_active:
            return evicted
        protected = {
            tid for tid, s in self._active.items() if s.active_turn is not None
        }
        for tid in list(self._lru.keys()):
            if len(self._active) < max_active:
                break
            if tid in protected:
                continue
            state = self._active.pop(tid, None)
            if state is not None:
                evicted.append(state)
            self._lru.pop(tid, None)
            break
        return evicted

    # --- turn monitoring -----------------------------------------------------

    async def _monitor_turn_safe(
        self, thread_id: str, turn_id: str, handle: EngineHandle
    ) -> None:
        try:
            await self._monitor_turn(thread_id, turn_id, handle)
        except Exception as exc:
            logger.error("Turn monitor failed for %s: %s", turn_id, exc)

    async def _monitor_turn(
        self, thread_id: str, turn_id: str, handle: EngineHandle
    ) -> None:
        """Consume engine events and persist turn items + runtime events.

        Mirrors Rust ``monitor_turn`` (line 1641-2373).
        """
        current_message_text = ""
        current_message_item_id: str | None = None
        current_reasoning_item_id: str | None = None
        current_reasoning_text = ""
        tool_items: dict[str, str] = {}  # tool_call_id -> item_id
        tool_call_args: dict[str, Any] = {}  # tool_call_id -> raw arguments
        turn_status = RuntimeTurnStatus.COMPLETED
        turn_error: str | None = None
        turn_usage: dict[str, Any] | None = None

        async for event in handle.events():
            if self._cancel_event.is_set():
                turn_status = RuntimeTurnStatus.INTERRUPTED
                break

            if isinstance(event, TurnStartedEvent):
                await self._emit_event(
                    thread_id, turn_id, None, "turn.lifecycle", {"status": "in_progress"}
                )

            elif isinstance(event, TextDeltaEvent):
                if current_reasoning_item_id is not None:
                    item = self.store.load_item(current_reasoning_item_id)
                    item.status = TurnItemLifecycleStatus.COMPLETED
                    item.summary = summarize_text(current_reasoning_text, SUMMARY_LIMIT)
                    item.detail = current_reasoning_text
                    item.ended_at = datetime.now(timezone.utc)
                    self.store.save_item(item)
                    await self._emit_event(
                        thread_id, turn_id, current_reasoning_item_id, "item.completed",
                        {"item": item.model_dump(mode="json")},
                    )
                    current_reasoning_item_id = None
                    current_reasoning_text = ""

                if current_message_item_id is None:
                    item_id = f"item_{uuid.uuid4().hex[:8]}"
                    now = datetime.now(timezone.utc)
                    item = TurnItemRecord(
                        id=item_id,
                        turn_id=turn_id,
                        kind=TurnItemKind.AGENT_MESSAGE,
                        status=TurnItemLifecycleStatus.IN_PROGRESS,
                        summary="",
                        detail="",
                        started_at=now,
                    )
                    self.store.save_item(item)
                    self._attach_item_to_turn(turn_id, item_id)
                    await self._emit_event(
                        thread_id, turn_id, item_id, "item.started",
                        {"item": item.model_dump(mode="json")},
                    )
                    current_message_item_id = item_id
                    current_message_text = ""

                current_message_text += event.text
                await self._emit_event(
                    thread_id, turn_id, current_message_item_id, "item.delta",
                    {"delta": event.text, "kind": "agent_message"},
                )

            elif isinstance(event, ThinkingDeltaEvent):
                if current_reasoning_item_id is None:
                    item_id = f"item_{uuid.uuid4().hex[:8]}"
                    now = datetime.now(timezone.utc)
                    item = TurnItemRecord(
                        id=item_id,
                        turn_id=turn_id,
                        kind=TurnItemKind.AGENT_REASONING,
                        status=TurnItemLifecycleStatus.IN_PROGRESS,
                        summary="",
                        detail="",
                        started_at=now,
                    )
                    self.store.save_item(item)
                    self._attach_item_to_turn(turn_id, item_id)
                    await self._emit_event(
                        thread_id, turn_id, item_id, "item.started",
                        {"item": item.model_dump(mode="json")},
                    )
                    current_reasoning_item_id = item_id
                    current_reasoning_text = ""

                current_reasoning_text += event.thinking
                await self._emit_event(
                    thread_id, turn_id, current_reasoning_item_id, "item.delta",
                    {"delta": event.thinking, "kind": "agent_reasoning"},
                )

            elif isinstance(event, ToolCallEvent):
                tc = event.tool_call
                item_id = f"item_{uuid.uuid4().hex[:8]}"
                tool_items[tc.id] = item_id
                tool_call_args[tc.id] = tc.arguments
                kind = tool_kind_for_name(tc.name)
                now = datetime.now(timezone.utc)
                metadata = tool_item_metadata(tc.name, tc.arguments)
                item = TurnItemRecord(
                    id=item_id,
                    turn_id=turn_id,
                    kind=kind,
                    status=TurnItemLifecycleStatus.IN_PROGRESS,
                    summary=summarize_text(f"{tc.name} started", SUMMARY_LIMIT),
                    detail=str(tc.arguments) if tc.arguments else None,
                    metadata=metadata,
                    started_at=now,
                )
                self.store.save_item(item)
                self._attach_item_to_turn(turn_id, item_id)
                await self._emit_event(
                    thread_id, turn_id, item_id, "item.started",
                    {
                        "item": item.model_dump(mode="json"),
                        # ``input`` is what the GUI provider needs to render
                        # interactive ``request_user_input`` blocks live;
                        # without it the questions only appear after the turn
                        # completes (via ThreadDetail reload). Mirrors Rust
                        # runtime_threads.rs ``item.started`` payload.
                        "tool": {
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        },
                    },
                )

            elif isinstance(event, ToolResultEvent):
                item_id = tool_items.pop(event.tool_call_id, None)
                tool_args = tool_call_args.pop(event.tool_call_id, None)
                if item_id is not None:
                    item = self.store.load_item(item_id)
                    now = datetime.now(timezone.utc)
                    item.ended_at = now
                    if event.success:
                        item.status = TurnItemLifecycleStatus.COMPLETED
                        item.summary = summarize_text(
                            f"{event.tool_name}: {event.content}", SUMMARY_LIMIT
                        )
                    else:
                        item.status = TurnItemLifecycleStatus.FAILED
                        item.summary = summarize_text(
                            f"{event.tool_name} failed: {event.content}", SUMMARY_LIMIT
                        )
                    if item.kind == TurnItemKind.FILE_CHANGE:
                        item.detail = file_change_completion_detail(
                            event.tool_name,
                            tool_args,
                            event.content or "",
                        )
                    else:
                        item.detail = event.content
                    if item.metadata is None or not isinstance(item.metadata, dict):
                        item.metadata = {"tool_name": event.tool_name}
                    elif "tool_name" not in item.metadata:
                        item.metadata = {**item.metadata, "tool_name": event.tool_name}
                    refreshed = todo_tool_metadata_from_result(
                        event.tool_name,
                        tool_args,
                        event.metadata,
                        item.metadata if isinstance(item.metadata, dict) else None,
                    )
                    if refreshed:
                        item.metadata = {**item.metadata, **refreshed}
                    self.store.save_item(item)
                    event_name = (
                        "item.completed" if item.status == TurnItemLifecycleStatus.COMPLETED
                        else "item.failed"
                    )
                    await self._emit_event(
                        thread_id, turn_id, item_id, event_name,
                        {"item": item.model_dump(mode="json")},
                    )

            elif isinstance(event, ApprovalRequiredEvent):
                from deepseek_tui.tools.approval_present import (
                    approval_request_to_sse_payload,
                )

                approval_id = event.tool_call_id
                await self._emit_event(
                    thread_id,
                    turn_id,
                    None,
                    "approval.required",
                    approval_request_to_sse_payload(approval_id, event.request),
                )

            elif isinstance(event, ElevationRequiredEvent):
                from deepseek_tui.tools.elevation_present import (
                    elevation_request_to_sse_payload,
                )

                await self._emit_event(
                    thread_id,
                    turn_id,
                    None,
                    "elevation.required",
                    elevation_request_to_sse_payload(event.tool_call_id, event),
                )

            elif isinstance(event, StatusEvent):
                now = datetime.now(timezone.utc)
                item_id = f"item_{uuid.uuid4().hex[:8]}"
                summary = summarize_text(event.message, SUMMARY_LIMIT)
                item = TurnItemRecord(
                    id=item_id,
                    turn_id=turn_id,
                    kind=TurnItemKind.STATUS,
                    status=TurnItemLifecycleStatus.COMPLETED,
                    summary=summary,
                    detail=event.message,
                    started_at=now,
                    ended_at=now,
                )
                self.store.save_item(item)
                self._attach_item_to_turn(turn_id, item_id)
                await self._emit_event(
                    thread_id,
                    turn_id,
                    item_id,
                    "item.completed",
                    {"item": item.model_dump(mode="json")},
                )

            elif isinstance(event, UserInputRequiredEvent):
                self._pending_user_inputs[event.tool_call_id] = _PendingUserInputRecord(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    questions=list(event.questions),
                )
                now = datetime.now(timezone.utc)
                item_id = event.tool_call_id
                try:
                    self.store.load_item(item_id)
                except FileNotFoundError:
                    import json as _json

                    item = TurnItemRecord(
                        id=item_id,
                        turn_id=turn_id,
                        kind=TurnItemKind.TOOL_CALL,
                        status=TurnItemLifecycleStatus.IN_PROGRESS,
                        summary="request_user_input",
                        detail=_json.dumps({"questions": event.questions}),
                        started_at=now,
                    )
                    self.store.save_item(item)
                    self._attach_item_to_turn(turn_id, item_id)
                    await self._emit_event(
                        thread_id,
                        turn_id,
                        item_id,
                        "item.started",
                        {"item": item.model_dump(mode="json")},
                    )
                await self._emit_event(
                    thread_id, turn_id, None, "user_input.required",
                    {
                        "id": event.tool_call_id,
                        "request_id": event.tool_call_id,
                        "questions": event.questions,
                    },
                )

            elif isinstance(event, SubAgentMailboxEvent):
                import json as _json

                mailbox_payload = {
                    "seq": event.seq,
                    "message": _mailbox_message_payload(event.message),
                }
                now = datetime.now(timezone.utc)
                item_id = f"item_{uuid.uuid4().hex[:8]}"
                item = TurnItemRecord(
                    id=item_id,
                    turn_id=turn_id,
                    kind=TurnItemKind.STATUS,
                    status=TurnItemLifecycleStatus.COMPLETED,
                    summary=f"subagent:{event.message.agent_id}",
                    detail=_json.dumps(mailbox_payload, default=str),
                    metadata={"subagent_mailbox": True},
                    started_at=now,
                    ended_at=now,
                )
                self.store.save_item(item)
                self._attach_item_to_turn(turn_id, item_id)
                await self._emit_event(
                    thread_id,
                    turn_id,
                    None,
                    "subagent.mailbox",
                    mailbox_payload,
                )

            elif isinstance(event, ErrorEvent):
                turn_status = RuntimeTurnStatus.FAILED
                turn_error = event.message
                now = datetime.now(timezone.utc)
                item = TurnItemRecord(
                    id=f"item_{uuid.uuid4().hex[:8]}",
                    turn_id=turn_id,
                    kind=TurnItemKind.ERROR,
                    status=TurnItemLifecycleStatus.FAILED,
                    summary=summarize_text(event.message, SUMMARY_LIMIT),
                    detail=event.message,
                    started_at=now,
                    ended_at=now,
                )
                self.store.save_item(item)
                self._attach_item_to_turn(turn_id, item.id)
                await self._emit_event(
                    thread_id, turn_id, item.id, "item.failed",
                    {"item": item.model_dump(mode="json")},
                )

            elif isinstance(event, TurnCancelledEvent):
                turn_status = RuntimeTurnStatus.INTERRUPTED
                break

            elif isinstance(event, TurnCompleteEvent):
                if event.usage is not None:
                    u = event.usage
                    turn_usage = {
                        "prompt_tokens": u.input_tokens,
                        "completion_tokens": u.output_tokens,
                        "total_tokens": u.input_tokens + u.output_tokens,
                    }
                turn_status = RuntimeTurnStatus.COMPLETED
                turn_error = None
                break

        # Check if interrupt was requested
        async with self._active_lock:
            state = self._active.get(thread_id)
            if (
                state
                and state.active_turn
                and state.active_turn.turn_id == turn_id
                and state.active_turn.interrupt_requested
            ):
                turn_status = RuntimeTurnStatus.INTERRUPTED

        await self._finalize_orphan_tool_items(
            thread_id, turn_id, tool_items, turn_status
        )

        # Finalize any open reasoning item
        if current_reasoning_item_id is not None:
            item = self.store.load_item(current_reasoning_item_id)
            item.status = (
                TurnItemLifecycleStatus.INTERRUPTED
                if turn_status == RuntimeTurnStatus.INTERRUPTED
                else TurnItemLifecycleStatus.COMPLETED
            )
            item.summary = summarize_text(current_reasoning_text, SUMMARY_LIMIT)
            item.detail = current_reasoning_text
            item.ended_at = datetime.now(timezone.utc)
            self.store.save_item(item)
            event_name = (
                "item.interrupted"
                if item.status == TurnItemLifecycleStatus.INTERRUPTED
                else "item.completed"
            )
            await self._emit_event(
                thread_id, turn_id, current_reasoning_item_id, event_name,
                {"item": item.model_dump(mode="json")},
            )

        # Finalize any open message item
        if current_message_item_id is not None:
            item = self.store.load_item(current_message_item_id)
            item.status = (
                TurnItemLifecycleStatus.INTERRUPTED
                if turn_status == RuntimeTurnStatus.INTERRUPTED
                else TurnItemLifecycleStatus.COMPLETED
            )
            item.summary = summarize_text(current_message_text, SUMMARY_LIMIT)
            item.detail = current_message_text
            item.ended_at = datetime.now(timezone.utc)
            self.store.save_item(item)
            event_name = (
                "item.interrupted"
                if item.status == TurnItemLifecycleStatus.INTERRUPTED
                else "item.completed"
            )
            await self._emit_event(
                thread_id, turn_id, current_message_item_id, event_name,
                {"item": item.model_dump(mode="json")},
            )

        # Finalize the turn record
        ended_at = datetime.now(timezone.utc)
        turn = self.store.load_turn(turn_id)
        turn.status = turn_status
        turn.ended_at = ended_at
        if turn.started_at:
            turn.duration_ms = duration_ms(turn.started_at, ended_at)
        turn.usage = turn_usage
        turn.error = turn_error
        self.store.save_turn(turn)

        # Update thread
        thread = self.store.load_thread(thread_id)
        thread.latest_turn_id = turn_id
        thread.updated_at = datetime.now(timezone.utc)
        self.store.save_thread(thread)

        await self._emit_event(
            thread_id, turn_id, None, "turn.completed",
            {"turn": turn.model_dump(mode="json")},
        )

        # Clear active turn
        async with self._active_lock:
            state = self._active.get(thread_id)
            if (
                state
                and state.active_turn
                and state.active_turn.turn_id == turn_id
            ):
                state.active_turn = None
            self._touch_lru(thread_id)

    # --- helpers -------------------------------------------------------------

    def _attach_item_to_turn(self, turn_id: str, item_id: str) -> None:
        turn = self.store.load_turn(turn_id)
        if item_id not in turn.item_ids:
            turn.item_ids.append(item_id)
            self.store.save_turn(turn)

    async def _finalize_orphan_tool_items(
        self,
        thread_id: str,
        turn_id: str,
        tool_items: dict[str, str],
        turn_status: RuntimeTurnStatus,
    ) -> None:
        """Close tool items that never received a ToolResultEvent."""
        if not tool_items:
            return
        now = datetime.now(timezone.utc)
        if turn_status == RuntimeTurnStatus.INTERRUPTED:
            orphan_summary = "Tool interrupted"
            item_status = TurnItemLifecycleStatus.INTERRUPTED
            event_name = "item.interrupted"
        else:
            orphan_summary = "Turn ended before tool result"
            item_status = TurnItemLifecycleStatus.FAILED
            event_name = "item.failed"
        for item_id in list(tool_items.values()):
            try:
                item = self.store.load_item(item_id)
            except FileNotFoundError:
                continue
            if item.status is not TurnItemLifecycleStatus.IN_PROGRESS:
                continue
            item.status = item_status
            item.summary = summarize_text(
                f"{item.summary.replace(' started', '')} failed: {orphan_summary}",
                SUMMARY_LIMIT,
            )
            item.detail = orphan_summary
            item.ended_at = now
            self.store.save_item(item)
            await self._emit_event(
                thread_id,
                turn_id,
                item_id,
                event_name,
                {"item": item.model_dump(mode="json")},
            )
        tool_items.clear()

    async def _emit_event(
        self,
        thread_id: str,
        turn_id: str | None,
        item_id: str | None,
        event: str,
        payload: dict[str, Any],
    ) -> RuntimeEventRecord:
        record = await self.store.append_event(thread_id, turn_id, item_id, event, payload)
        self.event_bus.send(record)
        return record

    def _recover_interrupted_state(self) -> None:
        """On startup, mark any Queued/InProgress turns as Interrupted.

        Mirrors Rust ``recover_interrupted_state`` (line 2425-2468).
        """
        now = datetime.now(timezone.utc)
        for thread in self.store.list_threads():
            thread_changed = False
            for turn in self.store.list_turns_for_thread(thread.id):
                if turn.status not in (RuntimeTurnStatus.QUEUED, RuntimeTurnStatus.IN_PROGRESS):
                    continue
                turn.status = RuntimeTurnStatus.INTERRUPTED
                turn.error = RUNTIME_RESTART_REASON
                turn.ended_at = now
                if turn.started_at:
                    turn.duration_ms = duration_ms(turn.started_at, now)
                self.store.save_turn(turn)

                for item_id in turn.item_ids:
                    try:
                        item = self.store.load_item(item_id)
                    except FileNotFoundError:
                        continue
                    if item.status in (
                        TurnItemLifecycleStatus.QUEUED,
                        TurnItemLifecycleStatus.IN_PROGRESS,
                    ):
                        item.status = TurnItemLifecycleStatus.INTERRUPTED
                        item.ended_at = now
                        self.store.save_item(item)

                thread_changed = True

            if thread_changed:
                thread.updated_at = now
                self.store.save_thread(thread)
