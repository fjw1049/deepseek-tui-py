"""Sub-agent completion payloads for parent turn handoff (Rust issue #756)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent.manager import SubAgentResult


@dataclass(frozen=True, slots=True)
class SubAgentCompletion:
    """Notification that a direct child sub-agent finished."""

    agent_id: str
    payload: str


def summarize_subagent_result(snap: SubAgentResult) -> str:
    """One-line human summary for the parent sidebar / transcript."""
    from deepseek_tui.tools.subagent.manager import SubAgentStatusKind

    if snap.status.kind is SubAgentStatusKind.FAILED:
        return f"Failed: {snap.status.message or 'unknown error'}"
    if snap.status.kind is SubAgentStatusKind.CANCELLED:
        return "Cancelled"
    if snap.status.kind is SubAgentStatusKind.INTERRUPTED:
        return f"Interrupted: {snap.status.message or 'unknown'}"
    body = (snap.result or "").strip()
    if not body:
        return f"Completed ({snap.agent_type.value})"
    first = body.splitlines()[0].strip()
    if len(first) > 240:
        return first[:237] + "..."
    return first


def subagent_done_sentinel(snap: SubAgentResult) -> str:
    """Build ``<deepseek:subagent.done>`` JSON sentinel."""
    from deepseek_tui.tools.subagent.manager import SubAgentStatusKind

    if snap.status.kind is SubAgentStatusKind.FAILED:
        payload = json.dumps(
            {
                "agent_id": snap.agent_id,
                "status": "failed",
                "error": snap.status.message or "unknown",
            },
            ensure_ascii=False,
        )
    else:
        payload = json.dumps(
            {
                "agent_id": snap.agent_id,
                "agent_type": snap.agent_type.value,
                "status": snap.status.kind.value,
                "duration_ms": snap.duration_ms,
                "steps": snap.steps_taken,
                "summary": summarize_subagent_result(snap),
            },
            ensure_ascii=False,
        )
    return f"<deepseek:subagent.done>{payload}</deepseek:subagent.done>"


_MAX_PAYLOAD_CHARS = 8_000


def build_completion_payload(snap: SubAgentResult) -> str:
    """Human summary on line 1, sentinel on line 2 (Rust ``run_subagent_task``)."""
    summary = summarize_subagent_result(snap)
    sentinel = subagent_done_sentinel(snap)
    payload = f"{summary}\n{sentinel}"
    if len(payload) > _MAX_PAYLOAD_CHARS:
        payload = payload[:_MAX_PAYLOAD_CHARS] + "\n…[truncated]"
    return payload
