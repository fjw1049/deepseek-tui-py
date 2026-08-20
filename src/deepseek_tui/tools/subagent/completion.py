"""Sub-agent completion payloads and run-output types."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from deepseek_tui.tools.subagent.types import SubAgentResult, SubAgentStatusKind


# Sub-agent completion payloads for parent turn handoff.


@dataclass(frozen=True, slots=True)
class SubAgentCompletion:
    """Notification that a direct child sub-agent finished."""

    agent_id: str
    payload: str


def summary_section_text(body: str) -> str | None:
    """Pull the prose under ``### SUMMARY``, or None when there is none.

    Shared with the sub-agent loop's output gate, which checks the same body
    for substance before accepting a report.
    """
    marker = "### SUMMARY"
    if marker not in body:
        return None
    section = body.split(marker, 1)[1]
    lines: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            break
        if stripped:
            lines.append(stripped)
    if not lines:
        return None
    return " ".join(lines)


def summarize_subagent_result(snap: SubAgentResult) -> str:
    """One-line human summary for the parent sidebar / transcript."""

    if snap.status.kind is SubAgentStatusKind.FAILED:
        return f"Failed: {snap.status.message or 'unknown error'}"
    if snap.status.kind is SubAgentStatusKind.CANCELLED:
        return "Cancelled"
    if snap.status.kind is SubAgentStatusKind.INTERRUPTED:
        return f"Interrupted: {snap.status.message or 'unknown'}"
    body = (snap.result or "").strip()
    if not body:
        return f"Completed ({snap.agent_type.value})"
    section = summary_section_text(body)
    first = (section or body.splitlines()[0]).strip()
    if len(first) > 240:
        return first[:237] + "..."
    return first


def subagent_done_sentinel(snap: SubAgentResult) -> str:
    """Build ``<deepseek:subagent.done>`` JSON sentinel."""

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
# Room for the one-line summary, the sentinel JSON, and the re-read pointer that
# replaces an elided tail. Measured against the sentinel's own budget rather
# than guessed: the reminder spec caps this payload at _MAX_PAYLOAD_CHARS.
_PAYLOAD_ENVELOPE_RESERVE = 1_200


def _report_block(snap: SubAgentResult, budget: int) -> str | None:
    """Render the child's full report for the parent, trimmed to *budget*.

    The parent used to receive only the 240-char sidebar line and had to spend a
    ``task_output`` round-trip to read what the child actually wrote — for every
    delegation, including foreground ones whose result it needs immediately.
    Kimi and grok both hand the parent the child's final message verbatim; the
    reminder budget here was already sized for it (see ``SUBAGENT_DONE``).

    Trimming keeps the head: the contract puts ``### SUMMARY`` first, so the head
    is the conclusion. An elided tail is recoverable — the pointer says how.
    """
    body = (snap.result or "").strip()
    if not body or budget <= 0:
        return None
    if len(body) <= budget:
        return body
    pointer = (
        f"\n\n[report truncated at {budget} chars — read the rest with "
        f"task_output(agent_id=\"{snap.agent_id}\")]"
    )
    head = max(0, budget - len(pointer))
    if head <= 0:
        return None
    return body[:head].rstrip() + pointer


def build_completion_payload(snap: SubAgentResult) -> str:
    """One-line summary, the sentinel, then the child's report in full.

    Ordered so the cheap signal comes first: a parent that only skims the first
    line still learns the outcome, and the report below saves it a round-trip
    when it needs the detail.
    """
    summary = summarize_subagent_result(snap)
    sentinel = subagent_done_sentinel(snap)
    payload = f"{summary}\n{sentinel}"
    report = _report_block(
        snap, _MAX_PAYLOAD_CHARS - len(payload) - _PAYLOAD_ENVELOPE_RESERVE
    )
    # Skip the block when it would only restate the summary line verbatim.
    if report and report != summary:
        payload = f"{payload}\n\n{report}"
    if len(payload) > _MAX_PAYLOAD_CHARS:
        payload = payload[:_MAX_PAYLOAD_CHARS] + "\n…[truncated]"
    return payload


# Sub-agent run result types (text + structured output).


@dataclass(slots=True)
class AgentRunOutput:
    """Result of one sub-agent loop execution."""

    text: str
    structured: dict[str, Any] | list[Any] | None = None
