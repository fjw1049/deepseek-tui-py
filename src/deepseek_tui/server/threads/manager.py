"""RuntimeThreadManager — orchestrates Engine lifecycles for HTTP threads.

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
    PluginMountEvent,
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
)
from deepseek_tui.server.phase_bridge import (
    PHASE_BRIDGE_AFTER_REASONING_KEY,
    PHASE_BRIDGE_METADATA_KEY,
    PROCESS_INTENT_METADATA_KEY,
    BatchKind,
    ProcessIntent,
    ReasoningSegment,
    TurnNarrationState,
    build_process_intent,
    classify_batch,
    compute_narration_display,
    gate_decision,
    infer_next_phase,
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
    from deepseek_tui.server.sessions import ImportTuiSessionRequest

from deepseek_tui.server.threads.broadcast import AsyncBroadcast
from deepseek_tui.server.threads.items import (
    duration_ms,
    file_change_completion_detail,
    reconstruct_messages_from_turn,
    reconstruct_messages_from_turns,
    task_tool_metadata_from_result,
    todo_tool_metadata_from_result,
    tool_kind_for_name,
    tool_started_metadata,
)
from deepseek_tui.server.threads.models import (
    EVENT_CHANNEL_CAPACITY,
    RUNTIME_RESTART_REASON,
    SUMMARY_LIMIT,
    CompactThreadRequest,
    CreateThreadRequest,
    RuntimeEventRecord,
    RuntimeThreadManagerConfig,
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
)
from deepseek_tui.server.threads.store import RuntimeThreadStore
from deepseek_tui.server.threads.usage import (
    accumulate_model_usage_from_turn,
    session_model_usage_response,
    thread_usage_response,
    turn_usage_from_engine_or_event,
)

logger = logging.getLogger(__name__)

# Upper bound on narration-service calls that word silent tool rounds within a
# single turn; the neutral structured frame is always shown regardless.
MAX_INTENT_FILLS_PER_TURN = 6


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
        "tool_call_id": msg.tool_call_id,
        "ok": msg.ok,
        "parent_id": msg.parent_id,
        "summary": msg.summary,
        "error": msg.error,
        "model": msg.model,
        "usage": msg.usage,
        "input_summary": msg.input_summary,
        "output_summary": msg.output_summary,
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
    """Manages active engine threads, lifecycle, and event persistence."""

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

    def _sync_trust_mode(self, engine: Engine, trust_mode: bool) -> None:
        """Mirror thread / turn trust onto ToolContext (TUI session parity).

        Also refreshes Seatbelt policy so ``trust_mode`` / danger-full-access
        actually disables the sandbox — not only path escape checks.
        """
        from deepseek_tui.policy.sandbox import sync_execution_sandbox_policy

        engine.tool_context.trust_mode = trust_mode
        sync_execution_sandbox_policy(
            engine.tool_context,
            getattr(engine, "mode", None) or "agent",
            engine.tool_context.working_directory,
            sandbox_mode=getattr(self.config, "sandbox_mode", None),
        )

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

        Re-hydrates the engine task by driving ``_ensure_engine_loaded``
        so the LRU cache + engine task wake up before clients hit the next
        ``/threads/{id}/turns`` request. Re-emits a ``thread.resumed``
        event onto the event timeline.
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

        Returns aggregate counts + last-updated id so dashboards / TUI
        sidebars can render a header without paginating the full list.
        ``ThreadRecord`` doesn't carry a status enum, so we expose
        ``active`` vs ``archived`` and a per-mode breakdown.
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

    async def rewind_thread(
        self, thread_id: str, *, before_item_id: str
    ) -> ThreadRecord:
        """Truncate a thread in place at ``before_item_id``.

        Deletes the item itself and everything after it (later items in the
        same turn plus all later turns) from the durable store, then re-syncs
        the warm engine session so the model no longer sees the dropped
        history. Backs the Workbench "edit & resend" (rewind) flow.
        """
        thread = self.store.load_thread(thread_id)

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is not None and state.active_turn is not None:
                raise ValueError("cannot rewind thread while a turn is active")

        turns = self.store.list_turns_for_thread(thread_id)
        cutoff_turn_index: int | None = None
        for idx, turn in enumerate(turns):
            if before_item_id in turn.item_ids:
                cutoff_turn_index = idx
                break
        if cutoff_turn_index is None:
            raise ValueError(f"item not found in thread: {before_item_id}")

        cutoff_turn = turns[cutoff_turn_index]
        kept_item_ids: list[str] = []
        dropping = False
        for item_id in cutoff_turn.item_ids:
            if item_id == before_item_id:
                dropping = True
            if dropping:
                self.store.delete_item(item_id)
            else:
                kept_item_ids.append(item_id)
        if kept_item_ids:
            cutoff_turn.item_ids = kept_item_ids
            self.store.save_turn(cutoff_turn)
        else:
            self.store.delete_turn(cutoff_turn.id)

        for turn in turns[cutoff_turn_index + 1 :]:
            for item_id in turn.item_ids:
                self.store.delete_item(item_id)
            self.store.delete_turn(turn.id)

        remaining = self.store.list_turns_for_thread(thread_id)
        thread.latest_turn_id = remaining[-1].id if remaining else None
        thread.updated_at = datetime.now(timezone.utc)
        self.store.save_thread(thread)

        # A warm engine still holds the dropped turns in session_messages;
        # replace them so regeneration truly starts from the rewound state.
        # (Unlike _sync_engine_session, an empty history must clear too.)
        async with self._active_lock:
            state = self._active.get(thread_id)
        if state is not None:
            messages = reconstruct_messages_from_turns(self.store, thread_id)
            state.engine.sync_session(messages, model=thread.model)

        await self._emit_event(
            thread_id,
            None,
            None,
            "thread.rewound",
            {
                "thread": thread.model_dump(mode="json"),
                "before_item_id": before_item_id,
            },
        )
        return thread

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

        # Soft-resume: previous turn cut short → rehydrate before reserving.
        prior_turns = self.store.list_turns_for_thread(thread_id)
        resume_from_incomplete = bool(
            prior_turns
            and prior_turns[-1].status
            in (
                RuntimeTurnStatus.INTERRUPTED,
                RuntimeTurnStatus.FAILED,
            )
            and not req.hidden
        )
        if resume_from_incomplete:
            self._resync_warm_engine_from_store(thread_id)

        now = datetime.now(timezone.utc)
        auto_approve = req.auto_approve if req.auto_approve is not None else thread.auto_approve
        trust_mode = req.trust_mode if req.trust_mode is not None else thread.trust_mode

        # Check-and-reserve must happen inside a single lock section:
        # releasing the lock between "no active turn" and "set active_turn"
        # lets two concurrent POST .../turns start two turns on one thread.
        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is None:
                pop_turn_latency(turn_id)
                raise RuntimeError("Thread engine not loaded")
            if state.active_turn is not None:
                pop_turn_latency(turn_id)
                raise ValueError("Thread already has an active turn")
            if state.provider != provider:
                client = self._get_llm_client(provider)
                state.engine.client = client
                state.engine.turn_loop.client = client
                state.provider = provider
            state.engine.mode = effective_mode
            state.engine.tool_context.metadata["turn_latency_turn_id"] = turn_id
            # Inject CONTINUE_NUDGE only after we own the turn slot so a
            # rejected concurrent start cannot pollute session_messages.
            if resume_from_incomplete:
                from deepseek_tui.engine.context_pressure import wrap_system_reminder
                from deepseek_tui.protocol.messages import Message, MessageOrigin
                from deepseek_tui.tools.durable_transcript import CONTINUE_NUDGE

                resume_msgs = list(state.engine.session_messages)
                resume_msgs.append(
                    Message.user(
                        wrap_system_reminder(CONTINUE_NUDGE),
                        origin=MessageOrigin.SYSTEM_REMINDER,
                    )
                )
                state.engine.sync_session(resume_msgs, model=model)
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
                reasoning_effort=req.reasoning_effort,
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
        if self._elevation_bridge is not None:
            self._elevation_bridge.cancel_for_thread(thread_id)

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
        compaction_succeeded = False
        if before_count == 0:
            summary_text = "Nothing to compact — session is empty."
            engine.session_messages.clear()
        else:
            result = await engine._run_compaction(list(engine.session_messages))
            engine.session_messages[:] = result.messages
            if result.success:
                compaction_succeeded = True
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
        # Persist the compacted session so later reconstruct/resync cannot
        # re-inflate the pre-compact tool history from older turn items.
        compaction_meta: dict[str, Any] | None = None
        if compaction_succeeded:
            compaction_meta = {
                "session_messages": [
                    m.model_dump(mode="json") for m in engine.session_messages
                ]
            }
        item = TurnItemRecord(
            id=item_id,
            turn_id=turn_id,
            kind=TurnItemKind.CONTEXT_COMPACTION,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary=summarize_text(summary_text, SUMMARY_LIMIT),
            detail=summary_text,
            metadata=compaction_meta,
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
        self._restore_active_plugin(engine, thread)
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

    def _resync_warm_engine_from_store(self, thread_id: str) -> None:
        """Rehydrate a warm engine after an interrupted/failed turn.

        Engine cancel/fail discards in-flight ``working_messages`` so a partial
        assistant chunk cannot corrupt later turns. Completed tool rounds from
        that turn are already durable as turn items — sync them back so the
        next user message (e.g. "继续") continues from the last completed
        tool-round boundary instead of an empty ``session_messages``.

        When the live engine already holds a compaction bridge, keep that
        compacted prefix and only append the incomplete turn's durable
        progress — a full reconstruct would re-inflate pre-compact history.
        """
        state = self._active.get(thread_id)
        if state is None:
            return
        thread = self.store.load_thread(thread_id)
        reconstructed = reconstruct_messages_from_turns(self.store, thread_id)

        from deepseek_tui.engine.context_pressure import extract_compaction_bridge_text

        engine_msgs = list(state.engine.session_messages)
        if extract_compaction_bridge_text(engine_msgs):
            turns = self.store.list_turns_for_thread(thread_id)
            incomplete = [
                t
                for t in turns
                if t.status
                in (
                    RuntimeTurnStatus.INTERRUPTED,
                    RuntimeTurnStatus.FAILED,
                )
            ]
            if incomplete:
                tail = reconstruct_messages_from_turn(self.store, incomplete[-1])
                state.engine.sync_session(
                    [*engine_msgs, *tail], model=thread.model
                )
                return

        state.engine.sync_session(reconstructed, model=thread.model)

    def _restore_active_plugin(self, engine: Engine, thread: ThreadRecord) -> None:
        """Re-apply the session's mounted plugin after engine reconstruction.

        The mount (``@plugin:<name>``) is session-level in-memory state on the
        engine, lost when an engine is rebuilt on thread resume. Scan the
        thread's persisted STATUS items for the latest ``active_plugin``
        metadata (turns are chronologically ordered, so the last signal wins)
        and re-mount so the next turn keeps the narrowed tool whitelist, the
        read-only plugin-dir grant, and the ``## Active Plugin`` prompt block.
        A null signal (explicit ``@plugin:off``) means intentionally unmounted.
        """
        from deepseek_tui.server.phase_bridge import ACTIVE_PLUGIN_METADATA_KEY

        latest_name: str | None = None
        saw_signal = False
        for turn in self.store.list_turns_for_thread(thread.id):
            for item in self.store.list_items_for_turn(turn.id):
                meta = item.metadata if isinstance(item.metadata, dict) else None
                if not meta or ACTIVE_PLUGIN_METADATA_KEY not in meta:
                    continue
                saw_signal = True
                raw = meta[ACTIVE_PLUGIN_METADATA_KEY]
                if isinstance(raw, dict):
                    name = raw.get("name")
                    latest_name = str(name) if isinstance(name, str) and name else None
                else:
                    latest_name = None  # explicit unmount (null marker)
        if not saw_signal or not latest_name:
            return
        try:
            engine.set_active_plugin(latest_name)
        except Exception:  # noqa: BLE001 - restore is best-effort
            logger.warning(
                "restore_active_plugin failed name=%s", latest_name, exc_info=True
            )

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
                if getattr(event, "success", True):
                    turn_status = RuntimeTurnStatus.COMPLETED
                    turn_error = None
                else:
                    turn_status = RuntimeTurnStatus.FAILED
                    turn_error = (
                        getattr(event, "error_message", None) or "Turn failed"
                    )
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

        if turn_status in (
            RuntimeTurnStatus.INTERRUPTED,
            RuntimeTurnStatus.FAILED,
        ):
            self._resync_warm_engine_from_store(thread_id)

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
        """Consume engine events and persist turn items + runtime events."""
        current_message_text = ""
        current_message_item_id: str | None = None
        # Preface item already finalized earlier in this round (a ToolCallEvent
        # closes the open message before AgentRoundComplete arrives). Kept so
        # the round-complete handler can attach the structured narration frame
        # to it instead of persisting a duplicate from event.preface_text.
        round_preface_item_id: str | None = None
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
        intent_fill_count = 0
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
            intent: ProcessIntent | None = None,
        ) -> None:
            await self._persist_phase_bridge(
                thread_id, turn_id, segment, text, intent=intent
            )
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
            extra_metadata: dict[str, Any] | None = None,
        ) -> None:
            nonlocal current_message_item_id, current_message_text, round_preface_item_id
            if current_message_item_id is None:
                return
            if agent_segment == MID_TURN_PREFACE:
                round_preface_item_id = current_message_item_id
            await flush_delta_batch()
            item = self.store.load_item(current_message_item_id)
            if agent_segment or extra_metadata:
                base_meta = item.metadata if isinstance(item.metadata, dict) else {}
                item.metadata = {
                    **base_meta,
                    **(extra_metadata or {}),
                    **({AGENT_SEGMENT_KEY: agent_segment} if agent_segment else {}),
                }
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

        async def persist_round_intent(text: str, intent: ProcessIntent) -> str:
            """Persist a pre-tool narration frame.

            ``text`` may be empty: the frame then carries only structured
            fields (``source == "none"``) and the UI renders a neutral
            progress state until the narration service upserts wording.
            """
            cleaned = text.strip()
            now = datetime.now(timezone.utc)
            item_id = f"item_{uuid.uuid4().hex[:8]}"
            item = TurnItemRecord(
                id=item_id,
                turn_id=turn_id,
                kind=TurnItemKind.AGENT_MESSAGE,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=summarize_text(cleaned, SUMMARY_LIMIT) if cleaned else "",
                detail=cleaned or None,
                metadata={
                    AGENT_SEGMENT_KEY: MID_TURN_PREFACE,
                    PROCESS_INTENT_METADATA_KEY: intent.to_metadata(),
                },
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
            return item_id

        async def tag_item_process_intent(item_id: str, intent: ProcessIntent) -> None:
            """Attach the structured frame to an already-finalized preface item."""
            item = self.store.load_item(item_id)
            base_meta = item.metadata if isinstance(item.metadata, dict) else {}
            item.metadata = {
                **base_meta,
                PROCESS_INTENT_METADATA_KEY: intent.to_metadata(),
            }
            self.store.save_item(item)
            await self._emit_event(
                thread_id,
                turn_id,
                item_id,
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
            decision = gate_decision(
                state=narration_state,
                segment=segment,
                tool_calls=tool_calls,
                narrated_ids=narrated_reasoning_ids,
                min_chars=narration_cfg.min_chars,
                has_tool_error=recent_tool_had_error,
                pending_scheduled=len(narration_compute_tasks),
                max_published=narration_cfg.max_per_turn,
                min_interval_s=narration_cfg.min_interval_s,
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
            milestone_intent = build_process_intent(
                scope="milestone",
                source="narration_service",
                phase=infer_next_phase(
                    narration_state.phase,
                    batch_kind,
                    has_tool_error=recent_tool_had_error,
                ),
                tool_calls=tool_calls,
                locale=narration_locale,
            )
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
                    await persist_segment_narration(
                        segment, text, batch_kind, tc_tuple, milestone_intent
                    )

            task = asyncio.create_task(
                run_and_persist(), name=f"phase-bridge-{segment.item_id}"
            )
            narration_compute_tasks.append(task)

        def schedule_intent_fill(
            item_id: str,
            intent: ProcessIntent,
            segment: ReasoningSegment | None,
            tool_calls: tuple,
        ) -> bool:
            """Ask the narration service to word a silent round's frame.

            Returns True when a fill was scheduled. The neutral frame is
            already visible; this only upserts wording, so any failure simply
            leaves the neutral state in place.
            """
            nonlocal intent_fill_count
            if not narration_cfg.enabled or segment is None:
                return False
            if intent_fill_count >= MAX_INTENT_FILLS_PER_TURN:
                return False
            intent_fill_count += 1
            recent = recent_tool_summaries[-narration_cfg.include_recent_tool_results :]

            async def run_and_fill() -> None:
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
                        "intent_fill compute failed turn=%s item=%s", turn_id, item_id
                    )
                    return
                if not text:
                    return
                item = self.store.load_item(item_id)
                item.detail = text
                item.summary = summarize_text(text, SUMMARY_LIMIT)
                base_meta = item.metadata if isinstance(item.metadata, dict) else {}
                item.metadata = {
                    **base_meta,
                    PROCESS_INTENT_METADATA_KEY: {
                        **intent.to_metadata(),
                        "source": "narration_service",
                    },
                }
                item.ended_at = datetime.now(timezone.utc)
                self.store.save_item(item)
                await self._emit_event(
                    thread_id,
                    turn_id,
                    item_id,
                    "item.completed",
                    {"item": item.model_dump(mode="json")},
                )

            narration_compute_tasks.append(
                asyncio.create_task(run_and_fill(), name=f"intent-fill-{item_id}")
            )
            return True

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
                        # completes (via ThreadDetail reload).
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
                        if event.tool_name == "workflow":
                            wf_meta = (
                                event.metadata.get("workflow")
                                if isinstance(event.metadata, dict)
                                else None
                            )
                            wf_name = (
                                wf_meta.get("name")
                                if isinstance(wf_meta, dict)
                                else None
                            )
                            label = (
                                str(wf_name).strip()
                                if isinstance(wf_name, str) and wf_name.strip()
                                else "workflow"
                            )
                            item.summary = summarize_text(
                                f"workflow: {label} completed", SUMMARY_LIMIT
                            )
                        else:
                            item.summary = summarize_text(
                                f"{event.tool_name}: {event.content}", SUMMARY_LIMIT
                            )
                    else:
                        recent_tool_had_error = True
                        item.status = TurnItemLifecycleStatus.FAILED
                        if event.tool_name == "workflow":
                            item.summary = summarize_text(
                                f"workflow failed: {event.content}", SUMMARY_LIMIT
                            )
                        else:
                            item.summary = summarize_text(
                                f"{event.tool_name} failed: {event.content}",
                                SUMMARY_LIMIT,
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
                if event.run_id:
                    payload["run_id"] = event.run_id
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

            elif isinstance(event, PluginMountEvent):
                # Persist the mount/unmount as a STATUS item carrying structured
                # active_plugin metadata, so the UI can render a persistent chip
                # and _restore_active_plugin can re-apply the mount on reload.
                from deepseek_tui.server.phase_bridge import (
                    ACTIVE_PLUGIN_METADATA_KEY,
                    PluginMountInfo,
                )

                now = datetime.now(timezone.utc)
                item_id = f"item_{uuid.uuid4().hex[:8]}"
                info = PluginMountInfo(
                    name=event.name,
                    version=event.version,
                    path=event.path,
                    scope=event.scope,
                    trusted=event.trusted,
                    permissions=event.permissions,
                    mcp_active=event.mcp_active,
                )
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
                    metadata={ACTIVE_PLUGIN_METADATA_KEY: info.to_metadata()},
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
                # Same closeout as TurnCompleteEvent: interrupt used to `break`
                # here without flush/reconcile, so cancelled sub-agents never
                # got a terminal mailbox envelope and the UI card stayed
                # "running" forever (and blocked the composer as busy).
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
                break

            elif isinstance(event, AgentRoundCompleteEvent):
                segment = await finalize_open_reasoning()
                if not event.tool_calls:
                    last_completed_reasoning = None
                    preface = (event.preface_text or "").strip()
                    if preface and current_message_item_id is not None:
                        await finalize_open_message(agent_segment=FINAL_ANSWER)
                    elif preface:
                        await persist_final_answer_message(text=preface)
                    elif current_message_item_id is not None:
                        await finalize_open_message(agent_segment=FINAL_ANSWER)
                else:
                    # The model's own preface is passed through verbatim as the
                    # pre-tool storyline (no content vetting — wording quality
                    # is owned by the prompt, not runtime rules). A silent
                    # round gets a structured neutral frame that the narration
                    # service may later fill with wording.
                    segment = segment or last_completed_reasoning
                    batch_kind = classify_batch(event.tool_calls)
                    intent_phase = infer_next_phase(
                        narration_state.phase,
                        batch_kind,
                        has_tool_error=recent_tool_had_error,
                    )
                    preface = (event.preface_text or "").strip()
                    fill_scheduled = False
                    if current_message_item_id is not None or round_preface_item_id or preface:
                        intent = build_process_intent(
                            scope="pre_tool",
                            source="primary_model",
                            phase=intent_phase,
                            tool_calls=event.tool_calls,
                            locale=narration_locale,
                        )
                        if current_message_item_id is not None:
                            await finalize_open_message(
                                agent_segment=MID_TURN_PREFACE,
                                extra_metadata={
                                    PROCESS_INTENT_METADATA_KEY: intent.to_metadata()
                                },
                            )
                        elif round_preface_item_id:
                            # The preface item was already closed by this
                            # round's first ToolCallEvent; only attach the
                            # structured frame instead of duplicating it.
                            await tag_item_process_intent(round_preface_item_id, intent)
                        else:
                            await persist_round_intent(preface, intent)
                    else:
                        intent = build_process_intent(
                            scope="pre_tool",
                            source="none",
                            phase=intent_phase,
                            tool_calls=event.tool_calls,
                            locale=narration_locale,
                        )
                        frame_id = await persist_round_intent("", intent)
                        fill_scheduled = schedule_intent_fill(
                            frame_id, intent, segment, event.tool_calls
                        )
                    if segment is not None and not fill_scheduled:
                        schedule_phase_bridge(segment, event)
                round_preface_item_id = None
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
                if getattr(event, "success", True):
                    turn_status = RuntimeTurnStatus.COMPLETED
                    turn_error = None
                else:
                    turn_status = RuntimeTurnStatus.FAILED
                    # Keep the more specific message from a prior ErrorEvent
                    # when the event itself carries none.
                    turn_error = (
                        getattr(event, "error_message", None) or turn_error
                        or "Turn failed"
                    )
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

        if turn_status == RuntimeTurnStatus.COMPLETED:
            recovered_answer = await self._recover_missing_final_answer(thread_id, turn_id)
            if recovered_answer:
                await persist_final_answer_message(text=recovered_answer)

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

        # Cancel/fail dropped Engine.session_messages mid-turn; durable items
        # still hold completed tool rounds — rehydrate before the next turn.
        if turn_status in (
            RuntimeTurnStatus.INTERRUPTED,
            RuntimeTurnStatus.FAILED,
        ):
            self._resync_warm_engine_from_store(thread_id)

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
                engine_client = getattr(active.engine, "client", None)
                if engine_client is not None:
                    client = engine_client
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

    async def _recover_missing_final_answer(self, thread_id: str, turn_id: str) -> str | None:
        """Produce a safe final reply when a completed turn emitted none.

        This is deliberately a tool-free synthesis of persisted evidence. It
        never reruns the agent loop, so a missing answer cannot repeat edits or
        commands. The provider client owns transport retries; semantic recovery
        is capped at two attempts to avoid holding a completed turn hostage.
        """
        turn = self.store.load_turn(turn_id)
        evidence: list[str] = []
        for item_id in turn.item_ids:
            item = self.store.load_item(item_id)
            metadata = item.metadata if isinstance(item.metadata, dict) else {}
            if (
                item.kind == TurnItemKind.AGENT_MESSAGE
                and metadata.get(AGENT_SEGMENT_KEY) == FINAL_ANSWER
                and (item.detail or item.summary or "").strip()
            ):
                return None
            if item.kind in {
                TurnItemKind.TOOL_CALL,
                TurnItemKind.COMMAND_EXECUTION,
                TurnItemKind.FILE_CHANGE,
                TurnItemKind.ERROR,
            }:
                text = (item.summary or item.detail or "").strip()
                if text:
                    evidence.append(summarize_text(text, 240))

        if not evidence:
            return None

        from deepseek_tui.engine.usage_ledger import usage_source
        from deepseek_tui.protocol.messages import Message, MessageRequest
        from deepseek_tui.protocol.responses import StreamTextDelta

        thread = self.store.load_thread(thread_id)
        client = self._get_llm_client()
        async with self._active_lock:
            active = self._active.get(thread_id)
            engine_client = getattr(active.engine, "client", None) if active else None
            if engine_client is not None:
                client = engine_client

        prompt = (
            "The agent completed a coding task but produced no final answer. "
            "Write a concise user-facing completion summary using ONLY the "
            "verified execution evidence below. Do not mention hidden reasoning, "
            "do not call tools, and do not claim unverified outcomes.\n\n"
            "Verified evidence:\n"
            + "\n".join(f"- {line}" for line in evidence[-12:])
        )
        request = MessageRequest(
            model=thread.model or "deepseek-chat",
            messages=[Message.user(prompt)],
            system_prompt=(
                "Return only the final user-facing answer. Be concise, factual, "
                "and state any failed verification plainly."
            ),
            max_tokens=768,
            temperature=0.1,
            reasoning_effort="low",
        )
        for _ in range(2):
            try:
                chunks: list[str] = []
                with usage_source("final_answer_recovery"):
                    async for event in client.stream_chat_completion(request):
                        if isinstance(event, StreamTextDelta):
                            chunks.append(event.text)
                text = "".join(chunks).strip()
                if text:
                    return text
            except Exception:
                logger.info("final_answer_recovery failed turn=%s", turn_id, exc_info=True)
        return None

    async def _persist_phase_bridge(
        self,
        thread_id: str,
        turn_id: str,
        segment: ReasoningSegment,
        text: str,
        *,
        intent: ProcessIntent | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        item_id = f"item_{uuid.uuid4().hex[:8]}"
        metadata: dict[str, Any] = {
            PHASE_BRIDGE_METADATA_KEY: True,
            PHASE_BRIDGE_AFTER_REASONING_KEY: segment.item_id,
        }
        if intent is not None:
            metadata[PROCESS_INTENT_METADATA_KEY] = intent.to_metadata()
        item = TurnItemRecord(
            id=item_id,
            turn_id=turn_id,
            kind=TurnItemKind.STATUS,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary=summarize_text(text, SUMMARY_LIMIT),
            detail=text,
            metadata=metadata,
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
        """On startup, mark any Queued/InProgress turns as Interrupted."""
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
                    except Exception:
                        logger.warning(
                            "Skipping unreadable item %s during interrupted-state recovery",
                            item_id,
                            exc_info=True,
                        )
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
