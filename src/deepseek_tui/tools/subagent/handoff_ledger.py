"""Parent-turn ledger after a batch of children stop.

Does not re-run anyone. It classifies each slot, counts outcomes, and names
the ids the parent should ``agent(resume=)``. One successful child stays a
plain ``subagent.done`` — a ledger for that case is noise.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from html import escape

from deepseek_tui.tools.subagent.completion import (
    has_summary_section,
    summarize_subagent_result,
)
from deepseek_tui.tools.subagent.types import SubAgentResult, SubAgentStatusKind

_SLOT_LINE_CHARS = 120
_RESUME_HINT = (
    "Unfinished slots still have agent ids. Call agent(resume=<id>) "
    "for each; do not summarize as if the batch succeeded."
)


class HandoffOutcome(str, Enum):
    COMPLETED = "completed"
    MAX_STEPS = "max_steps_reached"
    EMPTY = "empty"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


def classify_handoff(snap: SubAgentResult) -> HandoffOutcome:
    kind = snap.status.kind
    if kind is SubAgentStatusKind.FAILED:
        return HandoffOutcome.FAILED
    if kind is SubAgentStatusKind.CANCELLED:
        return HandoffOutcome.CANCELLED
    if kind is SubAgentStatusKind.INTERRUPTED:
        return HandoffOutcome.INTERRUPTED
    if kind is SubAgentStatusKind.RUNNING:
        return HandoffOutcome.INTERRUPTED
    # The step budget ran out mid-assignment. Whatever report the child wrote is
    # still worth reading, but the slot is not finished: it keeps its id so the
    # parent can resume it instead of summarising over the gap.
    if snap.max_steps_reached:
        return HandoffOutcome.MAX_STEPS
    if snap.structured is not None:
        return HandoffOutcome.COMPLETED
    if has_summary_section(snap.result):
        return HandoffOutcome.COMPLETED
    return HandoffOutcome.EMPTY


def is_resumable(snap: SubAgentResult) -> bool:
    """Failed, cancelled, interrupted, or completed-without-a-usable-report."""
    return classify_handoff(snap) is not HandoffOutcome.COMPLETED


def build_handoff_ledger(snaps: Sequence[SubAgentResult]) -> str | None:
    if not snaps:
        return None
    rows = [(snap, classify_handoff(snap)) for snap in snaps]
    if len(rows) == 1 and rows[0][1] is HandoffOutcome.COMPLETED:
        return None

    counts: dict[HandoffOutcome, int] = {}
    for _snap, outcome in rows:
        counts[outcome] = counts.get(outcome, 0) + 1
    order = (
        HandoffOutcome.COMPLETED,
        HandoffOutcome.MAX_STEPS,
        HandoffOutcome.EMPTY,
        HandoffOutcome.FAILED,
        HandoffOutcome.CANCELLED,
        HandoffOutcome.INTERRUPTED,
    )
    summary = ", ".join(
        f"{outcome.value}: {counts[outcome]}" for outcome in order if outcome in counts
    )
    resumable = [
        snap.agent_id
        for snap, outcome in rows
        if outcome is not HandoffOutcome.COMPLETED and snap.agent_id
    ]

    lines = [
        "<subagent_handoff>",
        f"<summary>{escape(summary)}</summary>",
    ]
    if resumable:
        lines.append(f"<resume_hint>{escape(_RESUME_HINT)}</resume_hint>")
    for snap, outcome in rows:
        line = summarize_subagent_result(snap).replace("\n", " ").strip()
        if len(line) > _SLOT_LINE_CHARS:
            line = line[: _SLOT_LINE_CHARS - 3] + "..."
        lines.append(
            f'<slot agent_id="{escape(snap.agent_id, quote=True)}" '
            f'outcome="{outcome.value}">{escape(line)}</slot>'
        )
    lines.append("</subagent_handoff>")
    return "\n".join(lines)
