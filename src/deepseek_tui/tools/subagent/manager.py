"""SubAgentManager — spawn/cancel/result/list/resume/send_input.

``asyncio.Task``-backed
execution (not multiprocessing — LLM calls are IO-bound; see HANDOVER.md
decision 2026-05-07). Persistence under
``~/.deepseek/agents/registries/<workspace_key>.json``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import Config
from deepseek_tui.engine.pause import RunPause
from deepseek_tui.tools.subagent.agent import SubAgent, SubAgentExecutor, _stub_executor
from deepseek_tui.tools.subagent.completion import (
    AgentRunOutput,
    SubAgentCompletion,
    build_completion_payload,
)
from deepseek_tui.tools.subagent.mailbox import Mailbox, MailboxMessage
from deepseek_tui.tools.subagent.types import (
    DEFAULT_MAX_AGENTS,
    DEFAULT_MAX_SPAWN_DEPTH,
    _MAX_TERMINAL_AGENTS_IN_MEMORY,
    SpawnRequest,
    SubAgentResult,
    SubAgentStatus,
    SubAgentStatusKind,
    _epoch_ms,
    whale_nickname_for_index,
)

logger = logging.getLogger(__name__)


class SubAgentManager:
    """Manager for in-process sub-agents.

    Runs agents as
    :class:`asyncio.Task` rather than multiprocessing subprocesses —
    LLM calls are IO-bound.
    """

    def __init__(
        self,
        workspace: Path,
        max_agents: int = DEFAULT_MAX_AGENTS,
        state_path: Path | None = None,
        executor: SubAgentExecutor | None = None,
        mailbox: Mailbox | None = None,
        default_model: str = "deepseek-chat",
        llm_max_concurrent: int = 2,
        handoff_timeout_secs: float = 600.0,
    ) -> None:
        self.workspace = workspace
        self.max_agents = max_agents
        self.default_model = default_model
        self.handoff_timeout_secs = handoff_timeout_secs
        self._state_path = state_path
        self._executor: SubAgentExecutor = executor or _stub_executor
        self._mailbox = mailbox
        # Gate concurrent sub-agent LLM streams: N parallel children plus
        # the parent all hitting one provider key is what triggers 429
        # rate-limit storms (and their multi-minute backoffs). Tool
        # execution is not gated — only the streaming call itself.
        self.llm_semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(llm_max_concurrent)
            if llm_max_concurrent > 0
            else None
        )
        from .store import AgentStore

        self._store = AgentStore(state_path) if state_path is not None else None
        self._records: dict[str, dict[str, Any]] = {}
        self._persisted: dict[str, dict[str, Any]] = {}
        self._owned_ids: set[str] = set()
        self._claims: dict[str, Any] = {}
        self.storage_error: str | None = None
        self._closed = False
        self._changed = asyncio.Event()
        self._agents: dict[str, SubAgent] = {}
        self._lock = asyncio.Lock()
        self._session_boot_id: str = f"boot_{uuid.uuid4().hex[:12]}"
        self._parent_cancel: asyncio.Event | None = None
        self.parent_pause: RunPause | None = None
        self._parent_completion_sink: Callable[[SubAgentCompletion], None] | None = (
            None
        )
        self._loop_runtime: SubAgentRuntime | None = None
        # Wired per parent turn by ThreadManager for File Mutation Ledger.
        self.on_file_mutation: Callable[[dict[str, Any]], None] | None = None
        if state_path is not None:
            self._load_state()
        if mailbox is not None:
            mailbox.snapshot_provider = self._mailbox_snapshot

    def _mailbox_snapshot(self) -> list[MailboxMessage]:
        messages = []
        for snap in self.list_agents():
            messages.append(MailboxMessage.started(snap.agent_id, snap.agent_type.value))
            if snap.status.kind is SubAgentStatusKind.COMPLETED:
                messages.append(MailboxMessage.completed(snap.agent_id, snap.result or ""))
            elif snap.status.kind is SubAgentStatusKind.FAILED:
                messages.append(MailboxMessage.failed(snap.agent_id, snap.status.message or ""))
            elif snap.status.kind is not SubAgentStatusKind.RUNNING:
                messages.append(MailboxMessage.cancelled(snap.agent_id))
        return messages

    def attach_parent_completion_sink(
        self, sink: Callable[[SubAgentCompletion], None]
    ) -> None:
        """Wake the parent engine turn loop when a direct child finishes (#756)."""
        self._parent_completion_sink = sink

    def attach_loop_runtime(self, runtime: SubAgentRuntime) -> None:
        """Wire shared client/config for ``run_subagent_loop``."""
        self._loop_runtime = runtime

    def bind_active_task_id(self, task_id: str | None) -> None:
        """Propagate durable-task nesting guard into the loop runtime.

        Called after ``Engine.create`` when a task executor sets
        ``tool_context.active_task_id`` — create-time wiring happens too early
        for that id to be known.
        """
        if self._loop_runtime is None:
            return
        self._loop_runtime.active_task_id = (
            task_id.strip() if isinstance(task_id, str) and task_id.strip() else None
        )

    @property
    def loop_runtime(self) -> SubAgentRuntime | None:
        return self._loop_runtime

    @property
    def session_boot_id(self) -> str:
        return self._session_boot_id

    @property
    def mailbox(self) -> Mailbox | None:
        return self._mailbox

    def attach_parent_cancel(self, token: asyncio.Event) -> None:
        """Link parent engine cancellation to all descendant agents."""
        self._parent_cancel = token

    def attach_parent_pause(self, pause: RunPause) -> None:
        """Share the parent turn's dispatch fence with all descendants."""
        self.parent_pause = pause

    def running_count(self) -> int:
        return sum(
            1
            for a in self._agents.values()
            if a.status.kind is SubAgentStatusKind.RUNNING
        )

    def running_foreground_count(self) -> int:
        """Running agents the parent turn should block on (handoff).

        Excludes ``background`` agents — those are detached from the handoff
        wait. Their ``<deepseek:subagent.done>`` sentinel is still delivered
        (active-turn handoff drain, or idle hidden follow-up turn).
        """
        return sum(
            1
            for a in self._agents.values()
            if a.status.kind is SubAgentStatusKind.RUNNING
            and not getattr(a, "background", False)
        )

    def list_filtered(self, include_archived: bool = False) -> list[SubAgentResult]:
        out: list[SubAgentResult] = []
        from .store import restore_agent

        for agent_id in self._records.keys() | self._agents.keys():
            agent = self._agents.get(agent_id)
            if agent is None:
                agent = restore_agent(self._records[agent_id], self.workspace, self.default_model)
            from_prior = self._is_from_prior_session(agent)
            if from_prior and not include_archived:
                continue
            snap = agent.snapshot()
            snap = replace(snap, from_prior_session=from_prior)
            out.append(snap)
        return out

    def list_agents(self) -> list[SubAgentResult]:
        return self.list_filtered(include_archived=False)

    def _loop_runtime_for_spawn(
        self,
        request: SpawnRequest,
        child_depth: int,
        parent_runtime: SubAgentRuntime | None = None,
    ) -> SubAgentRuntime | None:
        source = parent_runtime or self._loop_runtime
        if source is None:
            return None
        from dataclasses import replace

        rt = source.with_spawn_depth(child_depth)
        if request.auto_approve is not None:
            rt = replace(rt, auto_approve=request.auto_approve)
        return rt

    async def spawn(
        self, request: SpawnRequest, *, parent_runtime: SubAgentRuntime | None = None
    ) -> SubAgentResult:
        async with self._lock:
            self._check_admission()
            child_depth = request.parent_depth + 1
            if child_depth > DEFAULT_MAX_SPAWN_DEPTH:
                raise RuntimeError(
                    f"max sub-agent spawn depth exceeded "
                    f"({DEFAULT_MAX_SPAWN_DEPTH}); refusing nested spawn at "
                    f"depth {child_depth}"
                )
            runtime = self._loop_runtime_for_spawn(request, child_depth, parent_runtime)
            model = request.model or (
                parent_runtime.config.subagents.default_model or parent_runtime.model
                if parent_runtime is not None
                else self.default_model
            )
            provider = None
            if runtime is not None:
                from deepseek_tui.config.routing import config_for_model

                route = config_for_model(runtime.config, model)
                provider = route.provider
            agent = SubAgent(
                agent_type=request.agent_type,
                prompt=request.prompt,
                assignment=request.assignment,
                model=model,
                provider=provider,
                nickname=request.nickname
                or whale_nickname_for_index(len(self._agents)),
                allowed_tools=request.allowed_tools,
                session_boot_id=self._session_boot_id,
                workspace=request.workspace or self.workspace,
                spawn_depth=child_depth,
                fork_messages=request.fork_messages if request.fork_context else None,
                parent_cancel=self._parent_cancel,
                mailbox=self._mailbox,
                loop_runtime=runtime,
                output_schema=request.output_schema,
                system_prompt=request.system_prompt,
                background=request.background,
            )
            self._claim_agent(agent)
            self._agents[agent.id] = agent
            snapshot = agent.snapshot()
            self._persist_best_effort()
            agent.task = asyncio.create_task(self._drive_agent(agent))

        if self._mailbox is not None:
            parent_id = (request.parent_agent_id or "").strip()
            if parent_id:
                self._mailbox.send(
                    MailboxMessage.child_spawned(parent_id, agent.id)
                )
            self._mailbox.send(
                MailboxMessage.started(
                    agent.id, request.agent_type.value, prompt=request.prompt
                )
            )
        return snapshot

    async def get_result(self, agent_id: str) -> SubAgentResult:
        async with self._lock:
            agent = self._require_agent(agent_id)
            snapshot = agent.snapshot()
            self._trim_cache()
            return snapshot

    async def cancel(self, agent_id: str) -> SubAgentResult:
        async with self._lock:
            agent = self._require_agent(agent_id)
            task = agent.task
            if agent.status.kind is SubAgentStatusKind.RUNNING and not agent.cancel_token.is_set():
                agent.cancel_token.set()
                if task is not None and not task.done():
                    task.cancel()
        # Join outside the manager lock: finalization needs the same lock.
        if task is not None:
            await asyncio.gather(asyncio.shield(task), return_exceptions=True)
        async with self._lock:
            # Cancellation before the coroutine's first instruction cannot run
            # its finally block, so finalize that case here.
            if agent.status.kind is SubAgentStatusKind.RUNNING and agent.cancel_token.is_set():
                agent.status = SubAgentStatus.cancelled()
                agent.ended_at_ms = _epoch_ms()
                self._persist_best_effort()
                if not agent.closing:
                    self._release_claim(agent.id)
                self._changed.set()
                self._changed = asyncio.Event()
                if self._mailbox is not None:
                    self._mailbox.send(MailboxMessage.cancelled(agent.id))
                self._notify_parent_completion(agent)
            return agent.snapshot()

    def _check_admission(self) -> None:
        if self._closed:
            raise RuntimeError("Sub-agent manager is shut down")
        if self.running_count() >= self.max_agents:
            raise RuntimeError(f"Too many sub-agents running ({self.max_agents} cap)")

    def _claim_agent(self, agent: SubAgent) -> None:
        if self._store is not None:
            from deepseek_tui.tools.task.store import TaskStoreLock

            try:
                self._claims[agent.id] = TaskStoreLock(self._store.directory / ".claims" / agent.id)
            except RuntimeError as exc:
                raise RuntimeError(f"Agent {agent.id} already has an active executor") from exc
        self._owned_ids.add(agent.id)

    def _release_claim(self, agent_id: str) -> None:
        claim = self._claims.pop(agent_id, None)
        if claim is not None:
            claim.close()

    def _reopen_terminal_locked(self, agent: SubAgent) -> None:
        """Reset a terminal agent to Running in preparation for a re-drive.

        Caller must hold ``self._lock``; the caller re-spawns the driver task.
        """
        self._check_admission()
        if agent.closing:
            raise RuntimeError(f"Agent {agent.id} is closing")
        if agent.task is not None and not agent.task.done():
            raise RuntimeError(f"Agent {agent.id} is still stopping")
        self._claim_agent(agent)
        # Registry records contain durable state only. Engine.create attaches
        # the live runtime after loading them; bind it when a child is resumed.
        # Keep existing runtimes so same-process spawn overrides survive.
        if agent.loop_runtime is None and self._loop_runtime is not None:
            agent.loop_runtime = self._loop_runtime.with_spawn_depth(agent.spawn_depth)
        agent.mailbox = self._mailbox
        agent.parent_cancel = self._parent_cancel
        agent.session_boot_id = self._session_boot_id
        agent.status = SubAgentStatus.running()
        agent.result = None
        agent.structured_result = None
        agent.structured_received = False
        agent.max_steps_reached = False
        agent.ended_at_ms = None
        agent.cancel_token = asyncio.Event()
        agent.started_at_ms = _epoch_ms()
        self._persist_best_effort()

    async def send_input(
        self, agent_id: str, text: str, interrupt: bool = False
    ) -> None:
        """Queue input for an agent's next round.

        A terminal (completed/cancelled/failed/interrupted) agent is resumed
        first — the input becomes its next round, continuing from the durable
        transcript instead of erroring out.
        """
        resumed = False
        async with self._lock:
            agent = self._require_agent(agent_id)
            if agent.status.kind is not SubAgentStatusKind.RUNNING:
                self._reopen_terminal_locked(agent)
                resumed = True
            agent.input_queue.put_nowait((text, interrupt))
            if interrupt:
                agent.interrupt_event.set()
            if resumed:
                agent.task = asyncio.create_task(self._drive_agent(agent))

        if resumed:
            if self._mailbox is not None:
                self._mailbox.send(
                    MailboxMessage.started(
                        agent_id, agent.agent_type.value, prompt=agent.prompt
                    )
                )

    async def resume(self, agent_id: str) -> SubAgentResult:
        """True-resume a terminated agent from its durable transcript.

        Reopens status to Running and re-spawns the driver. The loop hydrates
        any checkpoint under ``~/.deepseek/agents/runs/<id>/``; without a
        transcript it restarts from the original prompt (legacy behavior).
        A completed report does not block this — the parent decides whether
        the handoff actually covered the assignment.
        """
        async with self._lock:
            agent = self._require_agent(agent_id)
            if agent.status.kind is SubAgentStatusKind.RUNNING:
                raise RuntimeError(f"Agent {agent_id} is already running")
            self._reopen_terminal_locked(agent)
            agent.task = asyncio.create_task(self._drive_agent(agent))
            snapshot = agent.snapshot()

        if self._mailbox is not None:
            self._mailbox.send(
                MailboxMessage.started(
                    agent_id, agent.agent_type.value, prompt=agent.prompt
                )
            )
        return snapshot

    async def close(self, agent_id: str) -> SubAgentResult:
        """Terminate and remove an agent from the active map."""
        async with self._lock:
            agent = self._require_agent(agent_id)
            if agent_id not in self._claims:
                self._claim_agent(agent)
            agent.closing = True
        snapshot = await self.cancel(agent_id)
        workspace: Path | None = None
        async with self._lock:
            try:
                if self._store is not None:
                    self._store.remove(agent_id)
            except OSError:
                self._require_agent(agent_id).closing = False
                raise
            finally:
                self._release_claim(agent_id)
            agent = self._agents.pop(agent_id, None)
            if agent is not None:
                workspace = Path(agent.workspace)
            self._records.pop(agent_id, None)
            self._persisted.pop(agent_id, None)
            self._owned_ids.discard(agent_id)
        if workspace is not None:
            from deepseek_tui.tools.durable_transcript import (
                clear_transcript,
                subagent_transcript_path,
            )

            clear_transcript(subagent_transcript_path(workspace, agent_id))
        return snapshot

    async def wait(
        self, agent_ids: list[str], mode: str, timeout_ms: int
    ) -> list[SubAgentResult]:
        """Wait until `mode` ("any" or "all") targets are terminal.

        Returns the snapshots after the wait concludes (either mode
        satisfied or timeout expired).
        """
        if mode not in ("any", "all", "first"):
            raise ValueError(f"Unknown wait mode: {mode}")
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            async with self._lock:
                snapshots = [
                    self._require_agent(aid).snapshot() for aid in agent_ids
                ]
                changed = self._changed
            terminals = [s for s in snapshots if s.status.kind is not SubAgentStatusKind.RUNNING]
            if mode in ("any", "first"):
                if terminals:
                    return snapshots
            else:  # all
                if len(terminals) == len(snapshots):
                    return snapshots
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return snapshots
            try:
                await asyncio.wait_for(changed.wait(), remaining)
            except asyncio.TimeoutError:
                pass

    def known_agent_ids(self) -> set[str]:
        """Snapshot the ids of every agent currently tracked.

        Used by a turn's monitor at start-up to tag pre-existing agents as
        *foreign*: turns are serial per thread, so any agent already present
        when a turn begins was spawned by an earlier turn and must not have
        its mailbox events re-attributed to the new turn.
        """
        return set(self._records) | set(self._agents)

    async def shutdown(self) -> None:
        """Stop admission, cancel and join all owned executions."""
        async with self._lock:
            self._closed = True
            ids = [aid for aid, agent in self._agents.items()
                   if agent.task is not None and not agent.task.done()]
        await asyncio.gather(*(self.cancel(aid) for aid in ids), return_exceptions=True)
        for agent_id in list(self._claims):
            self._release_claim(agent_id)

    def _require_agent(self, agent_id: str) -> SubAgent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raw = self._records.get(agent_id)
            if raw is None:
                raise KeyError(f"Unknown agent: {agent_id}")
            from .store import restore_agent

            agent = restore_agent(raw, self.workspace, self.default_model)
            self._agents[agent_id] = agent
        return agent

    def _is_from_prior_session(self, agent: SubAgent) -> bool:
        return (
            not agent.session_boot_id
            or agent.session_boot_id != self._session_boot_id
        )

    def _notify_parent_completion(self, agent: SubAgent) -> None:
        """Wake the parent turn loop (#756) for direct children in any terminal state."""
        if agent.spawn_depth != 1 or self._parent_completion_sink is None:
            return
        snap = agent.snapshot()
        payload = build_completion_payload(snap)
        try:
            self._parent_completion_sink(
                SubAgentCompletion(agent_id=agent.id, payload=payload)
            )
        except Exception:  # noqa: BLE001
            pass

    async def _drive_agent(self, agent: SubAgent) -> None:
        if self._parent_cancel is not None and self._parent_cancel.is_set():
            agent.cancel_token.set()
        result = None
        try:
            if agent.cancel_token.is_set():
                raise asyncio.CancelledError
            result = await self._executor(agent, agent.cancel_token)
            status = SubAgentStatus.cancelled() if agent.cancel_token.is_set() else SubAgentStatus.completed()
        except asyncio.CancelledError:
            status = SubAgentStatus.cancelled()
        except Exception as exc:
            logger.exception("subagent failed id=%s", agent.id)
            status = SubAgentStatus.failed(str(exc))
        async with self._lock:
            agent.status = status
            agent.ended_at_ms = _epoch_ms()
            if status.kind is SubAgentStatusKind.COMPLETED:
                if isinstance(result, AgentRunOutput):
                    agent.result = result.text
                    agent.structured_result = result.structured
                    agent.structured_received = result.structured_received or result.structured is not None
                else:
                    agent.result = str(result) if result is not None else None
            self._persist_best_effort()
            if not agent.closing:
                self._release_claim(agent.id)
            self._changed.set()
            self._changed = asyncio.Event()
        if self._mailbox is not None:
            if status.kind is SubAgentStatusKind.CANCELLED:
                self._mailbox.send(MailboxMessage.cancelled(agent.id))
            elif status.kind is SubAgentStatusKind.FAILED:
                self._mailbox.send(MailboxMessage.failed(agent.id, status.message or ""))
            else:
                self._mailbox.send(MailboxMessage.completed(agent.id, agent.result or ""))
        self._notify_parent_completion(agent)
        await self._evict_terminal_agents()

    async def _evict_terminal_agents(self) -> None:
        async with self._lock:
            self._trim_cache()

    def _trim_cache(self) -> None:
        terminal = [
            (aid, agent) for aid, agent in self._agents.items()
            if agent.status.kind is not SubAgentStatusKind.RUNNING and aid in self._records
            and (agent.task is None or agent.task.done() or agent.task is asyncio.current_task())
        ]
        terminal.sort(key=lambda pair: pair[1].started_at_ms)
        for aid, _ in terminal[:max(0, len(terminal) - _MAX_TERMINAL_AGENTS_IN_MEMORY)]:
            del self._agents[aid]
            self._persisted.pop(aid, None)
            self._owned_ids.discard(aid)

    def _persist_best_effort(self) -> None:
        try:
            self._persist_state()
            self.storage_error = None
        except OSError as exc:
            self.storage_error = str(exc)
            logger.warning("Sub-agent persistence failed: %s", exc)

    def _persist_state(self) -> None:
        from .store import agent_record

        for agent_id in self._owned_ids & self._agents.keys():
            raw = agent_record(self._agents[agent_id])
            if self._persisted.get(agent_id) == raw:
                continue
            if self._store is not None:
                self._store.save(raw)
            self._records[agent_id] = raw
            self._persisted[agent_id] = raw

    def _load_state(self) -> None:
        from .store import restore_agent

        if self._store is None:
            return
        for agent_id, raw in self._store.load().items():
            try:
                agent = restore_agent(raw, self.workspace, self.default_model)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                logger.warning("Skipping invalid sub-agent %s: %s", agent_id, exc)
                self.storage_error = str(exc)
                continue
            self._records[agent_id] = raw
            self._agents[agent_id] = agent
        self.storage_error = self.storage_error or self._store.error
        self._trim_cache()


@dataclass(slots=True)
class SubAgentRuntime:
    """Runtime context forwarded to children on spawn.

    All depths share
    :attr:`manager`; children increment :attr:`spawn_depth` only.
    """

    manager: SubAgentManager
    client: Any
    model: str
    config: Config
    workspace: Path
    allow_shell: bool = True
    # Default True so detached / unparented children can write. Interactive
    # sessions attach a parent approval_handler; the tool gate prefers that
    # handler's live auto_approve_enabled() over this create-time snapshot.
    auto_approve: bool = True
    task_manager: Any = None
    cancel_token: asyncio.Event = field(default_factory=asyncio.Event)
    mailbox: Mailbox | None = None
    spawn_depth: int = 0
    max_spawn_depth: int = DEFAULT_MAX_SPAWN_DEPTH
    # When set, children inherit the durable-task nesting guard so they
    # cannot call ``task_create`` (max_task_nest_depth=1).
    active_task_id: str | None = None
    # Parent engine approval bridge — gated tools escalate here instead of
    # hard-denying when the session is not auto-approved.
    approval_handler: Any | None = None
    emit_event: Any | None = None
    # Parent engine's lifecycle HookExecutor. When set, the sub-agent loop
    # fires ``subagent_stop`` (Claude Code "SubagentStop") hooks on
    # completion; a blocking decision keeps the sub-agent working.
    hook_executor: Any | None = None
    # Explicit trust only — never derived from ``auto_approve``: an
    # auto-approved (fire-and-forget) child must not silently gain
    # workspace-confinement bypass / danger-full-access sandbox.
    trust_mode: bool = False

    policy: Any | None = None
    network_policy: Any | None = None

    def with_spawn_depth(self, depth: int) -> SubAgentRuntime:
        return SubAgentRuntime(
            manager=self.manager,
            client=self.client,
            model=self.model,
            config=self.config,
            workspace=self.workspace,
            allow_shell=self.allow_shell,
            auto_approve=self.auto_approve,
            task_manager=self.task_manager,
            cancel_token=self.cancel_token,
            mailbox=self.mailbox,
            hook_executor=self.hook_executor,
            spawn_depth=depth,
            max_spawn_depth=self.max_spawn_depth,
            active_task_id=self.active_task_id,
            approval_handler=self.approval_handler,
            emit_event=self.emit_event,
            trust_mode=self.trust_mode,
            policy=self.policy,
            network_policy=self.network_policy,
        )
