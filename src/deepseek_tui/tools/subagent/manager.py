"""SubAgentManager — spawn/cancel/result/list/resume/send_input.

``asyncio.Task``-backed
execution (not multiprocessing — LLM calls are IO-bound; see HANDOVER.md
decision 2026-05-07). Persistence under
``<workspace>/.deepseek/subagents.v1.json``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import Config
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
    DEFAULT_MAX_STEPS,
    SUBAGENT_RESTART_REASON,
    SUBAGENT_STATE_SCHEMA_VERSION,
    _MAX_CARD_RESULT_CHARS,
    _MAX_TERMINAL_AGENTS_IN_MEMORY,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentStatusKind,
    SubAgentType,
    _epoch_ms,
    whale_nickname_for_index,
)

logger = logging.getLogger(__name__)


def _write_json_atomic(path: Path, value: Any) -> None:
    from deepseek_tui.utils import write_json_atomic

    write_json_atomic(path, value)


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
        self.max_steps = DEFAULT_MAX_STEPS
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
        self._agents: dict[str, SubAgent] = {}
        self._lock = asyncio.Lock()
        self._session_boot_id: str = f"boot_{uuid.uuid4().hex[:12]}"
        self._parent_cancel: asyncio.Event | None = None
        self._parent_completion_sink: Callable[[SubAgentCompletion], None] | None = (
            None
        )
        self._loop_runtime: SubAgentRuntime | None = None
        if state_path is not None:
            self._load_state()

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
        for agent in self._agents.values():
            from_prior = self._is_from_prior_session(agent)
            if from_prior and not include_archived:
                continue
            snap = agent.snapshot()
            # Synthesize the from_prior_session flag manager-side.
            snap = SubAgentResult(
                agent_id=snap.agent_id,
                agent_type=snap.agent_type,
                assignment=snap.assignment,
                model=snap.model,
                nickname=snap.nickname,
                status=snap.status,
                result=snap.result,
                steps_taken=snap.steps_taken,
                duration_ms=snap.duration_ms,
                from_prior_session=from_prior,
            )
            out.append(snap)
        return out

    def list_agents(self) -> list[SubAgentResult]:
        return self.list_filtered(include_archived=False)

    def _loop_runtime_for_spawn(
        self, request: SpawnRequest, child_depth: int
    ) -> SubAgentRuntime | None:
        if self._loop_runtime is None:
            return None
        from dataclasses import replace

        rt = self._loop_runtime.with_spawn_depth(child_depth)
        if request.auto_approve is not None:
            rt = replace(rt, auto_approve=request.auto_approve)
        return rt

    async def spawn(self, request: SpawnRequest) -> SubAgentResult:
        async with self._lock:
            if self.running_count() >= self.max_agents:
                raise RuntimeError(
                    f"Too many sub-agents running ({self.max_agents} cap)"
                )
            child_depth = request.parent_depth + 1
            if child_depth > DEFAULT_MAX_SPAWN_DEPTH:
                raise RuntimeError(
                    f"max sub-agent spawn depth exceeded "
                    f"({DEFAULT_MAX_SPAWN_DEPTH}); refusing nested spawn at "
                    f"depth {child_depth}"
                )
            agent = SubAgent(
                agent_type=request.agent_type,
                prompt=request.prompt,
                assignment=request.assignment,
                model=request.model or self.default_model,
                nickname=request.nickname
                or whale_nickname_for_index(len(self._agents)),
                allowed_tools=request.allowed_tools,
                session_boot_id=self._session_boot_id,
                workspace=request.workspace or self.workspace,
                spawn_depth=child_depth,
                fork_messages=request.fork_messages if request.fork_context else None,
                parent_cancel=self._parent_cancel,
                mailbox=self._mailbox,
                loop_runtime=self._loop_runtime_for_spawn(request, child_depth),
                output_schema=request.output_schema,
                system_prompt=request.system_prompt,
                background=request.background,
            )
            self._agents[agent.id] = agent
            snapshot = agent.snapshot()
            self._persist_best_effort()

        if self._mailbox is not None:
            parent_id = (request.parent_agent_id or "").strip()
            if parent_id:
                self._mailbox.send(
                    MailboxMessage.child_spawned(parent_id, agent.id)
                )
            self._mailbox.send(
                MailboxMessage.started(agent.id, request.agent_type.value)
            )
        agent.task = asyncio.create_task(self._drive_agent(agent))
        return snapshot

    async def get_result(self, agent_id: str) -> SubAgentResult:
        async with self._lock:
            agent = self._require_agent(agent_id)
            return agent.snapshot()

    async def cancel(self, agent_id: str) -> SubAgentResult:
        task: asyncio.Task[None] | None = None
        async with self._lock:
            agent = self._require_agent(agent_id)
            agent.cancel_token.set()
            task = agent.task
            if agent.status.kind is SubAgentStatusKind.RUNNING:
                agent.status = SubAgentStatus.cancelled()
            self._persist_best_effort()
            snapshot = agent.snapshot()

        if self._mailbox is not None:
            self._mailbox.send(MailboxMessage.cancelled(agent_id))
        if task is not None and not task.done():
            task.cancel()
        return snapshot

    async def send_input(
        self, agent_id: str, text: str, interrupt: bool = False
    ) -> None:
        async with self._lock:
            agent = self._require_agent(agent_id)
            if agent.status.kind is not SubAgentStatusKind.RUNNING:
                raise RuntimeError(
                    f"Cannot send input to {agent_id}: {agent.status.kind.value}"
                )
        await agent.input_queue.put((text, interrupt))

    async def resume(self, agent_id: str) -> SubAgentResult:
        """True-resume a terminated agent from its durable transcript.

        Reopens status to Running and re-spawns the driver. The loop hydrates
        any checkpoint under ``.deepseek/subagent-runs/<id>/``; without a
        transcript it restarts from the original prompt (legacy behavior).
        """
        async with self._lock:
            agent = self._require_agent(agent_id)
            if agent.status.kind is SubAgentStatusKind.RUNNING:
                raise RuntimeError(f"Agent {agent_id} is already running")
            if agent.status.kind is SubAgentStatusKind.COMPLETED:
                raise RuntimeError(
                    f"Agent {agent_id} already completed; spawn a new agent instead"
                )
            agent.status = SubAgentStatus.running()
            agent.result = None
            agent.structured_result = None
            agent.cancel_token = asyncio.Event()
            agent.started_at_ms = _epoch_ms()
            self._persist_best_effort()
            snapshot = agent.snapshot()

        if self._mailbox is not None:
            self._mailbox.send(
                MailboxMessage.started(agent_id, agent.agent_type.value)
            )
        agent.task = asyncio.create_task(self._drive_agent(agent))
        return snapshot

    async def close(self, agent_id: str) -> SubAgentResult:
        """Terminate and remove an agent from the active map."""
        snapshot = await self.cancel(agent_id)
        async with self._lock:
            self._agents.pop(agent_id, None)
            self._persist_best_effort()
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
            await asyncio.sleep(min(0.05, remaining))

    def known_agent_ids(self) -> set[str]:
        """Snapshot the ids of every agent currently tracked.

        Used by a turn's monitor at start-up to tag pre-existing agents as
        *foreign*: turns are serial per thread, so any agent already present
        when a turn begins was spawned by an earlier turn and must not have
        its mailbox events re-attributed to the new turn.
        """
        return set(self._agents)

    async def shutdown(self) -> None:
        """Cancel and join every running agent."""
        async with self._lock:
            agents = list(self._agents.values())
        for agent in agents:
            agent.cancel_token.set()
        for agent in agents:
            if agent.task is not None and not agent.task.done():
                agent.task.cancel()
                try:
                    await agent.task
                except (asyncio.CancelledError, BaseException):  # noqa: BLE001
                    pass

    # --- internal ------------------------------------------------------

    def _require_agent(self, agent_id: str) -> SubAgent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent: {agent_id}")
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
        logger.info("subagent_drive_start id=%s type=%s depth=%d", agent.id, agent.agent_type.value, agent.spawn_depth)
        if self._parent_cancel is not None and self._parent_cancel.is_set():
            agent.cancel_token.set()
        try:
            result = await self._executor(agent, agent.cancel_token)
        except asyncio.CancelledError:
            logger.info("subagent_drive_cancelled id=%s", agent.id)
            async with self._lock:
                if agent.status.kind is SubAgentStatusKind.RUNNING:
                    agent.status = SubAgentStatus.cancelled()
                self._persist_best_effort()
            if self._mailbox is not None:
                self._mailbox.send(MailboxMessage.cancelled(agent.id))
            self._notify_parent_completion(agent)
            return
        except Exception as exc:  # noqa: BLE001 — translate to Failed status
            logger.error("subagent_drive_failed id=%s error=%s", agent.id, exc)
            async with self._lock:
                agent.status = SubAgentStatus.failed(str(exc))
                self._persist_best_effort()
            if self._mailbox is not None:
                self._mailbox.send(MailboxMessage.failed(agent.id, str(exc)))
            self._notify_parent_completion(agent)
            return

        async with self._lock:
            if agent.cancel_token.is_set():
                if agent.status.kind is SubAgentStatusKind.RUNNING:
                    agent.status = SubAgentStatus.cancelled()
            else:
                agent.status = SubAgentStatus.completed()
                if isinstance(result, AgentRunOutput):
                    agent.result = result.text
                    agent.structured_result = result.structured
                else:
                    agent.result = str(result) if result is not None else None
                    agent.structured_result = None
            self._persist_best_effort()

        logger.info(
            "subagent_drive_done id=%s status=%s steps=%d",
            agent.id, agent.status.kind.value, agent.steps_taken,
        )
        if self._mailbox is not None:
            if agent.status.kind is SubAgentStatusKind.CANCELLED:
                self._mailbox.send(MailboxMessage.cancelled(agent.id))
            else:
                summary = (agent.result or "")[:_MAX_CARD_RESULT_CHARS] if agent.result else ""
                self._mailbox.send(MailboxMessage.completed(agent.id, summary))

        self._notify_parent_completion(agent)
        await self._evict_terminal_agents()

    async def _evict_terminal_agents(self) -> None:
        async with self._lock:
            terminal = [
                (aid, a) for aid, a in self._agents.items()
                if a.status.kind is not SubAgentStatusKind.RUNNING
            ]
            if len(terminal) <= _MAX_TERMINAL_AGENTS_IN_MEMORY:
                return
            terminal.sort(key=lambda x: x[1].started_at_ms or 0)
            to_remove = len(terminal) - _MAX_TERMINAL_AGENTS_IN_MEMORY
            for aid, _ in terminal[:to_remove]:
                del self._agents[aid]
            self._persist_best_effort()

    def _persist_best_effort(self) -> None:
        if self._state_path is None:
            return
        try:
            self._persist_state()
        except Exception as exc:  # noqa: BLE001
            # Best-effort logging.
            print(f"Failed to persist sub-agent state: {exc}")

    def _persist_state(self) -> None:
        if self._state_path is None:
            return
        now_ms = _epoch_ms()
        agents_payload = []
        for agent in sorted(self._agents.values(), key=lambda a: a.id):
            agents_payload.append(
                {
                    "id": agent.id,
                    "agent_type": agent.agent_type.value,
                    "prompt": agent.prompt,
                    "assignment": {
                        "objective": agent.assignment.objective,
                        "role": agent.assignment.role,
                    },
                    "model": agent.model,
                    "nickname": agent.nickname,
                    "status": agent.status.to_dict(),
                    "result": agent.result,
                    "steps_taken": agent.steps_taken,
                    "duration_ms": max(0, now_ms - agent.started_at_ms),
                    "allowed_tools": agent.allowed_tools or [],
                    "updated_at_ms": now_ms,
                    "session_boot_id": agent.session_boot_id,
                    "spawn_depth": agent.spawn_depth,
                }
            )
        payload = {
            "schema_version": SUBAGENT_STATE_SCHEMA_VERSION,
            "agents": agents_payload,
        }
        _write_json_atomic(self._state_path, payload)

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        data = json.loads(self._state_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SUBAGENT_STATE_SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported sub-agent state schema {data.get('schema_version')}"
            )
        self._agents.clear()
        for raw in data.get("agents", []):
            agent = SubAgent(
                agent_type=SubAgentType(raw["agent_type"]),
                prompt=raw["prompt"],
                assignment=SubAgentAssignment(
                    objective=raw["assignment"]["objective"],
                    role=raw["assignment"].get("role"),
                ),
                model=raw.get("model", self.default_model),
                nickname=raw.get("nickname"),
                allowed_tools=raw.get("allowed_tools") or None,
                session_boot_id=raw.get("session_boot_id", ""),
                workspace=self.workspace,
                spawn_depth=int(raw.get("spawn_depth", 0) or 0),
            )
            # Restore id from persisted record, overwriting the freshly
            # generated one.
            agent.id = raw["id"]
            # Running on disk → Interrupted on load.
            status = SubAgentStatus.from_dict(raw["status"])
            if status.kind is SubAgentStatusKind.RUNNING:
                status = SubAgentStatus.interrupted(SUBAGENT_RESTART_REASON)
            agent.status = status
            agent.result = raw.get("result")
            agent.steps_taken = raw.get("steps_taken", 0)
            duration_ms = raw.get("duration_ms", 0)
            agent.started_at_ms = _epoch_ms() - max(0, int(duration_ms))
            self._agents[agent.id] = agent


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
    # Secure default: children do NOT auto-approve unless the parent session
    # explicitly opts in (mirrors the task system's GHSA default). The engine
    # always passes the resolved value from ``approval_handler``.
    auto_approve: bool = False
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

    def would_exceed_depth(self) -> bool:
        return self.spawn_depth + 1 > self.max_spawn_depth

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
            spawn_depth=depth,
            max_spawn_depth=self.max_spawn_depth,
            active_task_id=self.active_task_id,
            approval_handler=self.approval_handler,
            emit_event=self.emit_event,
        )

    def child(self) -> SubAgentRuntime:
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
            spawn_depth=self.spawn_depth + 1,
            max_spawn_depth=self.max_spawn_depth,
            active_task_id=self.active_task_id,
            approval_handler=self.approval_handler,
            emit_event=self.emit_event,
        )
