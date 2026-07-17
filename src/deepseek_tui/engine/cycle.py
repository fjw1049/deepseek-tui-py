"""Cycle tracking and session activity.

Consolidates cycle_manager.py and session_activity.py. Manages
long-running session context by archiving full conversation cycles to
disk and producing compact briefings for fresh context windows.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
import asyncio
import logging
from collections.abc import Callable

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.protocol.messages import Message

CYCLE_ARCHIVE_SCHEMA_VERSION = 1
DEFAULT_BRIEFING_MAX_TOKENS = 3_000
APPROX_CHARS_PER_TOKEN = 4

CYCLE_HANDOFF_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "cycle_handoff.md"


@dataclass(slots=True)
class CycleConfig:
    """Configuration for cycle boundaries (ratio of model window)."""

    enabled: bool = True
    cycle_ratio: float = 0.90
    briefing_max_tokens: int = DEFAULT_BRIEFING_MAX_TOKENS
    per_model: dict[str, ModelCycleConfig] = field(default_factory=dict)

    def briefing_max_for(self, model: str) -> int:
        if model in self.per_model:
            return self.per_model[model].briefing_max_tokens
        return self.briefing_max_tokens


@dataclass(slots=True)
class ModelCycleConfig:
    """Per-model cycle tuning."""

    briefing_max_tokens: int = DEFAULT_BRIEFING_MAX_TOKENS


@dataclass(slots=True)
class CycleBriefing:
    """Snapshot of a model-curated briefing produced at cycle handoff."""

    cycle: int
    timestamp: int  # Unix epoch
    briefing_text: str
    token_estimate: int


@dataclass(slots=True)
class CycleArchiveHeader:
    """JSONL header record for an archived cycle file."""

    schema_version: int = CYCLE_ARCHIVE_SCHEMA_VERSION
    cycle: int = 0
    session_id: str = ""
    model: str = ""
    started: int = 0
    ended: int = 0
    message_count: int = 0


@dataclass(slots=True)
class StructuredState:
    """Roll-up of state that survives a cycle boundary deterministically."""

    mode_label: str = ""
    workspace: str = ""
    cwd: str | None = None
    working_set_summary: str | None = None
    todo_snapshot: list[dict[str, Any]] | None = None
    plan_snapshot: list[dict[str, Any]] | None = None
    subagent_snapshots: list[dict[str, Any]] = field(default_factory=list)

    def to_system_block(self) -> str | None:
        """Render structured state as a text block for seed messages."""
        out: list[str] = ["## Cycle State (Auto-Preserved)\n"]
        out.append(f"- Mode: `{self.mode_label}`")
        out.append(f"- Workspace: `{self.workspace}`")
        if self.cwd:
            out.append(f"- Cwd: `{self.cwd}`")

        if self.plan_snapshot:
            out.append("\n### Plan")
            for item in self.plan_snapshot:
                status = item.get("status", "pending")
                marker = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(
                    status, "[ ]"
                )
                out.append(f"- {marker} {item.get('step', '')}")

        if self.todo_snapshot:
            out.append("\n### Todos")
            for item in self.todo_snapshot:
                status = item.get("status", "pending")
                marker = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(
                    status, "[ ]"
                )
                out.append(f"- {marker} {item.get('content', '')}")

        if self.subagent_snapshots:
            out.append("\n### Open Sub-Agents")
            for s in self.subagent_snapshots:
                agent_id = s.get("agent_id", "?")
                role = s.get("role", "—")
                goal = s.get("objective", "(no objective)")
                out.append(f"- `{agent_id}` (role: {role}) — {goal}")

        if self.working_set_summary:
            out.append(f"\n{self.working_set_summary}")

        return "\n".join(out)


# ===========================================================================
# Core functions
# ===========================================================================


def should_advance_cycle(
    active_input_tokens: int,
    reserved_headroom_tokens: int,
    model: str,
    config: CycleConfig,
    in_flight: bool,
) -> bool:
    """Determine if a cycle boundary should fire (ratio ≥ cycle_ratio)."""
    if not config.enabled or in_flight:
        return False
    from deepseek_tui.config.providers import context_window_for_model

    window = max(1, int(context_window_for_model(model) or 128_000))
    # reserved_headroom_tokens kept for API compat; ratio already leaves room.
    _ = reserved_headroom_tokens
    ratio = active_input_tokens / window
    return ratio >= float(config.cycle_ratio or 0.90)


def extract_carry_forward(raw: str) -> str:
    """Extract <carry_forward>...</carry_forward> block from model output."""
    lower = raw.lower()
    open_tag = "<carry_forward>"
    close_tag = "</carry_forward>"

    start = lower.find(open_tag)
    if start != -1:
        after = start + len(open_tag)
        tail = raw[after:]
        tail_lower = lower[after:]
        end = tail_lower.find(close_tag)
        if end != -1:
            return tail[:end].strip()
        return tail.strip()
    return raw.strip()


def enforce_briefing_cap(text: str, max_tokens: int) -> str:
    """Defensive bound on briefing length (~4 chars/token)."""
    max_chars = max_tokens * APPROX_CHARS_PER_TOKEN
    if max_chars == 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[...briefing truncated to fit cap...]"


async def produce_briefing(
    client: LLMClient,
    model: str,
    conversation: list[Message],
    max_briefing_tokens: int,
) -> str:
    """Run the briefing turn to produce a <carry_forward> block."""
    if not conversation:
        return ""

    handoff_template = _load_handoff_template()

    from deepseek_tui.protocol.messages import Message as Msg
    from deepseek_tui.protocol.messages import MessageRequest
    from deepseek_tui.protocol.responses import StreamTextDelta

    messages = list(conversation)
    messages.append(
        Msg.user(
            f"[CYCLE BOUNDARY] The next turn starts in a fresh context.\n\n"
            f"Produce your `<carry_forward>` block now. "
            f"Stay under {max_briefing_tokens} tokens. "
            f"Output only the block — no other text."
        )
    )

    request = MessageRequest(
        model=model,
        messages=messages,
        system_prompt=handoff_template,
        max_tokens=min(max_briefing_tokens * 2, 8192),
        temperature=0.2,
    )

    result_text: list[str] = []
    async for event in client.stream_chat_completion(request):
        if isinstance(event, StreamTextDelta):
            result_text.append(event.text)

    raw = "".join(result_text)
    extracted = extract_carry_forward(raw)
    return enforce_briefing_cap(extracted, max_briefing_tokens)


def archive_cycle(
    session_id: str,
    cycle_n: int,
    messages: list[Message],
    model: str,
    started: int,
) -> Path:
    """Archive a cycle's messages to JSONL on disk."""
    archive_dir = _archive_dir_for(session_id)
    archive_dir.mkdir(parents=True, exist_ok=True)

    path = archive_dir / f"{cycle_n}.jsonl"
    header = CycleArchiveHeader(
        schema_version=CYCLE_ARCHIVE_SCHEMA_VERSION,
        cycle=cycle_n,
        session_id=session_id,
        model=model,
        started=started,
        ended=int(time.time()),
        message_count=len(messages),
    )

    tmp_path = path.with_suffix(".jsonl.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(_header_to_dict(header)) + "\n")
        for msg in messages:
            f.write(json.dumps(_message_to_dict(msg)) + "\n")
    tmp_path.rename(path)
    return path


def build_seed_messages(
    structured_state_block: str | None,
    briefing: CycleBriefing | None,
    pending_user_message: str | None,
) -> list[dict[str, str]]:
    """Compose seed messages for the next cycle.

    Seeds are user-role carriers only — never fake assistant acknowledgements.
    ``pending_user_message`` should be the last real user goal so the next
    cycle does not lose the objective.
    """
    from deepseek_tui.engine.context_pressure import (
        format_user_query_message,
        wrap_system_reminder,
    )

    out: list[dict[str, str]] = []
    seed_parts: list[str] = []

    if structured_state_block and structured_state_block.strip():
        seed_parts.append(
            "[CYCLE STATE — auto-preserved across the cycle boundary]\n\n"
            + structured_state_block.strip()
        )

    if briefing and briefing.briefing_text.strip():
        from datetime import datetime, timezone

        ts = datetime.fromtimestamp(briefing.timestamp, tz=timezone.utc).isoformat()
        seed_parts.append(
            f"[CYCLE BRIEFING — written by you on cycle {briefing.cycle} at {ts}]\n\n"
            f"<carry_forward>\n{briefing.briefing_text.strip()}\n</carry_forward>"
        )

    if seed_parts:
        out.append({
            "role": "user",
            "content": wrap_system_reminder("\n\n".join(seed_parts)),
            "origin": "cycle_seed",
        })

    if pending_user_message and pending_user_message.strip():
        out.append({
            "role": "user",
            "content": format_user_query_message(pending_user_message),
            "origin": "real_user",
        })

    return out


# ===========================================================================
# Helpers
# ===========================================================================


def _archive_dir_for(session_id: str) -> Path:
    from deepseek_tui.config.paths import user_session_cycles_dir

    return user_session_cycles_dir(session_id)


def _load_handoff_template() -> str:
    try:
        return CYCLE_HANDOFF_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return "Produce a <carry_forward> block summarizing the session state."


def _header_to_dict(header: CycleArchiveHeader) -> dict[str, Any]:
    return {
        "schema_version": header.schema_version,
        "cycle": header.cycle,
        "session_id": header.session_id,
        "model": header.model,
        "started": header.started,
        "ended": header.ended,
        "message_count": header.message_count,
    }


def _message_to_dict(msg: Any) -> dict[str, Any]:
    if hasattr(msg, "to_dict"):
        return msg.to_dict()
    if hasattr(msg, "role") and hasattr(msg, "content"):
        content = msg.content
        if isinstance(content, list):
            blocks = []
            for b in content:
                if hasattr(b, "text"):
                    blocks.append({"type": "text", "text": b.text})
                else:
                    blocks.append(str(b))
            return {"role": msg.role, "content": blocks}
        return {"role": msg.role, "content": str(content)}
    return {"role": "unknown", "content": str(msg)}


# Session-level activity coordinator — mailbox drain + task polling.
# Decouples background work observability from a single parent turn so the TUI
# can keep updating after ``TurnComplete`` when tasks or late mailbox events
# arrive.
# Important: started only from :meth:`Engine.run`, not ``Engine.create``, so
# unit tests that construct an engine without a consumer do not spawn a forever
# background loop.


from deepseek_tui.engine.events import (
    SessionActivityEvent,
    SubAgentMailboxEvent,
)
from deepseek_tui.tools.subagent import Mailbox

if TYPE_CHECKING:
    from deepseek_tui.engine.orchestrator import Engine

logger = logging.getLogger(__name__)

EmitFn = Callable[..., bool]
PollIntervalSecs = 0.4


class SessionActivityCoordinator:
    """Drain sub-agent mailbox and poll task queue for live UI updates."""

    def __init__(self, engine: Engine, try_emit: EmitFn) -> None:
        self._engine = engine
        self._try_emit = try_emit
        self._cancel = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_subagents = -1
        self._last_tasks = -1

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._cancel.clear()
        self._task = asyncio.create_task(self._run(), name="session-activity")

    async def stop(self) -> None:
        self._cancel.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._task = None

    def _mailbox(self) -> Mailbox | None:
        # Prefer the engine's own manager: with a shared ToolRuntime each
        # engine gets a per-engine manager + mailbox (Engine.create), and
        # draining the shared runtime.mailbox here would steal envelopes
        # that belong to another engine's coordinator.
        mgr = self._engine.tool_context.subagent_manager
        if mgr is not None and mgr.mailbox is not None:
            return mgr.mailbox
        rt = self._engine.tool_runtime
        if rt is not None and rt.mailbox is not None:
            return rt.mailbox
        return None

    def _running_subagents(self) -> int:
        mgr = self._engine.tool_context.subagent_manager
        return mgr.running_count() if mgr is not None else 0

    def _running_tasks(self) -> int:
        mgr = self._engine.tool_context.task_manager
        return mgr.running_count() if mgr is not None else 0

    def _emit_activity_snapshot(self, *, force: bool = False) -> None:
        subs = self._running_subagents()
        tasks = self._running_tasks()
        if not force and subs == self._last_subagents and tasks == self._last_tasks:
            return
        self._last_subagents = subs
        self._last_tasks = tasks
        # Skip idle snapshots — nothing useful for UI/tests, avoids queue spam.
        if subs == 0 and tasks == 0:
            return
        parts: list[str] = []
        if subs:
            parts.append(f"{subs} sub-agent(s)")
        if tasks:
            parts.append(f"{tasks} task(s)")
        detail = ", ".join(parts) + " running"
        self._try_emit(
            SessionActivityEvent(
                running_subagents=subs,
                running_tasks=tasks,
                message=detail,
            )
        )

    async def _run(self) -> None:
        mailbox = self._mailbox()
        try:
            while not self._cancel.is_set():
                if mailbox is not None:
                    for envelope in await mailbox.drain_available():
                        self._try_emit(
                            SubAgentMailboxEvent(
                                seq=envelope.seq,
                                message=envelope.message,
                            )
                        )
                self._emit_activity_snapshot()
                try:
                    await asyncio.wait_for(
                        self._cancel.wait(), timeout=PollIntervalSecs
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("session_activity_coordinator_failed")
