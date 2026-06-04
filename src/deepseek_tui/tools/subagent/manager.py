"""Sub-agent runtime and manager.

Mirrors `crates/tui/src/tools/subagent/mod.rs` (3,604 lines). Provides:

- :class:`SubAgentType` / :class:`SubAgentStatus` / :class:`SubAgentResult`
- :class:`SubAgentManager`: spawn/cancel/result/list/resume/assign/send_input
- ``asyncio.Task``-backed execution (not multiprocessing — LLM calls are
  IO-bound; see HANDOVER.md decision 2026-05-07)
- Persistence under ``<workspace>/.deepseek/subagents.v1.json``

The executor that drives the LLM loop is plugged in at manager
construction; the default is a placeholder that sleeps briefly and
returns a synthetic result (integration debt tracked for Stage 4).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.config.models import Config

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message

from deepseek_tui.tools.subagent.completion import (
    SubAgentCompletion,
    build_completion_payload,
)
from deepseek_tui.tools.subagent.mailbox import Mailbox, MailboxMessage
from deepseek_tui.tools.subagent.output import AgentRunOutput

DEFAULT_MAX_STEPS = 100
DEFAULT_MAX_AGENTS = 10
DEFAULT_MAX_SPAWN_DEPTH = 3
_MAX_TERMINAL_AGENTS_IN_MEMORY = 30
DEFAULT_RESULT_TIMEOUT_MS = 30_000
MIN_WAIT_TIMEOUT_MS = 10_000
MAX_RESULT_TIMEOUT_MS = 3_600_000
SUBAGENT_STATE_SCHEMA_VERSION = 1
SUBAGENT_STATE_FILE = "subagents.v1.json"
SUBAGENT_RESTART_REASON = "Interrupted by process restart"


class SubAgentType(str, Enum):
    GENERAL = "general"
    EXPLORE = "explore"
    PLAN = "plan"
    REVIEW = "review"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    CUSTOM = "custom"

    @staticmethod
    def parse(raw: str) -> SubAgentType | None:
        """Accepts Rust-compatible aliases (general_purpose, worker, etc.)."""
        key = raw.strip().lower().replace("-", "_")
        aliases: dict[str, SubAgentType] = {
            "general": SubAgentType.GENERAL,
            "general_purpose": SubAgentType.GENERAL,
            "worker": SubAgentType.GENERAL,
            "default": SubAgentType.GENERAL,
            "explore": SubAgentType.EXPLORE,
            "exploration": SubAgentType.EXPLORE,
            "explorer": SubAgentType.EXPLORE,
            "plan": SubAgentType.PLAN,
            "planning": SubAgentType.PLAN,
            "awaiter": SubAgentType.PLAN,
            "review": SubAgentType.REVIEW,
            "code_review": SubAgentType.REVIEW,
            "reviewer": SubAgentType.REVIEW,
            "implementer": SubAgentType.IMPLEMENTER,
            "implement": SubAgentType.IMPLEMENTER,
            "implementation": SubAgentType.IMPLEMENTER,
            "builder": SubAgentType.IMPLEMENTER,
            "verifier": SubAgentType.VERIFIER,
            "verify": SubAgentType.VERIFIER,
            "verification": SubAgentType.VERIFIER,
            "validator": SubAgentType.VERIFIER,
            "tester": SubAgentType.VERIFIER,
            "custom": SubAgentType.CUSTOM,
        }
        return aliases.get(key)

    def system_prompt(self) -> str:
        """Return the system prompt for this agent type.

        Mirrors Rust ``SubAgentType::system_prompt`` (mod.rs:227-237).
        """
        from deepseek_tui.prompts import load_prompt

        output_contract = load_prompt("subagent_output_format")
        base = _SUBAGENT_PROMPTS.get(self.value, "")
        return f"{base}\n\n{output_contract}" if base else output_contract


_SUBAGENT_PROMPTS: dict[str, str] = {
    "general": (
        "You are a general-purpose sub-agent spawned to handle a specific task autonomously.\n\n"
        "CRITICAL: File operations are sandboxed to the workspace directory.\n"
        "- ALWAYS use relative paths (e.g., 'script.py', './src/utils.py', 'bubble_sort.py')\n"
        "- NEVER use absolute paths (e.g., '/tmp/...', '/Users/...', '~/...', '/var/...')\n"
        "- If the parent's prompt mentions an absolute path like '/tmp/file.py', ignore the path\n"
        "  and use just the filename 'file.py' instead\n"
        "- All file operations are relative to the workspace root\n\n"
        "Your scope is exactly what the parent assigned to you. Do not expand the\n"
        "objective — if you discover related work that needs doing, surface it under\n"
        "RISKS or BLOCKERS rather than starting it. Work autonomously: the parent is\n"
        "not available to answer questions mid-run.\n\n"
        "Plan before you act. Use `checklist_write` for any multi-step task so your work\n"
        "is visible in the parent's sidebar. For complex initiatives, layer\n"
        "`update_plan` (strategy) above `checklist_write` (tactics)."
    ),
    "explore": (
        "You are an exploration sub-agent. Your job is to map the relevant region\n"
        "of the codebase fast and report what is there. You are read-only by\n"
        "convention — do not write, patch, or run side-effectful commands. If the\n"
        "task seems to require a write, stop and put it under BLOCKERS.\n\n"
        "Method:\n"
        "- Start with `list_dir` and `file_search` to orient.\n"
        "- Use `grep_files` (NOT `exec_shell rg`) to find call sites, type defs,\n"
        "  and string literals. Prefer narrow, structured queries over broad scans.\n"
        "- Read each candidate file with `read_file`. Skim, then quote line ranges.\n"
        "- Stop reading once you have enough evidence — exhaustive sweeps are not\n"
        "  the goal. The parent will spawn a follow-up explorer if needed.\n\n"
        "EVIDENCE is the load-bearing section for explorers. Cite every file you\n"
        "read with `path:line-range` and one line per finding.\n\n"
        "CHANGES will almost always be \"None.\" for an explorer."
    ),
    "plan": (
        "You are a planning sub-agent. Your job is to take an objective and\n"
        "produce a prioritized, executable plan — not to execute it. Keep writes\n"
        "to a minimum (notes and plan artifacts only); avoid patches and shell\n"
        "side effects.\n\n"
        "Method:\n"
        "- Read enough of the codebase to ground the plan in reality.\n"
        "- Decompose the objective into ordered, verifiable steps.\n"
        "- Surface trade-offs explicitly. If two approaches are viable, name both\n"
        "  and pick one with a reason.\n"
        "- Use `update_plan` to record the strategy and `checklist_write` for the backlog.\n\n"
        "Prioritization: order todos by dependency graph first, then by risk/effort ratio.\n"
        "Tag each item with `[P0]` / `[P1]` / `[P2]`."
    ),
    "review": (
        "You are a code review sub-agent. Your job is to read the code under\n"
        "review and emit a severity-scored list of findings. You are read-only by\n"
        "convention — do not patch the code.\n\n"
        "For each finding, score severity: BLOCKER / MAJOR / MINOR / NIT.\n"
        "Order EVIDENCE bullets by severity, BLOCKER first.\n\n"
        "CHANGES will almost always be \"None.\" for a reviewer."
    ),
    "implementer": (
        "You are an implementation sub-agent. Your job is to land the change\n"
        "the parent assigned — write the code, modify the files, satisfy the\n"
        "contract — with the minimum surrounding edit. Do not refactor adjacent code.\n\n"
        "CRITICAL: File operations are sandboxed to the workspace directory.\n"
        "- ALWAYS use relative paths (e.g., 'script.py', './src/utils.py', 'bubble_sort.py')\n"
        "- NEVER use absolute paths (e.g., '/tmp/...', '/Users/...', '~/...', '/var/...')\n"
        "- If the parent's prompt mentions an absolute path like '/tmp/file.py', ignore the path\n"
        "  and use just the filename 'file.py' instead\n"
        "- All file operations are relative to the workspace root\n\n"
        "Method:\n"
        "- Read target file(s) end-to-end before editing.\n"
        "- Prefer `edit_file` for narrow changes, `apply_patch` for multi-hunk.\n"
        "- After edits, run a quick verification (lint/test).\n"
        "- If tests are needed, write them alongside the implementation.\n\n"
        "CHANGES is the load-bearing section — list every file modified with a one-line summary."
    ),
    "verifier": (
        "You are a verification sub-agent. Your job is to run the project's\n"
        "test suite and report pass/fail with evidence. You are read-only —\n"
        "do not patch failing tests or modify code.\n\n"
        "Method:\n"
        "- Run the right gate: `run_tests`, or `exec_shell` for custom commands.\n"
        "- Capture the exact failing assertion plus stack trace in EVIDENCE.\n\n"
        "OUTCOME goes at the top of SUMMARY: PASS / FAIL / FLAKY.\n\n"
        "CHANGES will almost always be \"None.\" for a verifier."
    ),
    "custom": (
        "You are a custom sub-agent. The parent has given you a narrowed tool\n"
        "registry — only the tools you see at runtime are available. Do not try\n"
        "to reach for a tool that is not registered; if the task needs one, put\n"
        "the gap under BLOCKERS and stop.\n\n"
        "CRITICAL: File operations are sandboxed to the workspace directory.\n"
        "- ALWAYS use relative paths (e.g., 'script.py', './src/utils.py', 'bubble_sort.py')\n"
        "- NEVER use absolute paths (e.g., '/tmp/...', '/Users/...', '~/...', '/var/...')\n"
        "- If the parent's prompt mentions an absolute path like '/tmp/file.py', ignore the path\n"
        "  and use just the filename 'file.py' instead\n"
        "- All file operations are relative to the workspace root\n\n"
        "Stay tightly scoped to the assigned objective."
    ),
}


_WHALE_NICKNAMES: tuple[str, ...] = (
    "Blue",
    "Humpback",
    "Sperm",
    "Orca",
    "Beluga",
    "Narwhal",
    "Pilot",
    "Minke",
)


def whale_nickname_for_index(index: int) -> str:
    base = _WHALE_NICKNAMES[index % len(_WHALE_NICKNAMES)]
    if index < len(_WHALE_NICKNAMES):
        return base
    return f"{base} {index // len(_WHALE_NICKNAMES) + 1}"


def build_subagent_system_prompt(
    agent_type: SubAgentType, assignment: SubAgentAssignment
) -> str:
    """Mirror Rust ``build_subagent_system_prompt`` (mod.rs:2629)."""
    base = agent_type.system_prompt()
    role = (assignment.role or "").strip()
    if role:
        return f"{base}\n\nYou are operating in the role of `{role}`."
    return base


class SubAgentStatusKind(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True, frozen=True)
class SubAgentStatus:
    kind: SubAgentStatusKind
    message: str | None = None

    @staticmethod
    def running() -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.RUNNING)

    @staticmethod
    def completed() -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.COMPLETED)

    @staticmethod
    def interrupted(msg: str) -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.INTERRUPTED, msg)

    @staticmethod
    def failed(msg: str) -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.FAILED, msg)

    @staticmethod
    def cancelled() -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.CANCELLED)

    def is_terminal(self) -> bool:
        return self.kind is not SubAgentStatusKind.RUNNING

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind.value}
        if self.message is not None:
            out["message"] = self.message
        return out

    @staticmethod
    def from_dict(data: dict[str, Any]) -> SubAgentStatus:
        return SubAgentStatus(
            SubAgentStatusKind(data["kind"]), data.get("message")
        )


@dataclass(slots=True)
class SubAgentAssignment:
    objective: str
    role: str | None = None


@dataclass(slots=True)
class SubAgentResult:
    agent_id: str
    agent_type: SubAgentType
    assignment: SubAgentAssignment
    model: str
    nickname: str | None
    status: SubAgentStatus
    result: str | None
    steps_taken: int
    duration_ms: int
    from_prior_session: bool = False
    structured: Any | None = None


@dataclass(slots=True)
class SpawnRequest:
    prompt: str
    agent_type: SubAgentType
    assignment: SubAgentAssignment
    allowed_tools: list[str] | None = None
    model: str | None = None
    nickname: str | None = None
    parent_depth: int = 0
    fork_context: bool = False
    fork_messages: list[dict[str, Any]] | None = None
    output_schema: dict[str, Any] | None = None
    auto_approve: bool | None = None


# Executor signature — takes a SubAgent handle plus cancel token.
SubAgentExecutor = Callable[
    ["SubAgent", asyncio.Event], Awaitable[AgentRunOutput | str]
]


async def _stub_executor(agent: SubAgent, cancel: asyncio.Event) -> AgentRunOutput:
    """Placeholder executor — sleeps briefly, returns synthetic summary."""
    try:
        await asyncio.wait_for(cancel.wait(), timeout=0.05)
    except asyncio.TimeoutError:
        agent.steps_taken += 1
        text = f"[stub] agent {agent.id} completed prompt '{agent.prompt[:80]}'"
        return AgentRunOutput(text=text, structured=None)
    raise asyncio.CancelledError


def get_real_subagent_executor() -> SubAgentExecutor:
    """Return the real sub-agent executor that drives Engine turn loops."""
    from deepseek_tui.engine.executors import real_subagent_executor

    return real_subagent_executor


class SubAgent:
    """Single sub-agent handle.

    Mirrors Rust ``SubAgent`` (mod.rs:648-723).
    """

    def __init__(
        self,
        agent_type: SubAgentType,
        prompt: str,
        assignment: SubAgentAssignment,
        model: str,
        nickname: str | None,
        allowed_tools: list[str] | None,
        session_boot_id: str,
        workspace: Path | None = None,
        spawn_depth: int = 0,
        fork_messages: list[dict[str, Any]] | None = None,
        parent_cancel: asyncio.Event | None = None,
        mailbox: Mailbox | None = None,
        loop_runtime: SubAgentRuntime | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> None:
        self.id: str = f"agent_{uuid.uuid4().hex[:8]}"
        self.agent_type = agent_type
        self.prompt = prompt
        self.assignment = assignment
        self.model = model
        self.nickname = nickname
        self.status: SubAgentStatus = SubAgentStatus.running()
        self.result: str | None = None
        self.structured_result: Any | None = None
        self.output_schema = output_schema
        self.steps_taken: int = 0
        self.started_at_ms: int = _epoch_ms()
        self.allowed_tools = allowed_tools
        self.session_boot_id = session_boot_id
        self.workspace = workspace or Path.cwd()
        self.spawn_depth = spawn_depth
        self.fork_messages = fork_messages
        self.parent_cancel = parent_cancel
        self.mailbox = mailbox
        self.loop_runtime = loop_runtime
        self.cancel_token: asyncio.Event = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.input_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    def snapshot(self) -> SubAgentResult:
        duration_ms = max(0, _epoch_ms() - self.started_at_ms)
        return SubAgentResult(
            agent_id=self.id,
            agent_type=self.agent_type,
            assignment=self.assignment,
            model=self.model,
            nickname=self.nickname,
            status=self.status,
            result=self.result,
            steps_taken=self.steps_taken,
            duration_ms=duration_ms,
            from_prior_session=False,
            structured=self.structured_result,
        )


class SubAgentManager:
    """Manager for in-process sub-agents.

    Mirrors Rust ``SubAgentManager`` (mod.rs:726-). Runs agents as
    :class:`asyncio.Task` rather than multiprocessing subprocesses —
    LLM calls are IO-bound and Rust itself uses tokio::spawn.
    """

    def __init__(
        self,
        workspace: Path,
        max_agents: int = DEFAULT_MAX_AGENTS,
        state_path: Path | None = None,
        executor: SubAgentExecutor | None = None,
        mailbox: Mailbox | None = None,
        default_model: str = "deepseek-chat",
    ) -> None:
        self.workspace = workspace
        self.max_agents = max_agents
        self.max_steps = DEFAULT_MAX_STEPS
        self.default_model = default_model
        self._state_path = state_path
        self._executor: SubAgentExecutor = executor or _stub_executor
        self._mailbox = mailbox
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
        """Wire shared client/config for ``run_subagent_loop`` (Rust SubAgentRuntime)."""
        self._loop_runtime = runtime

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
                workspace=self.workspace,
                spawn_depth=child_depth,
                fork_messages=request.fork_messages if request.fork_context else None,
                parent_cancel=self._parent_cancel,
                mailbox=self._mailbox,
                loop_runtime=self._loop_runtime_for_spawn(request, child_depth),
                output_schema=request.output_schema,
            )
            self._agents[agent.id] = agent
            snapshot = agent.snapshot()
            self._persist_best_effort()

        if self._mailbox is not None:
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

    async def assign(
        self,
        agent_id: str,
        objective: str | None = None,
        role: str | None = None,
        message: str | None = None,
        interrupt: bool = False,
    ) -> SubAgentResult:
        async with self._lock:
            agent = self._require_agent(agent_id)
            if objective is not None:
                agent.assignment = SubAgentAssignment(
                    objective=objective, role=role or agent.assignment.role
                )
            elif role is not None:
                agent.assignment = SubAgentAssignment(
                    objective=agent.assignment.objective, role=role
                )
            snapshot = agent.snapshot()
        if message is not None:
            await self.send_input(agent_id, message, interrupt=interrupt)
        return snapshot

    async def resume(self, agent_id: str) -> SubAgentResult:
        """Re-open a terminated agent for a new prompt.

        Mirrors Rust ``SubAgentManager::resume`` — resurrects the status
        back to Running and re-spawns the driver task.
        """
        async with self._lock:
            agent = self._require_agent(agent_id)
            if agent.status.kind is SubAgentStatusKind.RUNNING:
                raise RuntimeError(f"Agent {agent_id} is already running")
            agent.status = SubAgentStatus.running()
            agent.result = None
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
        if self._parent_cancel is not None and self._parent_cancel.is_set():
            agent.cancel_token.set()
        try:
            result = await self._executor(agent, agent.cancel_token)
        except asyncio.CancelledError:
            async with self._lock:
                if agent.status.kind is SubAgentStatusKind.RUNNING:
                    agent.status = SubAgentStatus.cancelled()
                self._persist_best_effort()
            if self._mailbox is not None:
                self._mailbox.send(MailboxMessage.cancelled(agent.id))
            self._notify_parent_completion(agent)
            return
        except Exception as exc:  # noqa: BLE001 — translate to Failed status
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

        if self._mailbox is not None:
            if agent.status.kind is SubAgentStatusKind.CANCELLED:
                self._mailbox.send(MailboxMessage.cancelled(agent.id))
            else:
                summary = (agent.result or "")[:500] if agent.result else ""
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
            # Match Rust's eprintln! best-effort behavior.
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
            # Running on disk → Interrupted on load (Rust parity).
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

    Rust analogue: ``SubAgentRuntime`` (mod.rs:587). All depths share
    :attr:`manager`; children increment :attr:`spawn_depth` only.
    """

    manager: SubAgentManager
    client: Any
    model: str
    config: Config
    workspace: Path
    allow_shell: bool = True
    auto_approve: bool = True
    task_manager: Any = None
    cancel_token: asyncio.Event = field(default_factory=asyncio.Event)
    mailbox: Mailbox | None = None
    spawn_depth: int = 0
    max_spawn_depth: int = DEFAULT_MAX_SPAWN_DEPTH

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
        )


        raise


