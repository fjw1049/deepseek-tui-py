"""RuntimeThreadManager — orchestrates Engine lifecycles for HTTP threads.

Mirrors Rust ``RuntimeThreadManager`` (runtime_threads.rs:594-2488).
Manages active engines, turn monitoring, LRU eviction, and restart recovery.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
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
    tool_kind_for_name,
    tool_item_metadata,
)
from deepseek_tui.config.models import Config
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ErrorEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.utils import summarize_text

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient

logger = logging.getLogger(__name__)

__all__ = ["RuntimeThreadManager"]


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
    __slots__ = ("handle", "engine_task", "active_turn")

    def __init__(self, handle: EngineHandle, engine_task: asyncio.Task[None]) -> None:
        self.handle = handle
        self.engine_task: asyncio.Task[None] = engine_task
        self.active_turn: _ActiveTurnState | None = None


class _ApprovalDecision:
    APPROVE = "approve"
    DENY = "deny"
    RETRY_FULL_ACCESS = "retry_full_access"


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
    ) -> None:
        self.config = config
        self.workspace = workspace.resolve()
        self.manager_cfg = manager_cfg
        self.store = RuntimeThreadStore(manager_cfg.data_dir)
        self._llm_client = llm_client
        self._approval_bridge = approval_bridge

        self._active: dict[str, _ActiveThreadState] = {}
        self._lru: OrderedDict[str, None] = OrderedDict()
        self._active_lock = asyncio.Lock()

        self.event_bus: AsyncBroadcast[RuntimeEventRecord] = AsyncBroadcast(
            capacity=EVENT_CHANNEL_CAPACITY
        )
        self._cancel_event = asyncio.Event()

        self._recover_interrupted_state()

    # --- public lifecycle ----------------------------------------------------

    def shutdown(self) -> None:
        self._cancel_event.set()
        if self._approval_bridge is not None:
            self._approval_bridge.cancel_all()

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
                    return state.handle.resolve_user_input(
                        request_id, {"cancelled": True}
                    )
                return state.handle.resolve_user_input(
                    request_id, {"answers": answers or []}
                )
        return False

    async def get_thread_detail(self, thread_id: str) -> ThreadDetail:
        thread = self.store.load_thread(thread_id)
        turns = self.store.list_turns_for_thread(thread_id)
        items: list[TurnItemRecord] = []
        for turn in turns:
            items.extend(self.store.list_items_for_turn(turn.id))
        latest_seq = await self.store.current_seq()
        return ThreadDetail(thread=thread, turns=turns, items=items, latest_seq=latest_seq)

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

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is not None and state.active_turn is not None:
                raise ValueError("Thread already has an active turn")

        now = datetime.now(timezone.utc)
        turn_id = f"turn_{uuid.uuid4().hex[:8]}"
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

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is None:
                raise RuntimeError("Thread engine not loaded")
            auto_approve = req.auto_approve if req.auto_approve is not None else thread.auto_approve
            trust_mode = req.trust_mode if req.trust_mode is not None else thread.trust_mode
            state.active_turn = _ActiveTurnState(
                turn_id=turn_id, auto_approve=auto_approve, trust_mode=trust_mode
            )
            self._touch_lru(thread_id)

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

        await handle.send_message(content=prompt)

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
        handle, _ = await self._ensure_engine_loaded(thread)

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is not None and state.active_turn is not None:
                raise ValueError("Thread already has an active turn")

        now = datetime.now(timezone.utc)
        turn_id = f"turn_{uuid.uuid4().hex[:8]}"
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

        async with self._active_lock:
            state = self._active.get(thread_id)
            if state is None:
                raise RuntimeError("Thread engine not loaded")
            state.active_turn = _ActiveTurnState(
                turn_id=turn_id, auto_approve=thread.auto_approve, trust_mode=thread.trust_mode
            )
            self._touch_lru(thread_id)

        await self._emit_event(
            thread_id, turn_id, None, "turn.started",
            {"turn": turn.model_dump(mode="json"), "manual_compaction": True},
        )
        # Send a cancel to trigger compaction via engine loop
        # (In a full impl this would send Op::CompactContext)
        await handle.send_message(content="/compact", model=thread.model)

        monitor_task = asyncio.create_task(
            self._monitor_turn_safe(thread_id, turn_id, handle),
            name=f"monitor-compact-{turn_id}",
        )
        del monitor_task
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
                self._touch_lru(thread.id)
                return state.handle, state.engine_task

        from deepseek_tui.engine.engine import Engine

        handle = EngineHandle()
        workspace = Path(thread.workspace).expanduser().resolve()
        engine = await Engine.create(
            handle=handle,
            client=self._get_llm_client(),
            config=self.config,
            working_directory=workspace,
            default_model=thread.model,
            start_mcp=False,
        )
        engine_task = asyncio.create_task(engine.run(), name=f"engine-{thread.id}")

        async with self._active_lock:
            evicted = self._enforce_lru_capacity()
            self._active[thread.id] = _ActiveThreadState(
                handle=handle, engine_task=engine_task
            )
            self._touch_lru(thread.id)

        for evicted_state in evicted:
            await evicted_state.handle.cancel(reason="lru_eviction")
            evicted_state.engine_task.cancel()

        return handle, engine_task

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
                approval_id = event.tool_call_id
                await self._emit_event(
                    thread_id, turn_id, None, "approval.required",
                    {
                        "id": approval_id,
                        "approval_id": approval_id,
                        "tool_name": event.request.tool_name,
                        "description": event.request.description,
                    },
                )
                async with self._active_lock:
                    state = self._active.get(thread_id)
                    if state and state.active_turn and state.active_turn.turn_id == turn_id:
                        auto_approve = state.active_turn.auto_approve
                    else:
                        auto_approve = False

                from deepseek_tui.engine.events import ApprovalResolvedEvent

                if auto_approve:
                    await handle.emit(
                        ApprovalResolvedEvent(
                            tool_call_id=approval_id, approved=True
                        )
                    )
                elif self._approval_bridge is not None:
                    fut = self._approval_bridge.register(approval_id)
                    try:
                        approved = await fut
                    except asyncio.CancelledError:
                        approved = False
                    await handle.emit(
                        ApprovalResolvedEvent(
                            tool_call_id=approval_id,
                            approved=approved,
                            reason=None if approved else "denied",
                        )
                    )
                else:
                    await handle.emit(
                        ApprovalResolvedEvent(
                            tool_call_id=approval_id,
                            approved=False,
                            reason="denied",
                        )
                    )

            elif isinstance(event, UserInputRequiredEvent):
                await self._emit_event(
                    thread_id, turn_id, None, "user_input.required",
                    {
                        "id": event.tool_call_id,
                        "request_id": event.tool_call_id,
                        "questions": event.questions,
                    },
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
