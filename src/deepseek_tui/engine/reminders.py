"""Registry of everything the harness injects into the message stream.

Two problems this exists to solve.

**One envelope was doing two jobs.** Cycle seeds shipped inside
`<system-reminder>`, the same wrapper as "your last edit produced errors" and
"a Stop hook blocked you". But a seed is not an alert — it is a *stand-in for
history*, and it has to sit at the point in the transcript that the history it
replaces used to occupy. An alert is the opposite: it is about right now, and
belongs as close to the model's attention as we can put it. With one envelope
covering both, there was nothing to base a position rule on, so position
degraded to whichever code path happened to append first. Separate envelopes
make the rule statable, and `Placement` states it.

**The texts had no home.** Thirteen of them lived as inline literals across six
files, each site wrapping and tagging by hand — which is how four sites ended
up wrapped but untagged, and one wrapped by hand-rolled string concatenation.
Declaring them here means the envelope, the provenance tag and the size cap
travel together and cannot come apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from deepseek_tui.protocol.messages import Message, MessageOrigin


class Envelope(str, Enum):
    """What kind of thing this is, from the model's point of view."""

    # Live alert: the world changed, or a rule is being restated. Authority is
    # one-way (see base.md) — may tighten constraints, never loosen them.
    ALERT = "system-reminder"
    # Everything carried across a cycle boundary when the transcript is reset.
    CARRYOVER = "cycle_carryover"


class Placement(str, Enum):
    """Where in the transcript the injection has to land, and why."""

    # Before the user's turn: session-level framing that the request is
    # answered *against* (repo state, what the last session left behind).
    HEAD = "head"
    # At the tail, where attention is strongest. Live alerts only.
    TAIL = "tail"
    # At the position in history that the replaced content used to occupy.
    # Moving one of these to the tail would reorder the past.
    IN_HISTORY = "in_history"


@dataclass(frozen=True)
class ReminderSpec:
    """One injection: its envelope, its position, and its ceiling.

    ``priority`` orders injections that land at the same point in the turn.
    Lower goes first, which means *further from the end* — so the most
    specific, most actionable alert gets the last word.
    """

    name: str
    envelope: Envelope
    placement: Placement
    origin: MessageOrigin
    priority: int = 50
    max_chars: int | None = None


# --- Head: session framing, injected ahead of the user's first turn --------

GIT_SNAPSHOT = ReminderSpec(
    name="git_snapshot",
    envelope=Envelope.ALERT,
    placement=Placement.HEAD,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=10,
)

HANDOFF = ReminderSpec(
    name="handoff",
    envelope=Envelope.ALERT,
    placement=Placement.HEAD,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=20,
)

PROMPT_SUBMIT_HOOK_CONTEXT = ReminderSpec(
    name="prompt_submit_hook_context",
    envelope=Envelope.ALERT,
    placement=Placement.HEAD,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=30,
)


# --- Tail: live alerts, ordered least to most specific ---------------------

PLAN_NUDGE = ReminderSpec(
    name="plan_nudge",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=10,
)

APPROVED_PLAN = ReminderSpec(
    name="approved_plan",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    # Standing pointer after leaving plan mode; yields to live alerts.
    priority=12,
)

LONG_SESSION_DRIFT = ReminderSpec(
    name="long_session_drift",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    # Furthest from the end of the tail block: a general re-anchor, not a
    # reaction to anything that just happened.
    priority=20,
)

CHECKLIST_INCOMPLETE_GATE = ReminderSpec(
    name="checklist_incomplete_gate",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    # Fires when the model tries to end a turn with open checklist items.
    # Between the general long-session re-anchor (20) and diagnostics (30):
    # more specific than a drift nudge, less urgent than a fresh error.
    priority=25,
)

LSP_DIAGNOSTICS = ReminderSpec(
    name="lsp_diagnostics",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=30,
)

SUBAGENT_DONE = ReminderSpec(
    name="subagent_done",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=40,
    # A child's report is the one tail item that can be arbitrarily large.
    max_chars=8_000,
)

STOP_HOOK_BLOCK = ReminderSpec(
    name="stop_hook_block",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    # Last word by design: the model just tried to end the turn and cannot.
    priority=90,
)

GOAL_ACTIVE = ReminderSpec(
    name="goal_active",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=14,
)

GOAL_PAUSED = ReminderSpec(
    name="goal_paused",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=14,
)

GOAL_BLOCKED = ReminderSpec(
    name="goal_blocked",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=14,
)

GOAL_CANCELLED = ReminderSpec(
    name="goal_cancelled",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=16,
)

GOAL_CONTINUATION = ReminderSpec(
    name="goal_continuation",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.GOAL_CONTINUATION,
    priority=15,
    max_chars=8_000,
)

SOFT_RESUME = ReminderSpec(
    name="soft_resume",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=50,
)

SUBAGENT_OUTPUT_NUDGE = ReminderSpec(
    name="subagent_output_nudge",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=60,
)

SUBAGENT_STOP_HOOK_BLOCK = ReminderSpec(
    name="subagent_stop_hook_block",
    envelope=Envelope.ALERT,
    placement=Placement.TAIL,
    origin=MessageOrigin.SYSTEM_REMINDER,
    priority=90,
)


# --- In history: stand-ins for content that used to be there ---------------

CYCLE_SEED = ReminderSpec(
    name="cycle_seed",
    envelope=Envelope.CARRYOVER,
    placement=Placement.IN_HISTORY,
    origin=MessageOrigin.CYCLE_SEED,
)


REGISTRY: tuple[ReminderSpec, ...] = (
    GIT_SNAPSHOT,
    HANDOFF,
    PROMPT_SUBMIT_HOOK_CONTEXT,
    PLAN_NUDGE,
    APPROVED_PLAN,
    GOAL_ACTIVE,
    GOAL_PAUSED,
    GOAL_BLOCKED,
    GOAL_CANCELLED,
    GOAL_CONTINUATION,
    LONG_SESSION_DRIFT,
    CHECKLIST_INCOMPLETE_GATE,
    LSP_DIAGNOSTICS,
    SUBAGENT_DONE,
    SOFT_RESUME,
    SUBAGENT_OUTPUT_NUDGE,
    STOP_HOOK_BLOCK,
    SUBAGENT_STOP_HOOK_BLOCK,
    CYCLE_SEED,
)


def render(spec: ReminderSpec, body: str) -> str:
    """Apply the spec's ceiling, then its envelope."""
    text = body.strip()
    if not text:
        return ""
    if spec.max_chars is not None and len(text) > spec.max_chars:
        from deepseek_tui.engine.context import summarize_text_head_tail

        omitted = len(text) - spec.max_chars
        text = (
            f"{summarize_text_head_tail(text, spec.max_chars)}\n"
            f"[{spec.name}: {omitted} chars omitted from the middle]"
        )
    open_tag = f"<{spec.envelope.value}>"
    if text.startswith(open_tag):
        return text
    return f"{open_tag}\n{text}\n</{spec.envelope.value}>"


def reminder_message(spec: ReminderSpec, body: str) -> Message:
    """Build the injected message with envelope and provenance in one step.

    Doing these separately is what let four call sites wrap a reminder and
    forget to tag it, leaving the transcript unable to tell an injection from
    something the human said.
    """
    return Message.user(render(spec, body), origin=spec.origin)
