"""Thread management and runtime threads.
"""

from __future__ import annotations



# RuntimeThreadManager — orchestrates Engine lifecycles for HTTP threads.
#
# Mirrors Rust ``RuntimeThreadManager`` (runtime_threads.rs:594-2488).
# Manages active engines, turn monitoring, LRU eviction, and restart recovery.
#
import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from typing import Generic, TypeVar

_T = TypeVar("_T")


class AsyncBroadcast(Generic[_T]):
    """Simple multi-consumer broadcast channel built on asyncio.Queue."""

    def __init__(self, capacity: int = 1024) -> None:
        self._capacity = capacity
        self._subscribers: set[asyncio.Queue[_T]] = set()

    def send(self, item: _T) -> int:
        count = 0
        lagged = 0
        dead: list[asyncio.Queue[_T]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(item)
                count += 1
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(item)
                    count += 1
                    lagged += 1
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    dead.append(q)
        for q in dead:
            self._subscribers.discard(q)
        return count

    def subscribe(self) -> asyncio.Queue[_T]:
        q: asyncio.Queue[_T] = asyncio.Queue(maxsize=self._capacity)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[_T]) -> None:
        self._subscribers.discard(q)

    @property
    def receiver_count(self) -> int:
        return len(self._subscribers)


from typing import TYPE_CHECKING as _TC_THR
if _TC_THR:
    from deepseek_tui.server.sessions import ImportTuiSessionRequest
