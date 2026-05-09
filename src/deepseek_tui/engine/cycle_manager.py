"""Cycle manager — checkpoint-restart cycle management.

Mirrors Rust ``cycle_manager.rs`` (~1,071 LOC).
Manages long-running session context by archiving full conversation cycles
to disk and producing compact briefings for fresh context windows.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.protocol.messages import Message

CYCLE_ARCHIVE_SCHEMA_VERSION = 1
DEFAULT_CYCLE_THRESHOLD_TOKENS = 768_000
DEFAULT_BRIEFING_MAX_TOKENS = 3_000
APPROX_CHARS_PER_TOKEN = 4

CYCLE_HANDOFF_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "cycle_handoff.md"


@dataclass(slots=True)
class CycleConfig:
    """Configuration for cycle boundaries."""

    enabled: bool = True
    threshold_tokens: int = DEFAULT_CYCLE_THRESHOLD_TOKENS
    briefing_max_tokens: int = DEFAULT_BRIEFING_MAX_TOKENS
    per_model: dict[str, ModelCycleConfig] = field(default_factory=dict)

    def threshold_for(self, model: str) -> int:
        if model in self.per_model:
            return self.per_model[model].threshold_tokens
        return self.threshold_tokens

    def briefing_max_for(self, model: str) -> int:
        if model in self.per_model:
            return self.per_model[model].briefing_max_tokens
        return self.briefing_max_tokens


@dataclass(slots=True)
class ModelCycleConfig:
    """Per-model cycle tuning."""

    threshold_tokens: int = DEFAULT_CYCLE_THRESHOLD_TOKENS
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
    """Determine if a cycle boundary should fire."""
    if not config.enabled or in_flight:
        return False
    threshold = config.threshold_for(model)
    if threshold == 0:
        return False
    from deepseek_tui.engine.context import context_input_budget

    window = context_input_budget(model, 0)
    if window is not None:
        trigger_floor = min(threshold, window - reserved_headroom_tokens)
    else:
        trigger_floor = threshold
    return active_input_tokens >= trigger_floor


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


def estimate_briefing_tokens(text: str) -> int:
    """Estimate tokens (~4 chars/token)."""
    return (len(text) + APPROX_CHARS_PER_TOKEN - 1) // APPROX_CHARS_PER_TOKEN


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
    from deepseek_tui.protocol.requests import MessageRequest
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


def open_archive(path: Path) -> tuple[CycleArchiveHeader, list[dict[str, Any]]]:
    """Open an archived cycle JSONL and return header + message dicts."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"Empty archive at {path}")

    header_data = json.loads(lines[0])
    header = CycleArchiveHeader(
        schema_version=header_data.get("schema_version", 1),
        cycle=header_data.get("cycle", 0),
        session_id=header_data.get("session_id", ""),
        model=header_data.get("model", ""),
        started=header_data.get("started", 0),
        ended=header_data.get("ended", 0),
        message_count=header_data.get("message_count", 0),
    )

    if header.schema_version > CYCLE_ARCHIVE_SCHEMA_VERSION:
        raise ValueError(
            f"Archive schema v{header.schema_version} at {path} "
            f"is newer than supported v{CYCLE_ARCHIVE_SCHEMA_VERSION}"
        )

    messages = []
    for line in lines[1:]:
        line = line.strip()
        if line:
            messages.append(json.loads(line))
    return header, messages


def build_seed_messages(
    structured_state_block: str | None,
    briefing: CycleBriefing | None,
    pending_user_message: str | None,
) -> list[dict[str, str]]:
    """Compose seed messages for the next cycle."""
    out: list[dict[str, str]] = []

    if structured_state_block and structured_state_block.strip():
        out.append({
            "role": "user",
            "content": (
                "[CYCLE STATE — auto-preserved across the cycle boundary]\n\n"
                + structured_state_block.strip()
            ),
        })
        out.append({
            "role": "assistant",
            "content": "Acknowledged. State carried into the new cycle.",
        })

    if briefing and briefing.briefing_text.strip():
        from datetime import datetime, timezone

        ts = datetime.fromtimestamp(briefing.timestamp, tz=timezone.utc).isoformat()
        out.append({
            "role": "user",
            "content": (
                f"[CYCLE BRIEFING — written by you on cycle {briefing.cycle} at {ts}]\n\n"
                f"<carry_forward>\n{briefing.briefing_text.strip()}\n</carry_forward>"
            ),
        })
        out.append({
            "role": "assistant",
            "content": "Briefing absorbed. Continuing.",
        })

    if pending_user_message and pending_user_message.strip():
        out.append({"role": "user", "content": pending_user_message.strip()})

    return out


# ===========================================================================
# Helpers
# ===========================================================================


def _archive_dir_for(session_id: str) -> Path:
    return Path.home() / ".deepseek" / "sessions" / session_id / "cycles"


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