# --- sub-agent LLM loop (mirrors Rust ``run_subagent``) --------------------


def _subagent_cancelled(
    cancel: asyncio.Event,
    agent: SubAgent,
) -> bool:
    if cancel.is_set() or agent.cancel_token.is_set():
        return True
    return agent.parent_cancel is not None and agent.parent_cancel.is_set()


def _reject_subagent_interactive_shell(tool_name: str, input_data: dict[str, Any]) -> None:
    if tool_name != "exec_shell":
        return
    if input_data.get("interactive") is True:
        raise RuntimeError(
            "Sub-agents cannot use exec_shell with interactive=true "
            "(would take over the parent TUI terminal)"
        )


async def _execute_subagent_tool(
    registry: object,
    context: object,
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    auto_approve: bool,
) -> str:
    from deepseek_tui.tools.base import ApprovalRequirement, ToolError
    from deepseek_tui.tools.registry import ToolRegistry

    assert isinstance(registry, ToolRegistry)
    _reject_subagent_interactive_shell(tool_name, tool_input)
    tool = registry.get(tool_name)
    if not auto_approve and tool.approval_requirement() != ApprovalRequirement.AUTO:
        return (
            f"Error: Tool {tool_name} requires approval and cannot run "
            "inside this sub-agent unless the parent session is auto-approved"
        )
    try:
        result = await registry.execute(tool_name, tool_input, context)  # type: ignore[arg-type]
        if not result.success:
            return f"Error: {result.content}"
        return result.content
    except ToolError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def _structured_output_contract() -> str:
    return (
        "Final output contract:\n"
        "- Your final action MUST be a structured_output tool call.\n"
        "- The structured_output arguments are the return value of this subagent.\n"
        "- Do not emit a prose final answer instead of structured_output.\n"
        "- If you need to inspect files or run commands first, do so, then call "
        "structured_output exactly once."
    )