from deepseek_tui.server.metrics import TurnDeltaBatcher
from deepseek_tui.server.metrics import (
    TurnLatencyTrace,
    bind_turn_latency,
    first_response_timeout_message,
    first_response_timeout_s,
    get_turn_latency,
    now_ms,
    pop_turn_latency,
)
from deepseek_tui.config.models import Config
from deepseek_tui.engine.events import (
    AgentRoundCompleteEvent,
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
    WorkflowProgressEvent,
)
from deepseek_tui.server.agent_segments import (
    AGENT_SEGMENT_KEY,
    FINAL_ANSWER,
    MID_TURN_PREFACE,
    REASONING_FALLBACK_NOTICE,
    extract_terminal_display_text,
)
from deepseek_tui.server.phase_bridge import (
    PHASE_BRIDGE_AFTER_REASONING_KEY,
    PHASE_BRIDGE_METADATA_KEY,
    BatchKind,
    ReasoningSegment,
    TurnNarrationState,
    classify_batch,
    compute_narration_display,
    decide_and_prepare,
    note_published,
    resolve_narration_locale,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.tools.subagent import MailboxMessage
from deepseek_tui.utils import summarize_text

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.engine.handle import ApprovalHandler

logger = logging.getLogger(__name__)

__all__ = ["RuntimeThreadManager"]


def _resolved_workspace_path(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


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
    __slots__ = ("handle", "engine", "engine_task", "active_turn", "provider")

    def __init__(
        self,
        handle: EngineHandle,
        engine: Engine,
        engine_task: asyncio.Task[None],
        provider: str = "deepseek",
    ) -> None:
        self.handle = handle
        self.engine = engine
        self.engine_task: asyncio.Task[None] = engine_task
        self.active_turn: _ActiveTurnState | None = None
        self.provider = provider


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
        shared_tool_runtime: Any | None = None,
    ) -> None:
        self.config = config
        self.workspace = workspace.resolve()
        self.manager_cfg = manager_cfg
        self.store = RuntimeThreadStore(manager_cfg.data_dir)
        self._llm_client = llm_client
        self._provider_clients: dict[str, LLMClient] = {}
        self._approval_bridge = approval_bridge
        self._elevation_bridge = elevation_bridge
        self._shared_tool_runtime = shared_tool_runtime

        self._active: dict[str, _ActiveThreadState] = {}
        self._lru: OrderedDict[str, None] = OrderedDict()
        self._active_lock = asyncio.Lock()
        self._engine_load_tasks: dict[
            str, asyncio.Task[tuple[EngineHandle, asyncio.Task[None]]]
        ] = {}
        self._pending_user_inputs: dict[str, _PendingUserInputRecord] = {}
        self._session_started_at = datetime.now(timezone.utc)

        self.event_bus: AsyncBroadcast[RuntimeEventRecord] = AsyncBroadcast(
            capacity=EVENT_CHANNEL_CAPACITY
        )
        self._cancel_event = asyncio.Event()
        self._mcp_warmup_task: asyncio.Task[None] | None = None

        self._recover_interrupted_state()
        self._schedule_mcp_warmup()

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
        for client in self._provider_clients.values():
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    asyncio.get_running_loop().create_task(close())
                except RuntimeError:
                    pass
        self._provider_clients.clear()
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
        workspace = (req.workspace or "").strip() or str(self.workspace)
        mode = (req.mode or "").strip() or "agent"
        allow_shell = req.allow_shell if req.allow_shell is not None else self.config.allow_shell
        trust_mode = req.trust_mode if req.trust_mode is not None else False
        auto_approve = req.auto_approve if req.auto_approve is not None else False

        thread = ThreadRecord(
            id=f"thr_{uuid.uuid4().hex[:8]}",
            created_at=now,
            updated_at=now,
            model=model,
            provider=(req.provider or self.config.provider).strip() or self.config.provider,
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
        from deepseek_tui.server.sessions import (
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
                workspace=(req.workspace or "").strip() or meta_workspace or str(self.workspace),
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

    async def append_automation_notice(
        self,
        thread_id: str,
        *,
        automation_name: str,
        summary: str,
    ) -> None:
        """Push a read-only STATUS item + SSE for automation delivery (no LLM)."""

        thread = self.store.load_thread(thread_id)
        now = datetime.now(timezone.utc)
        turn_id = thread.latest_turn_id
        if turn_id is None:
            turn_id = f"turn_{uuid.uuid4().hex[:8]}"
            turn = TurnRecord(
                id=turn_id,
                thread_id=thread_id,
                status=RuntimeTurnStatus.COMPLETED,
                input_summary=summarize_text(summary, SUMMARY_LIMIT),
                created_at=now,
                started_at=now,
                ended_at=now,
            )
            self.store.save_turn(turn)
            thread.latest_turn_id = turn_id

        item_id = f"item_{uuid.uuid4().hex[:8]}"
        header = f"[{automation_name}] "
        body = header + summary
        item = TurnItemRecord(
            id=item_id,
            turn_id=turn_id,
            kind=TurnItemKind.STATUS,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary=summarize_text(body, SUMMARY_LIMIT),
            detail=body,
            started_at=now,
            ended_at=now,
            metadata={"source": "automation_delivery"},
        )
        turn = self.store.load_turn(turn_id)
        if item_id not in turn.item_ids:
            turn.item_ids.append(item_id)
        self.store.save_item(item)
        self.store.save_turn(turn)
        thread.updated_at = now
        self.store.save_thread(thread)
        await self._emit_event(
            thread_id,
            turn_id,
            item_id,
            "automation.delivered",
            {"automation_name": automation_name, "summary": summary},
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

    async def get_thread_usage(
        self,
        thread_id: str,
        *,
        group_by: str = "thread",
    ) -> dict[str, Any]:
        if group_by != "thread":
            raise ValueError(f"unsupported usage grouping: {group_by}")
        self.store.load_thread(thread_id)
        turns = self.store.list_turns_for_thread(thread_id)
        live_usage: dict[str, Any] | None = None
        async with self._active_lock:
            state = self._active.get(thread_id)
            if (
                state is not None
                and state.active_turn is not None
            ):
                ledger = getattr(state.engine, "turn_usage_ledger", None)
                if ledger is not None and ledger.items:
                    live_usage = ledger.totals()
        return thread_usage_response(thread_id, turns, live_usage=live_usage)

    async def get_session_model_usage(self, *, scope: str = "session") -> dict[str, Any]:
        if scope != "session":
            raise ValueError(f"unsupported usage scope: {scope}")
        merged: dict[str, dict[str, Any]] = {}
        for thread in self.store.list_threads():
            fallback_model = thread.model or "deepseek-chat"
            for turn in self.store.list_turns_for_thread(thread.id):
                if turn.status != RuntimeTurnStatus.COMPLETED:
                    continue
                if turn.ended_at is not None and turn.ended_at < self._session_started_at:
                    continue
                if not isinstance(turn.usage, dict) or not turn.usage:
                    continue
                accumulate_model_usage_from_turn(
                    merged,
                    turn.usage,
                    fallback_model=fallback_model,
                )
        async with self._active_lock:
            for thread_id, state in self._active.items():
                if state.active_turn is None:
                    continue
                active_turn_id = state.active_turn.turn_id
                stored_turn = self.store.load_turn(active_turn_id)
                if stored_turn.status == RuntimeTurnStatus.COMPLETED:
                    continue
                ledger = getattr(state.engine, "turn_usage_ledger", None)
                if ledger is None or not ledger.items:
                    continue
                thread = self.store.load_thread(thread_id)
                accumulate_model_usage_from_turn(
                    merged,
                    ledger.totals(),
                    fallback_model=thread.model or "deepseek-chat",
                )
        return session_model_usage_response(merged)

    def _record_turn_model_usage(
        self,
        turn_usage: dict[str, Any] | None,
        *,
        fallback_model: str,
        turn_id: str | None = None,
        thread_id: str | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        if turn_id and thread_id and ended_at and turn_usage:
            from deepseek_tui.server.workbench_usage_ledger import record_turn_usage

            record_turn_usage(
                turn_id=turn_id,
                ended_at=ended_at,
                thread_id=thread_id,
                turn_usage=turn_usage,
                fallback_model=fallback_model,
            )

    async def get_thread_context_breakdown(self, thread_id: str) -> dict[str, int]:
        """Context window estimate for Workbench / HTTP clients.

        Uses the live engine when the thread is already loaded, including
        dynamically discovered MCP tools. Otherwise reconstructs messages from
        the store and estimates with the default tool registry for that mode.
        """
        from deepseek_tui.engine.context import estimate_context_breakdown
        from deepseek_tui.tools.registry import build_default_registry

        thread = self.store.load_thread(thread_id)
        active_engine = None
        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is not None:
                active_engine = state.engine
        if active_engine is not None:
            return await active_engine.context_breakdown_live(thread.model)

        messages = reconstruct_messages_from_turns(self.store, thread_id)
        workspace = _resolved_workspace_path(thread.workspace)
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

    async def fork_thread(
        self, thread_id: str, *, through_item_id: str | None = None
    ) -> ThreadRecord:
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

        # When ``through_item_id`` is given, resolve the cutoff turn and the
        # position of the item within that turn's ``item_ids``. The forked
        # thread then contains all turns before the cutoff turn (in full), the
        # cutoff turn truncated at and including that item, and nothing after.
        cutoff_turn_index: int | None = None
        if through_item_id is not None:
            for idx, turn in enumerate(source_turns):
                if through_item_id in turn.item_ids:
                    cutoff_turn_index = idx
                    break
            if cutoff_turn_index is None:
                raise ValueError(
                    f"through_item_id not found in thread: {through_item_id}"
                )

        last_cloned_turn_id: str | None = None
        for idx, source_turn in enumerate(source_turns):
            if cutoff_turn_index is not None and idx > cutoff_turn_index:
                break

            cloned_turn = source_turn.model_copy(
                update={
                    "id": f"turn_{uuid.uuid4().hex[:8]}",
                    "thread_id": forked.id,
                    "item_ids": [],
                }
            )
            self.store.save_turn(cloned_turn)

            if cutoff_turn_index is not None and idx == cutoff_turn_index:
                # Truncate at the cutoff item, iterating ``item_ids`` directly
                # so missing-on-disk items earlier in the turn cannot shift
                # the cutoff position.
                for source_item_id in source_turn.item_ids:
                    try:
                        item = self.store.load_item(source_item_id)
                    except FileNotFoundError:
                        continue
                    cloned_item = item.model_copy(
                        update={
                            "id": f"item_{uuid.uuid4().hex[:8]}",
                            "turn_id": cloned_turn.id,
                        }
                    )
                    self.store.save_item(cloned_item)
                    cloned_turn.item_ids.append(cloned_item.id)
                    if source_item_id == through_item_id:
                        break
            else:
                for item in self.store.list_items_for_turn(source_turn.id):
                    cloned_item = item.model_copy(
                        update={
                            "id": f"item_{uuid.uuid4().hex[:8]}",
                            "turn_id": cloned_turn.id,
                        }
                    )
                    self.store.save_item(cloned_item)
                    cloned_turn.item_ids.append(cloned_item.id)

            self.store.save_turn(cloned_turn)
            if cloned_turn.item_ids:
                last_cloned_turn_id = cloned_turn.id

        if last_cloned_turn_id is not None:
            forked.latest_turn_id = last_cloned_turn_id
            forked.updated_at = now
            self.store.save_thread(forked)

        event_payload: dict[str, Any] = {
            "thread": forked.model_dump(mode="json"),
            "source_thread_id": source.id,
        }
        if through_item_id is not None:
            event_payload["through_item_id"] = through_item_id
        await self._emit_event(
            forked.id,
            None,
            None,
            "thread.forked",
            event_payload,
        )
        return forked

    # --- turn lifecycle ------------------------------------------------------

    async def start_turn(self, thread_id: str, req: StartTurnRequest) -> TurnRecord:
        prompt = req.prompt.strip()
        if not prompt:
            raise ValueError("prompt is required")

        thread = self.store.load_thread(thread_id)
        provider = (req.provider or thread.provider or self.config.provider).strip()
        model = (req.model or thread.model).strip()
        effective_mode = (req.mode or thread.mode or "agent").strip() or "agent"
        turn_id = f"turn_{uuid.uuid4().hex[:8]}"
        timeout_s = first_response_timeout_s(effective_mode)
        trace = TurnLatencyTrace(
            turn_id=turn_id,
            mode=effective_mode,
            ui_submit_at_ms=req.ui_submit_at_ms,
            main_runtime_request_start_ms=req.main_runtime_request_start_ms,
            first_response_timeout_s=timeout_s,
        )
        bind_turn_latency(trace)

        handle, engine_task = await self._ensure_engine_loaded(thread, trace=trace)
        trace.runtime_turn_created_ms = now_ms()

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is not None and state.active_turn is not None:
                pop_turn_latency(turn_id)
                raise ValueError("Thread already has an active turn")
            if state is not None:
                if state.provider != provider:
                    client = self._get_llm_client(provider)
                    state.engine.client = client
                    state.engine.turn_loop.client = client
                    state.provider = provider
                state.engine.mode = effective_mode
                state.engine.tool_context.metadata["turn_latency_turn_id"] = turn_id

        now = datetime.now(timezone.utc)
        auto_approve = req.auto_approve if req.auto_approve is not None else thread.auto_approve
        trust_mode = req.trust_mode if req.trust_mode is not None else thread.trust_mode

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is None:
                pop_turn_latency(turn_id)
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

        user_item_id: str | None = None
        if not req.hidden:
            user_item_id = f"item_{uuid.uuid4().hex[:8]}"
            persisted_prompt = prompt
            user_item = TurnItemRecord(
                id=user_item_id,
                turn_id=turn_id,
                kind=TurnItemKind.USER_MESSAGE,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=summarize_text(persisted_prompt, SUMMARY_LIMIT),
                detail=persisted_prompt,
                started_at=now,
                ended_at=now,
            )
            turn.item_ids.append(user_item_id)
            self.store.save_item(user_item)
        self.store.save_turn(turn)

        thread.latest_turn_id = turn_id
        thread.provider = provider
        thread.model = model
        thread.updated_at = now
        self.store.save_thread(thread)

        await self._emit_event(
            thread_id, turn_id, None, "turn.started", {"turn": turn.model_dump(mode="json")}
        )
        if user_item_id is not None:
            await self._emit_event(
                thread_id, turn_id, user_item_id, "item.completed",
                {"item": user_item.model_dump(mode="json")},
            )

        monitor_task = asyncio.create_task(
            self._monitor_turn_safe(thread_id, turn_id, handle, effective_mode),
            name=f"monitor-{turn_id}",
        )

        from deepseek_tui.engine.handle import SendMessageOp

        await handle.send_op(
            SendMessageOp(
                content=prompt,
                model=model,
                hidden=req.hidden,
                internal_kind=req.internal_kind,
            )
        )
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

        if self._approval_bridge is not None:
            self._approval_bridge.cancel_for_thread(thread_id)

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

        persisted_prompt = prompt
        item = TurnItemRecord(
            id=f"item_{uuid.uuid4().hex[:8]}",
            turn_id=turn_id,
            kind=TurnItemKind.USER_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary=summarize_text(persisted_prompt, SUMMARY_LIMIT),
            detail=persisted_prompt,
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

        engine.turn_usage_ledger.reset()
        before_count = len(engine.session_messages)
        if before_count == 0:
            summary_text = "Nothing to compact — session is empty."
            engine.session_messages.clear()
        else:
            result = await engine._run_compaction(list(engine.session_messages))
            engine.session_messages[:] = result.messages
            if result.success:
                summary_text = (
                    f"Context compacted: {before_count} → {len(result.messages)} messages."
                )
            else:
                # Compaction failed (e.g. summary model returned empty).
                # Messages are unchanged; surface this so the user knows
                # /compact did nothing rather than silently appearing OK.
                summary_text = (
                    f"Compaction failed after {result.retries_used} retries — "
                    f"messages unchanged ({before_count} → {len(result.messages)}). "
                    f"See log for details; try again or run /clear."
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
        ledger_totals = engine.turn_usage_ledger.totals()
        if engine.turn_usage_ledger.items:
            turn.usage = ledger_totals
            self._record_turn_model_usage(
                turn.usage,
                fallback_model=thread.model or "deepseek-chat",
                turn_id=turn_id,
                thread_id=thread_id,
                ended_at=ended_at,
            )
            turn_cache_hit = ledger_totals.get("cache_hit_tokens", 0)
            turn_cache_miss = ledger_totals.get("cache_miss_tokens", 0)
            if turn_cache_hit > 0 or turn_cache_miss > 0:
                engine.session_cache_hit_total += turn_cache_hit
                engine.session_cache_miss_total += turn_cache_miss
            turn_cost_usd = ledger_totals.get("cost_usd")
            turn_cost_cny = ledger_totals.get("cost_cny")
            if isinstance(turn_cost_usd, (int, float)) and turn_cost_usd > 0:
                engine.session_cost_usd += float(turn_cost_usd)
            if isinstance(turn_cost_cny, (int, float)) and turn_cost_cny > 0:
                engine.session_cost_cny += float(turn_cost_cny)
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

    async def warmup_thread(self, thread_id: str) -> dict[str, Any]:
        """Pre-load a thread's Engine without starting a turn.

        Workbench calls this after a thread is selected/created so the first
        user message does not pay the full Engine.create cold path. The regular
        start_turn path still calls _ensure_engine_loaded, so this is only an
        opportunistic latency warmup.
        """
        started = now_ms()
        thread = self.store.load_thread(thread_id)
        await self._ensure_engine_loaded(thread)
        return {
            "thread_id": thread_id,
            "status": "ready",
            "elapsed_ms": max(0, now_ms() - started),
        }

    # --- events query --------------------------------------------------------

    def events_since(
        self, thread_id: str, since_seq: int | None = None
    ) -> list[RuntimeEventRecord]:
        return self.store.events_since(thread_id, since_seq)

    # --- engine loading + LRU ------------------------------------------------

    async def _ensure_engine_loaded(
        self, thread: ThreadRecord, *, trace: TurnLatencyTrace | None = None
    ) -> tuple[EngineHandle, asyncio.Task[None]]:
        if trace is not None:
            trace.engine_load_start_ms = now_ms()
        load_task: asyncio.Task[tuple[EngineHandle, asyncio.Task[None]]] | None = None
        owns_load_task = False
        async with self._active_lock:
            state = self._active.get(thread.id)
            if state is not None:
                self._sync_trust_mode(
                    state.engine, self._trust_mode_for_thread(thread, state)
                )
                state.engine.mode = (thread.mode or "agent").strip() or "agent"
                self._touch_lru(thread.id)
                if trace is not None:
                    trace.engine_load_cache_hit = True
                    trace.engine_load_end_ms = now_ms()
                return state.handle, state.engine_task
            load_task = self._engine_load_tasks.get(thread.id)
            if load_task is None:
                load_task = asyncio.create_task(
                    self._load_engine_for_thread(thread),
                    name=f"engine-load-{thread.id}",
                )
                self._engine_load_tasks[thread.id] = load_task
                owns_load_task = True

        if trace is not None:
            trace.engine_load_cache_hit = False
        try:
            handle, engine_task = await load_task
        finally:
            if owns_load_task:
                async with self._active_lock:
                    if self._engine_load_tasks.get(thread.id) is load_task:
                        self._engine_load_tasks.pop(thread.id, None)
        if trace is not None:
            trace.engine_load_end_ms = now_ms()
        return handle, engine_task

    async def _load_engine_for_thread(
        self, thread: ThreadRecord
    ) -> tuple[EngineHandle, asyncio.Task[None]]:
        from deepseek_tui.engine.orchestrator import Engine
        from deepseek_tui.policy.approval import exec_policy_for_config

        handle = EngineHandle()
        workspace = _resolved_workspace_path(thread.workspace)
        approval_handler = self._build_approval_handler(thread.id)
        shared_runtime = self._shared_tool_runtime
        shared_mcp = None
        if shared_runtime is not None:
            shared_mcp = getattr(shared_runtime, "mcp_manager", None)
        create_kwargs: dict[str, Any] = {
            "handle": handle,
            "client": self._get_llm_client(thread.provider),
            "config": self._config_for_provider(thread.provider, thread.model),
            "working_directory": workspace,
            "default_model": thread.model,
            "mode": (thread.mode or "agent").strip() or "agent",
            "task_data_dir": self.manager_cfg.task_data_dir,
            "start_mcp": False,
            "mcp_manager": shared_mcp,
            "approval_handler": approval_handler,
            "exec_policy": exec_policy_for_config(self.config),
        }
        if shared_runtime is not None:
            create_kwargs["tool_runtime"] = shared_runtime
        engine = await Engine.create(**create_kwargs)
        self._sync_trust_mode(engine, thread.trust_mode)
        self._sync_engine_session(engine, thread)
        engine.tool_context.metadata["runtime_thread_id"] = thread.id
        if self._elevation_bridge is not None:
            engine.tool_context.metadata["elevation_bridge"] = self._elevation_bridge
        engine_task = asyncio.create_task(engine.run(), name=f"engine-{thread.id}")

        async with self._active_lock:
            evicted = self._enforce_lru_capacity()
            self._active[thread.id] = _ActiveThreadState(
                handle=handle,
                engine=engine,
                engine_task=engine_task,
                provider=thread.provider,
            )
            self._touch_lru(thread.id)

        for evicted_tid, evicted_state in evicted:
            await evicted_state.handle.cancel(reason="lru_eviction")
            evicted_state.engine_task.cancel()

        return handle, engine_task

    def _sync_engine_session(self, engine: Engine, thread: ThreadRecord) -> None:
        """Hydrate Engine.session_messages from durable turn items."""
        messages = reconstruct_messages_from_turns(self.store, thread.id)
        if messages:
            engine.sync_session(messages, model=thread.model)

    def _build_approval_handler(self, thread_id: str) -> ApprovalHandler:
        from deepseek_tui.server.approval import (
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

    def _get_llm_client(self, provider: str | None = None) -> LLMClient:
        requested = (provider or self.config.provider).strip() or self.config.provider
        cached = getattr(self, "_provider_clients", {}).get(requested)
        if cached is not None:
            return cached
        if self._llm_client is not None and requested == self.config.provider:
            return self._llm_client
        from deepseek_tui.client.factory import build_llm_client

        if requested == self.config.provider:
            client = build_llm_client(self.config)
        else:
            client = build_llm_client(self._config_for_provider(requested))
        if not hasattr(self, "_provider_clients"):
            self._provider_clients = {}
        self._provider_clients[requested] = client
        return client

    def _config_for_provider(
        self, provider: str, model: str | None = None
    ) -> Config:
        requested = provider.strip() or self.config.provider
        provider_config = self.config.model_copy(deep=True)
        provider_config.provider = requested
        if requested != self.config.provider:
            provider_config.api_key = None
            provider_config.base_url = None
            provider_config.model = model
        elif model is not None:
            provider_config.model = model
        return provider_config

    def _touch_lru(self, thread_id: str) -> None:
        self._lru.pop(thread_id, None)
        self._lru[thread_id] = None

    def _enforce_lru_capacity(self) -> list[tuple[str, _ActiveThreadState]]:
        max_active = self.manager_cfg.max_active_threads
        evicted: list[tuple[str, _ActiveThreadState]] = []
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
                evicted.append((tid, state))
            self._lru.pop(tid, None)
            break
        return evicted

    # --- turn monitoring -----------------------------------------------------

    async def _turn_first_response_watchdog(
        self,
        handle: EngineHandle,
        first_response: asyncio.Event,
        timeout_s: float,
        turn_id: str,
    ) -> None:
        """Cancel the turn if the model emits no content within ``timeout_s``."""
        from deepseek_tui.engine.events import TurnCancelledEvent

        try:
            await asyncio.wait_for(first_response.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            trace = get_turn_latency(turn_id)
            if trace is not None:
                trace.timeout_reason = "first_response_timeout"
            logger.warning(
                "turn_first_response_timeout turn_id=%s after=%.0fs mode=%s",
                turn_id,
                timeout_s,
                trace.mode if trace else "?",
            )
            await handle.cancel("first_response_timeout")
            try:
                await asyncio.wait_for(first_response.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.error(
                    "turn_first_response_force_fail turn_id=%s reason=first_response_timeout",
                    turn_id,
                )
                await handle.inject_event(
                    TurnCancelledEvent(reason="first_response_timeout")
                )

    async def _monitor_turn_safe(
        self,
        thread_id: str,
        turn_id: str,
        handle: EngineHandle,
        mode: str,
    ) -> None:
        try:
            await self._monitor_turn(thread_id, turn_id, handle, mode)
        except Exception as exc:
            logger.exception("Turn monitor failed for %s: %s", turn_id, exc)
            try:
                await self._finalize_turn_after_monitor_crash(
                    thread_id, turn_id, handle
                )
            except Exception:
                logger.exception(
                    "Turn monitor recovery failed for %s", turn_id
                )
        finally:
            pop_turn_latency(turn_id)

    async def _finalize_turn_after_monitor_crash(
        self,
        thread_id: str,
        turn_id: str,
        handle: EngineHandle,
    ) -> None:
        """Drain engine events until terminal so UI is not stuck in_progress."""
        turn_status = RuntimeTurnStatus.FAILED
        turn_error = "Turn monitor crashed"
        turn_usage: dict[str, Any] | None = None

        async for event in handle.events():
            if isinstance(event, TurnCompleteEvent):
                turn_status = RuntimeTurnStatus.COMPLETED
                turn_error = None
                thread_model = self.store.load_thread(thread_id).model or "deepseek-chat"
                async with self._active_lock:
                    engine = self._active.get(thread_id)
                    active_engine = engine.engine if engine is not None else None
                turn_usage = turn_usage_from_engine_or_event(
                    engine=active_engine,
                    event=event,
                    model=thread_model,
                )
                break
            if isinstance(event, TurnCancelledEvent):
                turn_status = RuntimeTurnStatus.INTERRUPTED
                turn_error = None
                break
            if isinstance(event, ErrorEvent):
                turn_status = RuntimeTurnStatus.FAILED
                turn_error = event.message
                break

        ended_at = datetime.now(timezone.utc)
        turn = self.store.load_turn(turn_id)
        if turn.status not in (
            RuntimeTurnStatus.QUEUED,
            RuntimeTurnStatus.IN_PROGRESS,
        ):
            return

        turn.status = turn_status
        turn.ended_at = ended_at
        if turn.started_at:
            turn.duration_ms = duration_ms(turn.started_at, ended_at)
        turn.usage = turn_usage
        turn.error = turn_error
        if turn_usage is not None:
            thread_for_usage = self.store.load_thread(thread_id)
            self._record_turn_model_usage(
                turn_usage,
                fallback_model=thread_for_usage.model or "deepseek-chat",
                turn_id=turn_id,
                thread_id=thread_id,
                ended_at=ended_at,
            )
        self.store.save_turn(turn)

        thread = self.store.load_thread(thread_id)
        thread.latest_turn_id = turn_id
        thread.updated_at = ended_at
        self.store.save_thread(thread)

        await self._emit_event(
            thread_id,
            turn_id,
            None,
            "turn.completed",
            {
                "turn": turn.model_dump(mode="json"),
                **(
                    {"latency_trace": latency_payload}
                    if (latency_payload := self._finalize_turn_latency(turn_id))
                    else {}
                ),
            },
            force_checkpoint=True,
        )

        async with self._active_lock:
            state = self._active.get(thread_id)
            if (
                state
                and state.active_turn
                and state.active_turn.turn_id == turn_id
            ):
                state.active_turn = None
            self._touch_lru(thread_id)

    async def _emit_item_delta(
        self,
        thread_id: str,
        turn_id: str,
        item_id: str,
        payload: dict[str, Any],
    ) -> None:
        trace = get_turn_latency(turn_id)
        if trace is not None and trace.runtime_first_delta_emitted_ms is None:
            trace.runtime_first_delta_emitted_ms = now_ms()
        if trace is not None:
            trace.delta_events_emitted += 1
        await self._emit_event(
            thread_id, turn_id, item_id, "item.delta", payload
        )

    async def _persist_subagent_mailbox(
        self,
        thread_id: str,
        turn_id: str,
        seq: int,
        message: MailboxMessage,
    ) -> None:
        """Persist one sub-agent mailbox envelope and stream it to the UI."""
        import json as _json

        mailbox_payload = {
            "seq": seq,
            "message": _mailbox_message_payload(message),
        }
        now = datetime.now(timezone.utc)
        item_id = f"item_{uuid.uuid4().hex[:8]}"
        item = TurnItemRecord(
            id=item_id,
            turn_id=turn_id,
            kind=TurnItemKind.STATUS,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary=f"subagent:{message.agent_id}",
            detail=_json.dumps(mailbox_payload, default=str),
            metadata={"subagent_mailbox": True},
            started_at=now,
            ended_at=now,
        )
        self.store.save_item(item)
        self._attach_item_to_turn(turn_id, item_id)
        await self._emit_event(
            thread_id, turn_id, None, "subagent.mailbox", mailbox_payload
        )

    async def _flush_pending_subagent_mailbox(
        self,
        thread_id: str,
        turn_id: str,
        engine: Engine | None,
        skip_ids: set[str] | None = None,
    ) -> None:
        """Drain any sub-agent mailbox events the activity coordinator has not
        consumed yet before the turn closes.

        A sub-agent flips its status to terminal and ``manager.wait`` returns
        (0.05s poll) before the coordinator's next 0.4s mailbox drain, so the
        turn can complete with the terminal ``completed``/``failed`` envelope
        still queued. Without this flush that envelope is never persisted and the
        card is reconstructed stuck at "running" forever.
        """
        if engine is None:
            return
        # Prefer the engine-owned manager's mailbox: with a shared
        # ToolRuntime each engine has its own manager + mailbox, and the
        # shared runtime.mailbox belongs to no thread in particular.
        mailbox = None
        mgr = engine.tool_context.subagent_manager
        if mgr is not None and mgr.mailbox is not None:
            mailbox = mgr.mailbox
        else:
            runtime = getattr(engine, "tool_runtime", None)
            if runtime is not None:
                mailbox = getattr(runtime, "mailbox", None)
        if mailbox is None:
            return
        try:
            envelopes = await mailbox.drain_available()
        except Exception:  # noqa: BLE001 — best-effort flush at turn close
            return
        for envelope in envelopes:
            if skip_ids and envelope.message.agent_id in skip_ids:
                continue  # leftover from a prior turn — do not leak its card
            await self._persist_subagent_mailbox(
                thread_id, turn_id, envelope.seq, envelope.message
            )

    async def _cancel_orphan_subagents(
        self,
        thread_id: str,
        turn_id: str,
        engine: Engine | None,
        agent_ids: set[str],
    ) -> None:
        """Cancel this turn's sub-agents that are still running at turn close.

        Sub-agents are in-turn entities and must not outlive the turn that
        spawned them. When the main agent ends the turn without awaiting them
        (premature completion), the orphans keep running on the shared
        per-engine manager and bleed their mailbox envelopes into the next
        turn. Cancelling here scopes each turn's sub-agents to that turn: the
        card lands as ``cancelled`` under the owning turn (honestly exposing
        the missing wait) and no stale work survives into the next turn.

        Idempotent: agents already terminal are skipped, so a turn that
        properly awaited everything cancels nothing.
        """
        if engine is None or not agent_ids:
            return
        from deepseek_tui.tools.subagent import SubAgentStatusKind

        manager = engine.tool_context.subagent_manager
        if manager is None:
            return
        for agent_id in agent_ids:
            try:
                snap = await manager.get_result(agent_id)
            except Exception:  # noqa: BLE001 — unknown/evicted agent
                continue
            if snap.status.kind is not SubAgentStatusKind.RUNNING:
                continue
            try:
                await manager.cancel(agent_id)
            except Exception:  # noqa: BLE001 — best-effort cleanup at turn close
                continue

    async def _reconcile_subagent_cards(
        self,
        thread_id: str,
        turn_id: str,
        engine: Engine | None,
        agent_ids: set[str],
    ) -> None:
        """Re-assert terminal state for every sub-agent touched this turn.

        Live ``subagent.mailbox`` events ride ``handle.try_emit``, which drops
        silently when the shared event queue saturates under a busy turn. A
        dropped terminal envelope leaves the card stuck at "running". Draining
        the mailbox cannot recover an already-dropped event, so at turn close we
        read the authoritative manager snapshot and re-emit a terminal envelope
        for any agent that is done. Idempotent (re-applying ``completed`` is a
        no-op on the card) and scoped to this turn's agents, so it never leaks a
        stray card into another turn.
        """
        if engine is None or not agent_ids:
            return
        from deepseek_tui.tools.subagent import (
            _MAX_CARD_RESULT_CHARS,
            MailboxMessage,
            SubAgentStatusKind,
        )

        manager = engine.tool_context.subagent_manager
        if manager is None:
            return
        for agent_id in agent_ids:
            try:
                snap = await manager.get_result(agent_id)
            except Exception:  # noqa: BLE001 — unknown/evicted agent
                continue
            kind = snap.status.kind
            if kind is SubAgentStatusKind.RUNNING:
                continue
            if kind is SubAgentStatusKind.COMPLETED:
                summary = (snap.result or "").strip()[:_MAX_CARD_RESULT_CHARS]
                message = MailboxMessage.completed(agent_id, summary)
            elif kind is SubAgentStatusKind.CANCELLED:
                message = MailboxMessage.cancelled(agent_id)
            else:
                message = MailboxMessage.failed(
                    agent_id, snap.status.message or "failed"
                )
            await self._persist_subagent_mailbox(thread_id, turn_id, 0, message)

    async def _monitor_turn(
        self,
        thread_id: str,
        turn_id: str,
        handle: EngineHandle,
        mode: str,
    ) -> None:
        """Consume engine events and persist turn items + runtime events.

        Mirrors Rust ``monitor_turn`` (line 1641-2373).
        """
        current_message_text = ""
        current_message_item_id: str | None = None
        current_reasoning_item_id: str | None = None
        current_reasoning_text = ""
        tool_items: dict[str, str] = {}  # tool_call_id -> item_id
        workflow_items: dict[str, str] = {}  # tool_call_id -> item_id (workflow progress)
        tool_call_args: dict[str, Any] = {}  # tool_call_id -> raw arguments
        seen_subagent_ids: set[str] = set()  # agents touched this turn (for reconcile)
        turn_status = RuntimeTurnStatus.COMPLETED
        turn_error: str | None = None
        turn_usage: dict[str, Any] | None = None
        first_response = asyncio.Event()
        timeout_s = first_response_timeout_s(mode)
        delta_batcher = TurnDeltaBatcher(
            thread_id,
            turn_id,
            lambda tid, tuid, iid, kind, payload: self._emit_item_delta(
                tid, tuid, iid, payload
            ),
        )
        tool_call_started_ms: dict[str, int] = {}
        approval_pending_ms: dict[str, int] = {}
        last_completed_reasoning: ReasoningSegment | None = None
        narrated_reasoning_ids: set[str] = set()
        narration_state = TurnNarrationState()
        narration_compute_tasks: list[asyncio.Task[None]] = []
        recent_tool_summaries: list[str] = []
        recent_tool_had_error = False
        turn_input_summary = self.store.load_turn(turn_id).input_summary
        narration_cfg = self.config.ui.process_narration
        narration_locale = resolve_narration_locale(
            turn_input_summary,
            config_locale=self.config.ui.locale,
        )

        async def persist_segment_narration(
            segment: ReasoningSegment,
            text: str,
            batch_kind: BatchKind,
            tool_calls: tuple,
        ) -> None:
            await self._persist_phase_bridge(thread_id, turn_id, segment, text)
            note_published(
                narration_state,
                text,
                batch=batch_kind,
                tool_calls=tool_calls,
            )

        async def flush_narration_tasks(*, wait_remaining: bool = False) -> None:
            nonlocal narration_compute_tasks
            still: list[asyncio.Task[None]] = []
            for task in narration_compute_tasks:
                if not task.done():
                    if wait_remaining:
                        try:
                            await asyncio.wait_for(task, timeout=narration_cfg.turn_wait_s)
                        except (asyncio.TimeoutError, asyncio.CancelledError):
                            if not task.done():
                                task.cancel()
                    if not task.done():
                        still.append(task)
                        continue
                try:
                    task.result()
                except Exception:
                    logger.exception(
                        "phase_bridge compute failed turn=%s task=%s",
                        turn_id,
                        task.get_name(),
                    )
            narration_compute_tasks = still

        async def finalize_open_reasoning() -> ReasoningSegment | None:
            nonlocal current_reasoning_item_id, current_reasoning_text, last_completed_reasoning
            if current_reasoning_item_id is None:
                return last_completed_reasoning
            await flush_delta_batch()
            item = self.store.load_item(current_reasoning_item_id)
            item.status = TurnItemLifecycleStatus.COMPLETED
            item.summary = summarize_text(current_reasoning_text, SUMMARY_LIMIT)
            item.detail = current_reasoning_text
            item.ended_at = datetime.now(timezone.utc)
            self.store.save_item(item)
            await self._emit_event(
                thread_id,
                turn_id,
                current_reasoning_item_id,
                "item.completed",
                {"item": item.model_dump(mode="json")},
            )
            segment = ReasoningSegment(
                item_id=current_reasoning_item_id,
                text=current_reasoning_text,
            )
            last_completed_reasoning = segment
            current_reasoning_item_id = None
            current_reasoning_text = ""
            return segment

        async def finalize_open_message(
            *,
            agent_segment: str | None = None,
            status: TurnItemLifecycleStatus | None = None,
        ) -> None:
            nonlocal current_message_item_id, current_message_text
            if current_message_item_id is None:
                return
            await flush_delta_batch()
            item = self.store.load_item(current_message_item_id)
            if agent_segment:
                base_meta = item.metadata if isinstance(item.metadata, dict) else {}
                item.metadata = {**base_meta, AGENT_SEGMENT_KEY: agent_segment}
            item.status = status or TurnItemLifecycleStatus.COMPLETED
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
                thread_id,
                turn_id,
                current_message_item_id,
                event_name,
                {"item": item.model_dump(mode="json")},
            )
            current_message_item_id = None
            current_message_text = ""

        async def promote_reasoning_to_final_answer(
            segment: ReasoningSegment,
            display_text: str,
        ) -> None:
            item = self.store.load_item(segment.item_id)
            base_meta = item.metadata if isinstance(item.metadata, dict) else {}
            item.kind = TurnItemKind.AGENT_MESSAGE
            item.status = TurnItemLifecycleStatus.COMPLETED
            item.detail = display_text
            item.summary = summarize_text(display_text, SUMMARY_LIMIT)
            item.metadata = {**base_meta, AGENT_SEGMENT_KEY: FINAL_ANSWER}
            item.ended_at = datetime.now(timezone.utc)
            self.store.save_item(item)
            await self._emit_event(
                thread_id,
                turn_id,
                segment.item_id,
                "item.completed",
                {"item": item.model_dump(mode="json")},
            )

        async def persist_final_answer_message(*, text: str) -> None:
            nonlocal current_message_item_id, current_message_text
            cleaned = text.strip()
            if not cleaned:
                return
            now = datetime.now(timezone.utc)
            if current_message_item_id is not None:
                item = self.store.load_item(current_message_item_id)
                base_meta = item.metadata if isinstance(item.metadata, dict) else {}
                item.kind = TurnItemKind.AGENT_MESSAGE
                item.status = TurnItemLifecycleStatus.COMPLETED
                item.detail = cleaned
                item.summary = summarize_text(cleaned, SUMMARY_LIMIT)
                item.metadata = {**base_meta, AGENT_SEGMENT_KEY: FINAL_ANSWER}
                item.ended_at = now
                item_id = current_message_item_id
            else:
                item_id = f"item_{uuid.uuid4().hex[:8]}"
                item = TurnItemRecord(
                    id=item_id,
                    turn_id=turn_id,
                    kind=TurnItemKind.AGENT_MESSAGE,
                    status=TurnItemLifecycleStatus.COMPLETED,
                    summary=summarize_text(cleaned, SUMMARY_LIMIT),
                    detail=cleaned,
                    metadata={AGENT_SEGMENT_KEY: FINAL_ANSWER},
                    started_at=now,
                    ended_at=now,
                )
                self.store.save_item(item)
                self._attach_item_to_turn(turn_id, item_id)
            self.store.save_item(item)
            await self._emit_event(
                thread_id,
                turn_id,
                item_id,
                "item.completed",
                {"item": item.model_dump(mode="json")},
            )
            current_message_item_id = None
            current_message_text = ""

        def schedule_phase_bridge(
            segment: ReasoningSegment, round_event: AgentRoundCompleteEvent
        ) -> None:
            nonlocal last_completed_reasoning
            if not narration_cfg.enabled:
                return
            tool_calls = round_event.tool_calls
            batch_kind = classify_batch(tool_calls)
            decision, immediate = decide_and_prepare(
                state=narration_state,
                segment=segment,
                tool_calls=tool_calls,
                preface_text=round_event.preface_text,
                narrated_ids=narrated_reasoning_ids,
                min_chars=narration_cfg.min_chars,
                has_tool_error=recent_tool_had_error,
                pending_scheduled=len(narration_compute_tasks),
                locale=narration_locale,
                max_published=narration_cfg.max_per_turn,
            )
            if decision == "skip":
                logger.debug(
                    "phase_bridge skip turn=%s reasoning=%s batch=%s",
                    turn_id,
                    segment.item_id,
                    batch_kind.value,
                )
                return
            narrated_reasoning_ids.add(segment.item_id)
            last_completed_reasoning = None
            tc_tuple = tuple(tool_calls)

            if decision == "use_preface" and immediate:
                # The model already narrated this batch in its own words; surface
                # it directly instead of regenerating via the flash model.
                preface_line = immediate

                async def persist_preface() -> None:
                    await persist_segment_narration(
                        segment, preface_line, batch_kind, tc_tuple
                    )

                narration_compute_tasks.append(
                    asyncio.create_task(
                        persist_preface(),
                        name=f"phase-bridge-preface-{segment.item_id}",
                    )
                )
                return

            recent = recent_tool_summaries[-narration_cfg.include_recent_tool_results :]

            async def run_and_persist() -> None:
                try:
                    text = await self._compute_phase_bridge(
                        thread_id=thread_id,
                        user_prompt=turn_input_summary,
                        state=narration_state,
                        segment=segment,
                        tool_calls=tool_calls,
                        recent_tool_results=recent,
                        locale=narration_locale,
                    )
                except Exception:
                    logger.exception(
                        "phase_bridge compute failed turn=%s reasoning=%s",
                        turn_id,
                        segment.item_id,
                    )
                    return
                if text:
                    await persist_segment_narration(segment, text, batch_kind, tc_tuple)

            task = asyncio.create_task(
                run_and_persist(), name=f"phase-bridge-{segment.item_id}"
            )
            narration_compute_tasks.append(task)

        def note_tool_result_timing(tool_call_id: str) -> None:
            trace = get_turn_latency(turn_id)
            if trace is None:
                return
            end = now_ms()
            started = tool_call_started_ms.pop(tool_call_id, None)
            approval_start = approval_pending_ms.pop(tool_call_id, None)
            if started is None:
                return
            if approval_start is not None:
                trace.note_approval_wait(end - approval_start)
            # Tool execution wall clock is captured per-round by the
            # orchestrator (round_trace.tool_exec_ms). Per-call tracking here
            # double-counted parallel tool batches, so it is intentionally
            # not recorded.

        async def flush_delta_batch() -> None:
            emitted = await delta_batcher.flush()
            if emitted:
                await self.store.flush_event_checkpoint()

        watchdog = asyncio.create_task(
            self._turn_first_response_watchdog(
                handle, first_response, timeout_s, turn_id
            ),
            name=f"turn-watchdog-{turn_id}",
        )

        # Sub-agents are in-turn entities: any agent already tracked when this
        # turn starts belongs to a prior turn (turns are serial per thread). If
        # such an orphan keeps emitting after its turn ended, this monitor must
        # not re-attribute those envelopes to the new turn (which would leak a
        # stray card with a lost agent_type). Tag them foreign and drop them.
        foreign_subagent_ids: set[str] = set()
        async with self._active_lock:
            _state = self._active.get(thread_id)
            _engine = _state.engine if _state is not None else None
        if _engine is not None:
            _mgr = _engine.tool_context.subagent_manager
            _known = getattr(_mgr, "known_agent_ids", None)
            if callable(_known):
                foreign_subagent_ids = _known()

        async for event in handle.events():
            if self._cancel_event.is_set():
                turn_status = RuntimeTurnStatus.INTERRUPTED
                break

            if isinstance(event, TurnStartedEvent):
                await flush_delta_batch()
                await self._emit_event(
                    thread_id, turn_id, None, "turn.lifecycle", {"status": "in_progress"}
                )

            elif isinstance(event, TextDeltaEvent):
                first_response.set()
                if current_reasoning_item_id is not None:
                    await finalize_open_reasoning()

                if current_message_item_id is None:
                    await flush_delta_batch()
                    item_id = f"item_{uuid.uuid4().hex[:8]}"
                    now = datetime.now(timezone.utc)
                    item = TurnItemRecord(
                        id=item_id,
                        turn_id=turn_id,
                        kind=TurnItemKind.AGENT_MESSAGE,
                        status=TurnItemLifecycleStatus.IN_PROGRESS,
                        summary="",
                        detail="",
                        metadata={AGENT_SEGMENT_KEY: MID_TURN_PREFACE},
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
                await delta_batcher.append(
                    current_message_item_id, "agent_message", event.text
                )

            elif isinstance(event, ThinkingDeltaEvent):
                first_response.set()
                if current_reasoning_item_id is None:
                    last_completed_reasoning = None
                    await flush_delta_batch()
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
                await delta_batcher.append(
                    current_reasoning_item_id, "agent_reasoning", event.thinking
                )

            elif isinstance(event, ToolCallEvent):
                await flush_delta_batch()
                first_response.set()
                if current_reasoning_item_id is not None:
                    await finalize_open_reasoning()
                await finalize_open_message(agent_segment=MID_TURN_PREFACE)
                tc = event.tool_call
                tool_call_started_ms[tc.id] = now_ms()
                item_id = f"item_{uuid.uuid4().hex[:8]}"
                tool_items[tc.id] = item_id
                tool_call_args[tc.id] = tc.arguments
                kind = tool_kind_for_name(tc.name)
                now = datetime.now(timezone.utc)
                metadata = tool_started_metadata(tc.name, tc.arguments)
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
                note_tool_result_timing(event.tool_call_id)
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
                        recent_tool_had_error = True
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
                    task_refreshed = task_tool_metadata_from_result(
                        event.tool_name,
                        tool_args,
                        event.metadata,
                        item.metadata if isinstance(item.metadata, dict) else None,
                    )
                    if task_refreshed:
                        item.metadata = {**item.metadata, **task_refreshed}
                    self.store.save_item(item)
                    if event.success and item.summary:
                        recent_tool_summaries.append(item.summary)
                        keep = narration_cfg.include_recent_tool_results * 3
                        if len(recent_tool_summaries) > keep:
                            del recent_tool_summaries[:-keep]
                    event_name = (
                        "item.completed" if item.status == TurnItemLifecycleStatus.COMPLETED
                        else "item.failed"
                    )
                    await self._emit_event(
                        thread_id, turn_id, item_id, event_name,
                        {"item": item.model_dump(mode="json")},
                    )

            elif isinstance(event, ApprovalRequiredEvent):
                from deepseek_tui.tools.approval import (
                    approval_request_to_sse_payload,
                )

                approval_id = event.tool_call_id
                approval_pending_ms[approval_id] = now_ms()
                await self._emit_event(
                    thread_id,
                    turn_id,
                    None,
                    "approval.required",
                    approval_request_to_sse_payload(approval_id, event.request),
                )

            elif isinstance(event, ElevationRequiredEvent):
                from deepseek_tui.tools.approval import (
                    elevation_request_to_sse_payload,
                )

                approval_pending_ms[event.tool_call_id] = now_ms()
                await self._emit_event(
                    thread_id,
                    turn_id,
                    None,
                    "elevation.required",
                    elevation_request_to_sse_payload(event.tool_call_id, event),
                )

            elif isinstance(event, WorkflowProgressEvent):
                import json as _json

                from deepseek_tui.workflow.models import WorkflowSnapshot
                from deepseek_tui.workflow.models import snapshot_to_dict

                snap = event.snapshot
                snapshot_payload = (
                    snapshot_to_dict(snap)
                    if isinstance(snap, WorkflowSnapshot)
                    else snap
                )
                payload = {
                    "tool_call_id": event.tool_call_id,
                    "workflow_name": event.workflow_name,
                    "snapshot": snapshot_payload,
                    "completed": event.completed,
                    "status": event.status,
                }
                item_id = workflow_items.get(event.tool_call_id)
                now = datetime.now(timezone.utc)
                if item_id is None:
                    item_id = f"item_{uuid.uuid4().hex[:8]}"
                    workflow_items[event.tool_call_id] = item_id
                    item = TurnItemRecord(
                        id=item_id,
                        turn_id=turn_id,
                        kind=TurnItemKind.STATUS,
                        status=TurnItemLifecycleStatus.IN_PROGRESS,
                        summary=f"workflow:{event.workflow_name}",
                        detail=_json.dumps(payload, default=str),
                        metadata={"workflow_progress": True},
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
                else:
                    item = self.store.load_item(item_id)
                    item.detail = _json.dumps(payload, default=str)
                    if event.completed:
                        if event.status == "failed":
                            item.status = TurnItemLifecycleStatus.FAILED
                        elif event.status == "cancelled":
                            item.status = TurnItemLifecycleStatus.CANCELED
                        else:
                            item.status = TurnItemLifecycleStatus.COMPLETED
                        item.ended_at = now
                    self.store.save_item(item)
                await self._emit_event(
                    thread_id,
                    turn_id,
                    item_id,
                    "workflow.progress",
                    payload,
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
                if event.message.agent_id in foreign_subagent_ids:
                    continue  # leftover from a prior turn — do not leak its card
                seen_subagent_ids.add(event.message.agent_id)
                await self._persist_subagent_mailbox(
                    thread_id, turn_id, event.seq, event.message
                )

            elif isinstance(event, ErrorEvent):
                await flush_delta_batch()
                first_response.set()
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
                await flush_delta_batch()
                if event.reason == "first_response_timeout":
                    trace = get_turn_latency(turn_id)
                    if trace is not None:
                        trace.timeout_reason = event.reason
                    turn_status = RuntimeTurnStatus.FAILED
                    turn_error = first_response_timeout_message(trace)
                else:
                    turn_status = RuntimeTurnStatus.INTERRUPTED
                break

            elif isinstance(event, AgentRoundCompleteEvent):
                segment = await finalize_open_reasoning()
                if not event.tool_calls:
                    last_completed_reasoning = None
                    display, is_raw_fallback = extract_terminal_display_text(
                        text=event.preface_text,
                        thinking=event.round_thinking,
                    )
                    preface = (event.preface_text or "").strip()
                    # Raw reasoning fallback: the round produced no answer
                    # `content` AND the thinking doesn't use the
                    # "(reasoning omitted)" protocol. This typically means the
                    # output budget was too small and reasoning was
                    # length-truncated before the model could emit its answer.
                    # Prepend a visible notice so it isn't mistaken for a clean
                    # reply (see max_output_tokens_for_model).
                    if display and is_raw_fallback:
                        logger.warning(
                            "terminal_reasoning_fallback turn=%s thinking_chars=%d "
                            "— no answer content, showing reasoning as final answer",
                            turn_id,
                            len(display),
                        )
                        display = f"{REASONING_FALLBACK_NOTICE}\n\n{display}"
                    if display and segment is not None and not preface:
                        await promote_reasoning_to_final_answer(segment, display)
                    elif display and current_message_item_id is not None:
                        await finalize_open_message(agent_segment=FINAL_ANSWER)
                    elif display:
                        await persist_final_answer_message(text=display)
                    else:
                        await finalize_open_message(agent_segment=FINAL_ANSWER)
                else:
                    await finalize_open_message(agent_segment=MID_TURN_PREFACE)
                    segment = segment or last_completed_reasoning
                    if segment is not None:
                        schedule_phase_bridge(segment, event)
                await flush_narration_tasks()

            elif isinstance(event, TurnCompleteEvent):
                await flush_delta_batch()
                first_response.set()
                thread_model = self.store.load_thread(thread_id).model or "deepseek-chat"
                async with self._active_lock:
                    engine = self._active.get(thread_id)
                    active_engine = engine.engine if engine is not None else None
                await self._cancel_orphan_subagents(
                    thread_id, turn_id, active_engine, seen_subagent_ids
                )
                await self._flush_pending_subagent_mailbox(
                    thread_id, turn_id, active_engine, skip_ids=foreign_subagent_ids
                )
                await self._reconcile_subagent_cards(
                    thread_id, turn_id, active_engine, seen_subagent_ids
                )
                turn_usage = turn_usage_from_engine_or_event(
                    engine=active_engine,
                    event=event,
                    model=thread_model,
                )
                turn_status = RuntimeTurnStatus.COMPLETED
                turn_error = None
                break

        watchdog.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass

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
        await self._finalize_orphan_workflow_items(
            thread_id, turn_id, workflow_items, turn_status
        )

        await flush_narration_tasks(wait_remaining=True)

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
            orphan_segment = (
                FINAL_ANSWER
                if turn_status == RuntimeTurnStatus.COMPLETED
                else None
            )
            orphan_status = (
                TurnItemLifecycleStatus.INTERRUPTED
                if turn_status == RuntimeTurnStatus.INTERRUPTED
                else None
            )
            await finalize_open_message(
                agent_segment=orphan_segment,
                status=orphan_status,
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
        if turn_usage is not None:
            thread_for_usage = self.store.load_thread(thread_id)
            self._record_turn_model_usage(
                turn_usage,
                fallback_model=thread_for_usage.model or "deepseek-chat",
                turn_id=turn_id,
                thread_id=thread_id,
                ended_at=ended_at,
            )
        self.store.save_turn(turn)

        # Update thread
        thread = self.store.load_thread(thread_id)
        thread.latest_turn_id = turn_id
        thread.updated_at = datetime.now(timezone.utc)
        self.store.save_thread(thread)

        await self._emit_event(
            thread_id, turn_id, None, "turn.completed",
            {
                "turn": turn.model_dump(mode="json"),
                **(
                    {"latency_trace": latency_payload}
                    if (latency_payload := self._finalize_turn_latency(turn_id))
                    else {}
                ),
            },
            force_checkpoint=True,
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

    def _insert_turn_item_after(self, turn_id: str, after_item_id: str, item_id: str) -> None:
        turn = self.store.load_turn(turn_id)
        if item_id in turn.item_ids:
            return
        try:
            idx = turn.item_ids.index(after_item_id)
            turn.item_ids.insert(idx + 1, item_id)
        except ValueError:
            turn.item_ids.append(item_id)
        self.store.save_turn(turn)

    async def _compute_phase_bridge(
        self,
        *,
        thread_id: str,
        user_prompt: str,
        state: TurnNarrationState,
        segment: ReasoningSegment,
        tool_calls: tuple,
        recent_tool_results: list[str],
        locale: str,
    ) -> str | None:
        from deepseek_tui.engine.usage_ledger import usage_source
        from deepseek_tui.protocol.responses import ToolCall

        client = self._get_llm_client()
        narration_config = self.config
        async with self._active_lock:
            active = self._active.get(thread_id)
            if active is not None:
                client = active.engine.client
                thread = self.store.load_thread(thread_id)
                narration_config = self._config_for_provider(
                    active.provider, thread.model
                )
        typed_calls: tuple[ToolCall, ...] = tool_calls
        with usage_source("phase_bridge"):
            return await compute_narration_display(
                client,
                narration_config,
                user_goal=user_prompt,
                state=state,
                segment=segment,
                tool_calls=typed_calls,
                recent_tool_results=recent_tool_results,
                locale=locale,
            )

    async def _persist_phase_bridge(
        self,
        thread_id: str,
        turn_id: str,
        segment: ReasoningSegment,
        text: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        item_id = f"item_{uuid.uuid4().hex[:8]}"
        item = TurnItemRecord(
            id=item_id,
            turn_id=turn_id,
            kind=TurnItemKind.STATUS,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary=summarize_text(text, SUMMARY_LIMIT),
            detail=text,
            metadata={
                PHASE_BRIDGE_METADATA_KEY: True,
                PHASE_BRIDGE_AFTER_REASONING_KEY: segment.item_id,
            },
            started_at=now,
            ended_at=now,
        )
        self.store.save_item(item)
        self._insert_turn_item_after(turn_id, segment.item_id, item_id)
        await self._emit_event(
            thread_id,
            turn_id,
            item_id,
            "item.completed",
            {"item": item.model_dump(mode="json")},
        )

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

    async def _finalize_orphan_workflow_items(
        self,
        thread_id: str,
        turn_id: str,
        workflow_items: dict[str, str],
        turn_status: RuntimeTurnStatus,
    ) -> None:
        """Close workflow progress items that never received a terminal event."""
        if not workflow_items:
            return
        import json as _json

        now = datetime.now(timezone.utc)
        interrupted = turn_status in (
            RuntimeTurnStatus.INTERRUPTED,
            RuntimeTurnStatus.CANCELED,
        )
        workflow_status = "cancelled" if interrupted else "failed"
        item_status = (
            TurnItemLifecycleStatus.INTERRUPTED
            if interrupted
            else TurnItemLifecycleStatus.FAILED
        )
        event_name = "item.interrupted" if interrupted else "item.failed"

        for tool_call_id, item_id in list(workflow_items.items()):
            try:
                item = self.store.load_item(item_id)
            except FileNotFoundError:
                continue
            if item.status != TurnItemLifecycleStatus.IN_PROGRESS:
                continue
            payload: dict[str, Any]
            try:
                parsed = _json.loads(item.detail or "{}")
                payload = parsed if isinstance(parsed, dict) else {}
            except _json.JSONDecodeError:
                payload = {}
            payload["tool_call_id"] = str(payload.get("tool_call_id") or tool_call_id)
            payload["completed"] = True
            payload["status"] = workflow_status

            item.status = item_status
            item.summary = summarize_text(
                f"{item.summary}: {workflow_status}",
                SUMMARY_LIMIT,
            )
            item.detail = _json.dumps(payload, default=str)
            item.ended_at = now
            self.store.save_item(item)
            await self._emit_event(
                thread_id,
                turn_id,
                item_id,
                event_name,
                {"item": item.model_dump(mode="json")},
            )
            await self._emit_event(
                thread_id,
                turn_id,
                item_id,
                "workflow.progress",
                payload,
            )
        workflow_items.clear()

    async def _emit_event(
        self,
        thread_id: str,
        turn_id: str | None,
        item_id: str | None,
        event: str,
        payload: dict[str, Any],
        *,
        force_checkpoint: bool = False,
    ) -> RuntimeEventRecord:
        record = await self.store.append_event(
            thread_id, turn_id, item_id, event, payload, force_checkpoint=force_checkpoint
        )
        self.event_bus.send(record)
        return record

    def _finalize_turn_latency(self, turn_id: str) -> dict[str, Any] | None:
        trace = get_turn_latency(turn_id)
        if trace is None:
            return None
        trace.turn_completed_ms = now_ms()
        trace.log_summary()
        return trace.to_payload()

    def _schedule_mcp_warmup(self) -> None:
        """Fire-and-forget background MCP tool discovery so first turn is fast."""
        if self._shared_tool_runtime is None:
            return
        mcp = getattr(self._shared_tool_runtime, "mcp_manager", None)
        if mcp is None:
            return
        self._mcp_warmup_task = asyncio.create_task(
            self._warmup_mcp(mcp), name="mcp-warmup"
        )

    async def _warmup_mcp(self, mcp: object) -> None:
        """Background MCP discover_tools so cache is hot before first turn."""
        import logging

        logger = logging.getLogger(__name__)
        try:
            discover = getattr(mcp, "discover_tools", None)
            if discover is None:
                return
            await asyncio.wait_for(discover(), timeout=30)
            logger.info("[mcp-warmup] tool discovery completed in background")
        except asyncio.TimeoutError:
            logger.warning("[mcp-warmup] background discovery timed out (30s)")
        except Exception:  # noqa: BLE001
            logger.debug("[mcp-warmup] background discovery failed (non-fatal)")

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


# Durable thread/turn/item runtime for the HTTP API and background tasks.
#
# Mirrors Rust ``crates/tui/src/runtime_threads.rs`` (4,413 lines).
# This module keeps DeepSeek-only execution while exposing Codex-like lifecycle
# semantics (threads, turns, items, interrupt/steer, and replayable events).
#
# Split into two layers:
# - Data models + RuntimeThreadStore (this file) — pure I/O, no engine logic
# - RuntimeThreadManager (thread_manager.py) — orchestration + engine loading
#
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from deepseek_tui.utils import write_json_atomic

logger = logging.getLogger(__name__)

__all__ = [
    "CURRENT_RUNTIME_SCHEMA_VERSION",
    "EVENT_CHANNEL_CAPACITY",
    "MAX_ACTIVE_THREADS_DEFAULT",
    "RUNTIME_RESTART_REASON",
    "SUMMARY_LIMIT",
    "CompactThreadRequest",
    "CreateThreadRequest",
    "RuntimeEventRecord",
    "RuntimeStoreState",
    "RuntimeThreadManagerConfig",
    "RuntimeThreadStore",
    "RuntimeTurnStatus",
    "StartTurnRequest",
    "SteerTurnRequest",
    "ThreadDetail",
    "ThreadRecord",
    "TurnItemKind",
    "TurnItemLifecycleStatus",
    "TurnItemRecord",
    "TurnRecord",
    "UpdateThreadRequest",
]

# --- constants (mirrors Rust) ------------------------------------------------

EVENT_CHANNEL_CAPACITY: int = 1024
MAX_ACTIVE_THREADS_DEFAULT: int = 8
SUMMARY_LIMIT: int = 280
CURRENT_RUNTIME_SCHEMA_VERSION: int = 2
RUNTIME_RESTART_REASON: str = "Interrupted by process restart"


# --- enums -------------------------------------------------------------------


class RuntimeTurnStatus(str, Enum):
    """Mirrors Rust ``RuntimeTurnStatus`` (line 53)."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"


class TurnItemKind(str, Enum):
    """Mirrors Rust ``TurnItemKind`` (line 64)."""

    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    AGENT_REASONING = "agent_reasoning"
    TOOL_CALL = "tool_call"
    FILE_CHANGE = "file_change"
    COMMAND_EXECUTION = "command_execution"
    CONTEXT_COMPACTION = "context_compaction"
    STATUS = "status"
    ERROR = "error"


class TurnItemLifecycleStatus(str, Enum):
    """Mirrors Rust ``TurnItemLifecycleStatus`` (line 77)."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"


# --- record models -----------------------------------------------------------


class ThreadRecord(BaseModel):
    """Mirrors Rust ``ThreadRecord`` (line 87)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    id: str
    created_at: datetime
    updated_at: datetime
    model: str
    provider: str = "deepseek"
    workspace: str
    mode: str = "agent"
    allow_shell: bool = False
    trust_mode: bool = False
    auto_approve: bool = False
    latest_turn_id: str | None = None
    latest_response_bookmark: str | None = None
    archived: bool = False
    system_prompt: str | None = None
    task_id: str | None = None
    coherence_state: str = "intro"
    title: str | None = None
    source_session_id: str | None = None
    source_session_path: str | None = None
    memory_mode: str | None = None


class TurnRecord(BaseModel):
    """Mirrors Rust ``TurnRecord`` (line 114)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    id: str
    thread_id: str
    status: RuntimeTurnStatus
    input_summary: str
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    item_ids: list[str] = Field(default_factory=list)
    steer_count: int = 0


def build_turn_usage_record(*, usage: Any, model: str) -> dict[str, Any]:
    """Persist a per-turn usage delta on ``TurnRecord.usage``."""
    from deepseek_tui.client.pricing import calculate_turn_cost_estimate_from_usage
    from deepseek_tui.protocol.responses import Usage

    u = usage if isinstance(usage, Usage) else Usage.model_validate(usage)
    input_tokens = max(0, int(u.input_tokens))
    output_tokens = max(0, int(u.output_tokens))
    record: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cache_hit_tokens": max(0, int(u.cache_read_input_tokens)),
        "cache_miss_tokens": max(0, int(u.cache_creation_input_tokens)),
        "turns": 1,
        "token_economy_savings_tokens": 0,
    }
    estimate = calculate_turn_cost_estimate_from_usage(model, u)
    if estimate is not None and estimate.is_positive:
        record["cost_usd"] = estimate.usd
        record["cost_cny"] = estimate.cny
    model_id = model.strip() or "unknown"
    record["models"] = {
        model_id: {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_hit_tokens": record["cache_hit_tokens"],
            "cache_miss_tokens": record["cache_miss_tokens"],
            "cost_usd": float(record.get("cost_usd", 0.0) or 0.0),
            "cost_cny": float(record.get("cost_cny", 0.0) or 0.0),
            "turns": 1,
        }
    }
    return record


def turn_usage_from_engine_or_event(
    *,
    engine: Any | None,
    event: TurnCompleteEvent | None,
    model: str,
) -> dict[str, Any] | None:
    ledger = getattr(engine, "turn_usage_ledger", None) if engine is not None else None
    if ledger is not None and ledger.items:
        return ledger.totals()
    if event is not None and event.usage is not None:
        return build_turn_usage_record(usage=event.usage, model=model)
    return None


def _usage_counter_value(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return 0


def _usage_counter_float(usage: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)
    return 0.0


def _empty_thread_usage_bucket(thread_id: str) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cache_miss_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_cny": 0.0,
        "cache_savings_usd": 0.0,
        "cache_savings_cny": 0.0,
        "token_economy_savings_tokens": 0,
        "token_economy_savings_usd": 0.0,
        "token_economy_savings_cny": 0.0,
        "turns": 0,
        "cache_hit_rate": None,
    }


def _turn_usage_has_cache_telemetry(usage: dict[str, Any]) -> bool:
    return any(key in usage for key in ("cache_hit_tokens", "cache_miss_tokens"))


def _add_turn_usage_to_bucket(
    bucket: dict[str, Any],
    usage: dict[str, Any],
) -> bool:
    bucket["input_tokens"] += _usage_counter_value(
        usage, "input_tokens", "prompt_tokens"
    )
    bucket["output_tokens"] += _usage_counter_value(
        usage, "output_tokens", "completion_tokens"
    )
    hit = _usage_counter_value(usage, "cache_hit_tokens")
    miss = _usage_counter_value(usage, "cache_miss_tokens")
    has_cache = _turn_usage_has_cache_telemetry(usage)
    if has_cache:
        bucket["cached_tokens"] += hit
        bucket["cache_miss_tokens"] += miss
    bucket["total_tokens"] += _usage_counter_value(usage, "total_tokens")
    if bucket["total_tokens"] <= 0:
        bucket["total_tokens"] = bucket["input_tokens"] + bucket["output_tokens"]
    bucket["cost_usd"] += _usage_counter_float(usage, "cost_usd")
    bucket["cost_cny"] += _usage_counter_float(usage, "cost_cny")
    bucket["token_economy_savings_tokens"] += _usage_counter_value(
        usage, "token_economy_savings_tokens"
    )
    bucket["turns"] += max(1, _usage_counter_value(usage, "turns"))
    return has_cache


def aggregate_thread_usage_bucket(
    thread_id: str,
    turns: list[TurnRecord],
    *,
    live_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bucket = _empty_thread_usage_bucket(thread_id)
    has_cache_telemetry = False
    for turn in turns:
        usage = turn.usage
        if not isinstance(usage, dict) or not usage:
            continue
        has_cache_telemetry = (
            _add_turn_usage_to_bucket(bucket, usage) or has_cache_telemetry
        )
    if isinstance(live_usage, dict) and live_usage:
        has_cache_telemetry = (
            _add_turn_usage_to_bucket(bucket, live_usage) or has_cache_telemetry
        )
    cache_total = bucket["cached_tokens"] + bucket["cache_miss_tokens"]
    bucket["cache_hit_rate"] = (
        bucket["cached_tokens"] / cache_total
        if has_cache_telemetry and cache_total > 0
        else None
    )
    return bucket


def thread_usage_bucket_has_data(bucket: dict[str, Any]) -> bool:
    return (
        bucket["total_tokens"] > 0
        or bucket["cached_tokens"] > 0
        or bucket["cache_miss_tokens"] > 0
        or bucket["cost_usd"] > 0
        or bucket["cost_cny"] > 0
        or bucket["token_economy_savings_tokens"] > 0
        or bucket["turns"] > 0
    )


def _empty_model_usage_bucket(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_cny": 0.0,
        "turns": 0,
    }


def _merge_model_usage_bucket(
    session: dict[str, dict[str, Any]],
    model_id: str,
    bucket: dict[str, Any],
) -> None:
    normalized = (model_id or "unknown").strip() or "unknown"
    target = session.setdefault(normalized, _empty_model_usage_bucket(normalized))
    input_tokens = _usage_counter_value(bucket, "input_tokens", "prompt_tokens")
    output_tokens = _usage_counter_value(
        bucket, "output_tokens", "completion_tokens"
    )
    target["input_tokens"] += input_tokens
    target["output_tokens"] += output_tokens
    target["total_tokens"] += _usage_counter_value(bucket, "total_tokens")
    if target["total_tokens"] <= 0:
        target["total_tokens"] = target["input_tokens"] + target["output_tokens"]
    target["cost_usd"] += _usage_counter_float(bucket, "cost_usd")
    target["cost_cny"] += _usage_counter_float(bucket, "cost_cny")
    target["turns"] += max(1, _usage_counter_value(bucket, "turns"))


def accumulate_model_usage_from_turn(
    session: dict[str, dict[str, Any]],
    turn_usage: dict[str, Any] | None,
    *,
    fallback_model: str,
) -> None:
    if not isinstance(turn_usage, dict) or not turn_usage:
        return
    models = turn_usage.get("models")
    if isinstance(models, dict) and models:
        for model_id, bucket in models.items():
            if isinstance(bucket, dict):
                _merge_model_usage_bucket(session, str(model_id), bucket)
        return
    fallback = (fallback_model or "unknown").strip() or "unknown"
    _merge_model_usage_bucket(session, fallback, turn_usage)


def session_model_usage_response(
    session: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    buckets = sorted(
        session.values(),
        key=lambda item: (
            -int(item.get("total_tokens", 0) or 0),
            str(item.get("model", "")),
        ),
    )
    totals = _empty_model_usage_bucket("total")
    totals.pop("model", None)
    for bucket in buckets:
        totals["input_tokens"] += int(bucket.get("input_tokens", 0) or 0)
        totals["output_tokens"] += int(bucket.get("output_tokens", 0) or 0)
        totals["total_tokens"] += int(bucket.get("total_tokens", 0) or 0)
        totals["cost_usd"] += float(bucket.get("cost_usd", 0.0) or 0.0)
        totals["cost_cny"] += float(bucket.get("cost_cny", 0.0) or 0.0)
        totals["turns"] += int(bucket.get("turns", 0) or 0)
    if not buckets:
        return {
            "group_by": "model",
            "scope": "session",
            "buckets": [],
            "totals": totals,
        }
    return {
        "group_by": "model",
        "scope": "session",
        "buckets": buckets,
        "totals": totals,
    }


def thread_usage_response(
    thread_id: str,
    turns: list[TurnRecord],
    *,
    live_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bucket = aggregate_thread_usage_bucket(
        thread_id, turns, live_usage=live_usage
    )
    if not thread_usage_bucket_has_data(bucket):
        return {
            "group_by": "thread",
            "buckets": [],
            "totals": {**bucket, "thread_count": 0},
        }
    totals = {**bucket, "thread_count": 1}
    return {
        "group_by": "thread",
        "buckets": [bucket],
        "totals": totals,
    }


class TurnItemRecord(BaseModel):
    """Mirrors Rust ``TurnItemRecord`` (line 139)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    id: str
    turn_id: str
    kind: TurnItemKind
    status: TurnItemLifecycleStatus
    summary: str
    detail: str | None = None
    metadata: Any | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class RuntimeEventRecord(BaseModel):
    """Mirrors Rust ``RuntimeEventRecord`` (line 160)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    seq: int
    timestamp: datetime
    thread_id: str
    turn_id: str | None = None
    item_id: str | None = None
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimeStoreState(BaseModel):
    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    next_seq: int = 1


# --- request models ----------------------------------------------------------


class CreateThreadRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    workspace: str | None = None
    mode: str | None = None
    allow_shell: bool | None = None
    trust_mode: bool | None = None
    auto_approve: bool | None = None
    archived: bool = False
    system_prompt: str | None = None
    task_id: str | None = None


class UpdateThreadRequest(BaseModel):
    archived: bool | None = None
    title: str | None = None
    memory_mode: str | None = None


class ForkThreadRequest(BaseModel):
    """Optional cutoff for fork-from-a-point.

    When ``through_item_id`` is omitted the whole thread is forked (legacy
    behavior). When provided, the forked thread contains the conversation up
    to and including that turn item.
    """

    through_item_id: str | None = None


class StartTurnRequest(BaseModel):
    prompt: str
    input_summary: str | None = None
    provider: str | None = None
    model: str | None = None
    mode: str | None = None
    allow_shell: bool | None = None
    trust_mode: bool | None = None
    auto_approve: bool | None = None
    ui_submit_at_ms: int | None = None
    main_runtime_request_start_ms: int | None = None
    hidden: bool = False
    internal_kind: str | None = None


class SteerTurnRequest(BaseModel):
    prompt: str


class CompactThreadRequest(BaseModel):
    reason: str | None = None


# --- composite response model ------------------------------------------------


class ThreadDetail(BaseModel):
    thread: ThreadRecord
    turns: list[TurnRecord] = Field(default_factory=list)
    items: list[TurnItemRecord] = Field(default_factory=list)
    latest_seq: int = 0


# --- config ------------------------------------------------------------------


class RuntimeThreadManagerConfig(BaseModel):
    """Mirrors Rust ``RuntimeThreadManagerConfig`` (line 479)."""

    data_dir: Path
    task_data_dir: Path
    max_active_threads: int = MAX_ACTIVE_THREADS_DEFAULT

    @classmethod
    def from_task_data_dir(cls, task_data_dir: Path) -> RuntimeThreadManagerConfig:
        import os

        override = os.environ.get("DEEPSEEK_RUNTIME_DIR", "").strip()
        data_dir = Path(override) if override else task_data_dir / "runtime"
        return cls(data_dir=data_dir, task_data_dir=task_data_dir)


# --- RuntimeThreadStore (file-based persistence) ----------------------------


class RuntimeThreadStore:
    """File-based store: threads/turns/items as individual JSON, events as JSONL.

    Mirrors Rust ``RuntimeThreadStore`` (line 191-476).
    """

    def __init__(self, root: Path) -> None:
        self._threads_dir = root / "threads"
        self._turns_dir = root / "turns"
        self._items_dir = root / "items"
        self._events_dir = root / "events"
        self._state_path = root / "state.json"

        for d in (
            self._threads_dir,
            self._turns_dir,
            self._items_dir,
            self._events_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        if self._state_path.exists():
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._state = RuntimeStoreState.model_validate(raw)
        else:
            self._state = RuntimeStoreState()
            write_json_atomic(self._state_path, self._state.model_dump())

        import asyncio

        self._seq_lock = asyncio.Lock()
        # Per-thread locks so seq allocation + JSONL append happen atomically
        # for a given events file (concurrent writers would interleave lines).
        self._event_write_locks: dict[str, asyncio.Lock] = {}
        self._events_since_checkpoint = 0
        self._last_checkpoint_at = time.monotonic()

    CHECKPOINT_EVENT_INTERVAL = 16
    CHECKPOINT_MAX_INTERVAL_S = 0.5

    # --- paths ---------------------------------------------------------------

    def _thread_path(self, thread_id: str) -> Path:
        return self._threads_dir / f"{thread_id}.json"

    def _turn_path(self, turn_id: str) -> Path:
        return self._turns_dir / f"{turn_id}.json"

    def _item_path(self, item_id: str) -> Path:
        return self._items_dir / f"{item_id}.json"

    def _events_path(self, thread_id: str) -> Path:
        return self._events_dir / f"{thread_id}.jsonl"

    # --- CRUD ----------------------------------------------------------------

    def save_thread(self, thread: ThreadRecord) -> None:
        write_json_atomic(self._thread_path(thread.id), thread.model_dump(mode="json"))

    def save_turn(self, turn: TurnRecord) -> None:
        write_json_atomic(self._turn_path(turn.id), turn.model_dump(mode="json"))

    def save_item(self, item: TurnItemRecord) -> None:
        write_json_atomic(self._item_path(item.id), item.model_dump(mode="json"))

    def load_thread(self, thread_id: str) -> ThreadRecord:
        path = self._thread_path(thread_id)
        if not path.exists():
            raise FileNotFoundError(f"Thread not found: {thread_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = ThreadRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Thread schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def load_turn(self, turn_id: str) -> TurnRecord:
        path = self._turn_path(turn_id)
        if not path.exists():
            raise FileNotFoundError(f"Turn not found: {turn_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = TurnRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Turn schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def load_item(self, item_id: str) -> TurnItemRecord:
        path = self._item_path(item_id)
        if not path.exists():
            raise FileNotFoundError(f"Item not found: {item_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = TurnItemRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Item schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def list_threads(self) -> list[ThreadRecord]:
        out: list[ThreadRecord] = []
        if not self._threads_dir.exists():
            return out
        for path in self._threads_dir.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = ThreadRecord.model_validate(raw)
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
                raise ValueError(
                    f"Thread schema v{record.schema_version} is newer than supported "
                    f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
                )
            out.append(record)
        out.sort(key=lambda t: t.updated_at, reverse=True)
        return out

    def list_turns_for_thread(self, thread_id: str) -> list[TurnRecord]:
        out: list[TurnRecord] = []
        if not self._turns_dir.exists():
            return out
        for path in self._turns_dir.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = TurnRecord.model_validate(raw)
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
                raise ValueError(
                    f"Turn schema v{record.schema_version} is newer than supported "
                    f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
                )
            if record.thread_id == thread_id:
                out.append(record)
        out.sort(key=lambda t: t.created_at)
        return out

    def list_items_for_turn(self, turn_id: str) -> list[TurnItemRecord]:
        out: list[TurnItemRecord] = []
        if not self._items_dir.exists():
            return out
        try:
            turn = self.load_turn(turn_id)
        except FileNotFoundError:
            turn = None
        if turn is not None and turn.item_ids:
            for item_id in turn.item_ids:
                try:
                    out.append(self.load_item(item_id))
                except FileNotFoundError:
                    continue
            return out
        for path in self._items_dir.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = TurnItemRecord.model_validate(raw)
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
                raise ValueError(
                    f"Item schema v{record.schema_version} is newer than supported "
                    f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
                )
            if record.turn_id == turn_id:
                out.append(record)
        out.sort(key=lambda i: i.started_at or datetime.min.replace(tzinfo=timezone.utc))
        return out

    # --- events (JSONL append) -----------------------------------------------

    async def append_event(
        self,
        thread_id: str,
        turn_id: str | None,
        item_id: str | None,
        event: str,
        payload: dict[str, Any],
        *,
        force_checkpoint: bool = False,
    ) -> RuntimeEventRecord:
        import asyncio

        write_lock = self._event_write_locks.setdefault(thread_id, asyncio.Lock())
        # Hold the per-thread lock across seq allocation AND the JSONL append
        # so concurrent writers cannot interleave lines in the events file.
        async with write_lock:
            async with self._seq_lock:
                seq = self._state.next_seq
                self._state.next_seq += 1
                self._events_since_checkpoint += 1
                now = time.monotonic()
                checkpoint_due = force_checkpoint or (
                    self._events_since_checkpoint >= self.CHECKPOINT_EVENT_INTERVAL
                    or (now - self._last_checkpoint_at) >= self.CHECKPOINT_MAX_INTERVAL_S
                )
                if checkpoint_due:
                    write_json_atomic(self._state_path, self._state.model_dump())
                    self._events_since_checkpoint = 0
                    self._last_checkpoint_at = now

            record = RuntimeEventRecord(
                schema_version=CURRENT_RUNTIME_SCHEMA_VERSION,
                seq=seq,
                timestamp=datetime.now(timezone.utc),
                thread_id=thread_id,
                turn_id=turn_id,
                item_id=item_id,
                event=event,
                payload=payload,
            )

            path = self._events_path(thread_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            line = record.model_dump_json()
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                if checkpoint_due:
                    f.flush()

        return record

    async def flush_event_checkpoint(self) -> None:
        """Persist ``state.next_seq`` after a batched delta flush."""
        async with self._seq_lock:
            if self._events_since_checkpoint <= 0:
                return
            write_json_atomic(self._state_path, self._state.model_dump())
            self._events_since_checkpoint = 0
            self._last_checkpoint_at = time.monotonic()

    def events_since(
        self, thread_id: str, since_seq: int | None = None
    ) -> list[RuntimeEventRecord]:
        path = self._events_path(thread_id)
        if not path.exists():
            return []
        out: list[RuntimeEventRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = RuntimeEventRecord.model_validate_json(line)
            except Exception:  # noqa: BLE001 — skip corrupt lines, keep the rest
                logger.warning(
                    "events_since_skip_corrupt_line thread_id=%s line=%.120s",
                    thread_id,
                    line,
                )
                continue
            if since_seq is not None and record.seq <= since_seq:
                continue
            out.append(record)
        return out

    async def current_seq(self) -> int:
        async with self._seq_lock:
            return self._state.next_seq - 1


# --- helper functions --------------------------------------------------------


def _ordered_turn_items(
    store: RuntimeThreadStore,
    turn: TurnRecord,
) -> list[TurnItemRecord]:
    """Return turn items in persisted order (``item_ids``), with stable fallback."""
    items = store.list_items_for_turn(turn.id)
    if not items:
        return []

    kind_rank = {
        TurnItemKind.USER_MESSAGE: 0,
        TurnItemKind.AGENT_MESSAGE: 1,
    }

    def sort_key(item: TurnItemRecord) -> tuple:
        started = item.started_at or datetime.min.replace(tzinfo=timezone.utc)
        return (started, kind_rank.get(item.kind, 99), item.id)

    if not turn.item_ids:
        return sorted(items, key=sort_key)

    by_id = {item.id: item for item in items}
    ordered = [by_id[item_id] for item_id in turn.item_ids if item_id in by_id]
    seen = set(turn.item_ids)
    orphans = sorted((item for item in items if item.id not in seen), key=sort_key)
    return ordered + orphans


def reconstruct_messages_from_turns(
    store: RuntimeThreadStore,
    thread_id: str,
) -> list:
    """Rebuild Engine chat history from persisted turn items.

    Mirrors Rust ``RuntimeThreadManager::reconstruct_messages_from_turns``.
    """
    from deepseek_tui.protocol.messages import (
        Message,
        Role,
        TextBlock,
        ToolUseBlock,
    )

    messages: list[Message] = []
    for turn in store.list_turns_for_thread(thread_id):
        for item in _ordered_turn_items(store, turn):
            text = (item.detail or item.summary or "").strip()
            if item.kind == TurnItemKind.USER_MESSAGE:
                if not text:
                    continue
                messages.append(
                    Message(role=Role.USER, content=[TextBlock(text=text)])
                )
            elif item.kind == TurnItemKind.AGENT_MESSAGE:
                if not text:
                    continue
                messages.append(
                    Message(role=Role.ASSISTANT, content=[TextBlock(text=text)])
                )
            elif item.kind in {
                TurnItemKind.TOOL_CALL,
                TurnItemKind.COMMAND_EXECUTION,
                TurnItemKind.FILE_CHANGE,
            }:
                meta = item.metadata if isinstance(item.metadata, dict) else {}
                tool_use_id = str(meta.get("tool_use_id") or item.id)
                tool_name = str(meta.get("tool_name") or item.summary or "tool")
                arguments = meta.get("arguments")
                if not isinstance(arguments, dict):
                    arguments = {}
                messages.append(
                    Message.assistant_with_tools(
                        [
                            ToolUseBlock(
                                id=tool_use_id,
                                name=tool_name,
                                input=arguments,
                            )
                        ]
                    )
                )
                if item.status in {
                    TurnItemLifecycleStatus.COMPLETED,
                    TurnItemLifecycleStatus.FAILED,
                } and text:
                    messages.append(
                        Message.tool_result(
                            tool_use_id,
                            text,
                            is_error=item.status == TurnItemLifecycleStatus.FAILED,
                        )
                    )
    return messages


def tool_kind_for_name(name: str) -> TurnItemKind:
    """Mirrors Rust ``tool_kind_for_name`` (line 2542)."""
    lower = name.lower()
    if lower in ("exec_shell", "exec_shell_wait", "exec_shell_interact"):
        return TurnItemKind.COMMAND_EXECUTION
    if "patch" in lower or "write" in lower or "edit" in lower:
        return TurnItemKind.FILE_CHANGE
    return TurnItemKind.TOOL_CALL


def _parse_tool_arguments(arguments: Any) -> dict[str, Any] | None:
    args = arguments
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(args, dict):
        return None
    return args


def _is_todo_tool_name(tool_name: str) -> bool:
    lower = tool_name.lower()
    return "todo" in lower or "checklist" in lower


def _todo_items_from_arguments(args: dict[str, Any]) -> list[dict[str, Any]] | None:
    todos = args.get("todos")
    if isinstance(todos, list) and todos:
        items: list[dict[str, Any]] = []
        for index, entry in enumerate(todos, start=1):
            if isinstance(entry, str) and entry.strip():
                items.append({"id": index, "content": entry.strip(), "status": "pending"})
                continue
            if not isinstance(entry, dict):
                continue
            content = entry.get("content") or entry.get("text")
            if not isinstance(content, str) or not content.strip():
                continue
            status = entry.get("status") if isinstance(entry.get("status"), str) else "pending"
            item_id = entry.get("id", index)
            items.append(
                {
                    "id": item_id,
                    "content": content.strip(),
                    "status": status,
                }
            )
        return items or None
    legacy = args.get("items")
    if isinstance(legacy, list) and legacy:
        return [
            {"id": index, "content": str(text).strip(), "status": "pending"}
            for index, text in enumerate(legacy, start=1)
            if isinstance(text, str) and str(text).strip()
        ] or None
    return None


def todo_tool_metadata(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    """Expose checklist/todo payloads to Workbench sidebar consumers."""
    if not _is_todo_tool_name(tool_name):
        return None
    args = _parse_tool_arguments(arguments)
    if not args:
        return {"tool_name": tool_name}
    items = _todo_items_from_arguments(args)
    if not items:
        return {"tool_name": tool_name}
    completed = sum(
        1
        for item in items
        if str(item.get("status", "")).lower() in {"completed", "done"}
    )
    return {
        "tool_name": tool_name,
        "items": items,
        "completion_pct": round(completed * 100 / len(items)) if items else 0,
    }


def todo_tool_metadata_from_result(
    tool_name: str,
    arguments: Any,
    result_metadata: dict[str, Any] | None,
    existing_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Merge checklist snapshots from tool args and result metadata for Workbench."""
    if not _is_todo_tool_name(tool_name):
        return None
    base: dict[str, Any] = dict(existing_metadata) if existing_metadata else {}
    base["tool_name"] = tool_name

    if isinstance(result_metadata, dict):
        task_updates = result_metadata.get("task_updates")
        if isinstance(task_updates, dict):
            checklist = task_updates.get("checklist")
            if isinstance(checklist, dict):
                items_raw = checklist.get("items")
                if isinstance(items_raw, list) and items_raw:
                    items: list[dict[str, Any]] = []
                    for index, entry in enumerate(items_raw, start=1):
                        if not isinstance(entry, dict):
                            continue
                        content = entry.get("content") or entry.get("text")
                        if not isinstance(content, str) or not content.strip():
                            continue
                        status = (
                            entry.get("status")
                            if isinstance(entry.get("status"), str)
                            else "pending"
                        )
                        item_id = entry.get("id", index)
                        items.append(
                            {
                                "id": item_id,
                                "content": content.strip(),
                                "status": status,
                            }
                        )
                    if items:
                        completed = sum(
                            1
                            for item in items
                            if str(item.get("status", "")).lower()
                            in {"completed", "done"}
                        )
                        base["items"] = items
                        base["completion_pct"] = (
                            round(completed * 100 / len(items)) if items else 0
                        )
                        in_progress = checklist.get("in_progress_id")
                        if in_progress is not None:
                            base["in_progress_id"] = in_progress
                        return base

    from_args = todo_tool_metadata(tool_name, arguments)
    if from_args and from_args.get("items"):
        base.update(from_args)
        return base

    args = _parse_tool_arguments(arguments)
    if args and "item_id" in args:
        items = base.get("items")
        if isinstance(items, list):
            item_id = str(args["item_id"])
            new_status: str | None = None
            if isinstance(args.get("status"), str):
                new_status = str(args["status"]).lower()
            elif isinstance(args.get("done"), bool):
                new_status = "completed" if args["done"] else "pending"
            if new_status:
                updated: list[dict[str, Any]] = []
                for row in items:
                    if not isinstance(row, dict):
                        continue
                    copy = dict(row)
                    if str(copy.get("id")) == item_id:
                        copy["status"] = new_status
                    updated.append(copy)
                base["items"] = updated
                completed = sum(
                    1
                    for item in updated
                    if str(item.get("status", "")).lower() in {"completed", "done"}
                )
                base["completion_pct"] = (
                    round(completed * 100 / len(updated)) if updated else 0
                )
                return base

    return from_args or (base if base.get("items") else None)


_TASK_TOOL_NAMES = frozenset(
    {"task_create", "task_list", "task_read", "task_cancel"}
)


def _is_task_tool_name(tool_name: str) -> bool:
    return tool_name in _TASK_TOOL_NAMES


def _normalize_task_entry(entry: Any) -> dict[str, Any] | None:
    """Coerce a task summary dict into the Workbench sidebar shape."""
    if not isinstance(entry, dict):
        return None
    task_id = entry.get("id") or entry.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return None
    status = entry.get("status")
    status = status.strip().lower() if isinstance(status, str) else "queued"
    prompt = entry.get("prompt_summary") or entry.get("prompt") or ""
    return {
        "id": task_id.strip(),
        "status": status,
        "prompt": str(prompt).strip(),
    }


def task_tool_metadata_from_result(
    tool_name: str,
    arguments: Any,
    result_metadata: dict[str, Any] | None,
    existing_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Expose durable-task payloads to the Workbench TASKS sidebar section.

    ``task_list`` returns ``metadata["tasks"]`` (a list of summaries);
    ``task_create`` / ``task_read`` / ``task_cancel`` return a single task's
    ``task_id`` / ``status`` / ``prompt_summary``. Both shapes are normalised
    into ``metadata["tasks"]`` so the frontend reads one consistent field.
    """
    if not _is_task_tool_name(tool_name):
        return None
    if not isinstance(result_metadata, dict):
        return None

    entries: list[dict[str, Any]] = []
    raw_tasks = result_metadata.get("tasks")
    if isinstance(raw_tasks, list):
        for item in raw_tasks:
            normalized = _normalize_task_entry(item)
            if normalized:
                entries.append(normalized)
    else:
        normalized = _normalize_task_entry(result_metadata)
        if normalized:
            entries.append(normalized)

    if not entries:
        return None

    base: dict[str, Any] = dict(existing_metadata) if existing_metadata else {}
    base["tool_name"] = tool_name
    base["tasks"] = entries
    return base


def tool_item_metadata(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    """Extract file path metadata for Workbench Diff / ChangeInspector."""
    todo_meta = todo_tool_metadata(tool_name, arguments)
    if todo_meta is not None:
        return todo_meta
    if tool_kind_for_name(tool_name) != TurnItemKind.FILE_CHANGE:
        return None
    args = _parse_tool_arguments(arguments)
    if not args:
        return None
    for key in ("path", "file_path", "filename", "target"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return {"path": value.strip()}
    return None


def tool_started_metadata(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    """Metadata persisted on a tool item at start.

    Combines file-path / todo metadata (``tool_item_metadata``) with the raw
    call args under ``tool_input``. The live UI reads the args from the SSE
    event, but a thread reload reads only stored metadata — without this, read
    and search tool rows lose their descriptor ("browse dir src/", "grep TODO")
    after restore.
    """
    metadata = tool_item_metadata(tool_name, arguments)
    parsed = _parse_tool_arguments(arguments)
    if parsed:
        metadata = {**(metadata or {}), "tool_input": parsed}
    return metadata


def _looks_like_unified_diff(text: str) -> bool:
    return any(
        line.startswith(("@@", "diff --git ", "--- ", "+++ ", "index "))
        for line in text.splitlines()
    )


def _file_path_from_arguments(args: dict[str, Any]) -> str:
    for key in ("path", "file_path", "filename", "target"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "file"


def _synthesize_edit_diff(path: str, search: str, replace: str) -> str:
    old_lines = search.splitlines() or [""]
    new_lines = replace.splitlines() or [""]
    body = [f"-{line}" for line in old_lines] + [f"+{line}" for line in new_lines]
    return f"--- a/{path}\n+++ b/{path}\n@@\n" + "\n".join(body)


def _synthesize_new_file_diff(path: str, content: str) -> str:
    lines = content.splitlines()
    count = max(len(lines), 1)
    body = "\n".join(f"+{line}" for line in lines) if lines else "+"
    return f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{count} @@\n{body}"


def file_change_completion_detail(
    tool_name: str,
    arguments: Any,
    result_content: str,
) -> str:
    """Return unified diff text for Workbench ChangeInspector when possible."""
    content = (result_content or "").strip()
    if content and _looks_like_unified_diff(content):
        return content

    args = _parse_tool_arguments(arguments)
    if not args:
        return content

    lower = tool_name.lower()
    path = _file_path_from_arguments(args)

    if lower == "apply_patch":
        patch = args.get("patch")
        if isinstance(patch, str) and _looks_like_unified_diff(patch):
            return patch
        changes = args.get("changes")
        if isinstance(changes, list) and len(changes) == 1:
            only = changes[0]
            if isinstance(only, dict):
                change_path = only.get("path")
                change_content = only.get("content")
                if isinstance(change_path, str) and isinstance(change_content, str):
                    return _synthesize_new_file_diff(change_path.strip(), change_content)

    if lower == "edit_file":
        search = args.get("search", args.get("old_string"))
        replace = args.get("replace", args.get("new_string"))
        if isinstance(search, str) and isinstance(replace, str):
            return _synthesize_edit_diff(path, search, replace)

    if lower == "write_file":
        file_content = args.get("content")
        if isinstance(file_content, str):
            return _synthesize_new_file_diff(path, file_content)

    return content


def duration_ms(start: datetime, end: datetime) -> int:
    """Milliseconds between two datetimes, clamped to >=0."""
    delta = end - start
    ms = int(delta.total_seconds() * 1000)
    return max(ms, 0)