async def run_subagent_loop(
    agent: SubAgent,
    runtime: SubAgentRuntime,
    cancel: asyncio.Event,
) -> AgentRunOutput:
    """Drive one sub-agent to completion without nesting a full Engine."""
    from deepseek_tui.engine.turn_loop import TurnLoop
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.requests import MessageRequest
    from deepseek_tui.tools.builder import build_subagent_registry
    from deepseek_tui.tools.context import ToolContext
    from deepseek_tui.tools.structured_output_tool import (
        STRUCTURED_OUTPUT_TOOL_NAME,
        StructuredOutputTool,
    )
    from deepseek_tui.tools.subagent.mailbox import MailboxMessage

    system_prompt = build_subagent_system_prompt(agent.agent_type, agent.assignment)
    extra_tools = []
    if agent.output_schema:
        extra_tools.append(StructuredOutputTool(agent.output_schema))
        system_prompt = f"{system_prompt}\n\n{_structured_output_contract()}"
    registry = build_subagent_registry(
        runtime.config,
        allowed_tools=agent.allowed_tools,
        client=runtime.client,
        root_model=agent.model,
        extra_tools=extra_tools or None,
    )
    context = ToolContext(
        working_directory=agent.workspace,
        trust_mode=False,
        task_manager=runtime.task_manager,
        subagent_manager=runtime.manager,
        metadata={
            "subagent_depth": agent.spawn_depth,
            "subagent_runtime": runtime,
            "auto_approve": runtime.auto_approve,
        },
    )
    from deepseek_tui.execpolicy.sandbox import sandbox_policy_for_mode

    context.execution_sandbox_policy = sandbox_policy_for_mode(
        "agent",
        agent.workspace,
    )
    registry.set_context(context)
    api_tools = registry.to_api_tools()

    messages: list[Message] = []
    if agent.fork_messages:
        messages.extend(_messages_from_fork_dicts(agent.fork_messages))
    messages.append(Message.user(agent.prompt))

    turn_loop = TurnLoop(runtime.client)
    final_text = ""
    structured_value: Any | None = None
    steps = 0
    last_usage: object | None = None

    async def _noop_emit(_event: object) -> None:
        return None

    for _ in range(DEFAULT_MAX_STEPS):
        if _subagent_cancelled(cancel, agent):
            raise asyncio.CancelledError

        steps += 1
        agent.steps_taken = steps

        request = MessageRequest(
            model=agent.model,
            messages=messages,
            system_prompt=system_prompt,
            tools=api_tools,
            tool_choice={"type": "auto"} if api_tools else None,
            max_tokens=4096,
            stream=True,
        )
        result = await turn_loop.run(
            request,
            _noop_emit,
            cancel,
            tools=api_tools,
        )

        if result.usage is not None:
            last_usage = result.usage

        if result.cancelled:
            raise asyncio.CancelledError

        if result.assistant_message is not None:
            messages.append(result.assistant_message)

        text_parts: list[str] = []
        if result.assistant_message is not None:
            for block in result.assistant_message.content:
                if block.type == "text":
                    text_parts.append(block.text)
        if text_parts:
            final_text = "".join(text_parts).strip()

        if not result.tool_calls:
            break

        from deepseek_tui.protocol.messages import ToolUseBlock

        messages.append(
            Message.assistant_with_tools(
                [
                    ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments)
                    for tc in result.tool_calls
                ]
            )
        )

        for tc in result.tool_calls:
            if runtime.mailbox is not None:
                runtime.mailbox.send(
                    MailboxMessage.tool_call_started(agent.id, tc.name, steps)
                )
            if tc.name == STRUCTURED_OUTPUT_TOOL_NAME:
                tool_result = await registry.execute(tc.name, tc.arguments, context)
                output = (
                    tool_result.content
                    if tool_result.success
                    else f"Error: {tool_result.content}"
                )
                ok = tool_result.success
                if ok and tool_result.metadata.get("terminate_subagent"):
                    structured_value = tool_result.metadata.get("value")
            else:
                output = await _execute_subagent_tool(
                    registry,
                    context,
                    tool_name=tc.name,
                    tool_input=tc.arguments,
                    auto_approve=runtime.auto_approve,
                )
                ok = not output.startswith("Error:")
            if runtime.mailbox is not None:
                runtime.mailbox.send(
                    MailboxMessage.tool_call_completed(
                        agent.id, tc.name, steps, ok
                    )
                )
            messages.append(Message.tool_result(tc.id, output, is_error=not ok))
            if structured_value is not None:
                break
        if structured_value is not None:
            break

    if runtime.mailbox is not None and last_usage is not None:
        runtime.mailbox.send(
            MailboxMessage.token_usage(
                agent.id,
                agent.model,
                {
                    "input_tokens": getattr(last_usage, "input_tokens", 0),
                    "output_tokens": getattr(last_usage, "output_tokens", 0),
                    "reasoning_tokens": getattr(last_usage, "reasoning_tokens", 0),
                },
            )
        )

    agent.steps_taken = steps
    if agent.output_schema and structured_value is None:
        raise RuntimeError("sub-agent did not return structured_output")
    return AgentRunOutput(text=final_text, structured=structured_value)


def _messages_from_fork_dicts(raw_messages: list[dict[str, Any]]) -> list[Message]:
    from deepseek_tui.protocol.messages import Message

    out: list[Message] = []
    for item in raw_messages:
        try:
            out.append(Message.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    return out


# --- helpers ----------------------------------------------------------------


def _epoch_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
