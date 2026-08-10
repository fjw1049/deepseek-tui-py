"""Same-args tool-call dedup / anti-loop for a single turn.

Two behaviours, deliberately thin so they fit the existing
``tool_use → execute → tool_result`` path:

- Same batch: identical ``(name, canonical args)`` reuses the first result
  instead of executing again.
- Cross-round streak: consecutive identical calls escalate a
  ``<system-reminder>`` on the model-facing result; at a hard streak the
  call is blocked (error result, no execute).

State is turn-local — reset at the start of each conversation turn.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

REPEAT_REMINDER_1_START = 3
REPEAT_REMINDER_2_START = 6
REPEAT_FORCE_STOP_STREAK = 10

_REMINDER_1 = (
    "\n\n<system-reminder>\n"
    "The same tool call has been repeated several times in a row. "
    "Before making your next call, write one sentence stating what new "
    "information you expect it to produce. Then act on that sentence: if it "
    "names something this result does not already give you, choose the "
    "action that best provides it; otherwise continue with the evidence you "
    "already have.\n"
    "</system-reminder>"
)

_REMINDER_2 = (
    "\n\n<system-reminder>\n"
    "The same tool call has been issued repeatedly. Choose exactly one and "
    "state your choice before acting:\n"
    "(1) Falsification check: run the cheapest test that could conclusively "
    "disprove your current approach, if such a test exists.\n"
    "(2) Missing input: tell the user precisely what information or decision "
    "you need, and ask for it.\n"
    "(3) Conclude: deliver your best result based on evidence already "
    "gathered, listing anything that remains uncertain.\n"
    "</system-reminder>"
)

_FORCE_STOP = (
    "<system-reminder>\n"
    "The same tool call was issued too many times in a row and was not "
    "executed again. Write your final response now without further identical "
    "calls. Cover: the blocker, approaches already tried, and what you need "
    "from the user if still stuck. Text only.\n"
    "</system-reminder>"
)

_SAME_BATCH_NOTE = (
    "\n\n<system-reminder>\n"
    "Duplicate tool call in the same step — reused the earlier result "
    "without re-running.\n"
    "</system-reminder>"
)


def canonical_tool_args(args: Any) -> str:
    """Stable JSON form for fingerprinting tool arguments."""
    if not isinstance(args, dict):
        args = {}
    try:
        return json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(args)


def make_tool_call_key(tool_name: str, args: Any) -> str:
    return f"{tool_name} {canonical_tool_args(args)}"


@dataclass(frozen=True, slots=True)
class DedupDecision:
    """What to do with one tool call in the current batch."""

    kind: Literal["execute", "reuse", "block"]
    key: str
    # For reuse: prior batch content (before same-batch note).
    reuse_content: str = ""
    reuse_is_error: bool = False
    # Projected cross-round streak including this call (execute/block only).
    projected_streak: int = 0


class ToolCallDeduplicator:
    """Turn-scoped dedup state for the engine tool loop."""

    def __init__(self) -> None:
        self._consecutive_key: str | None = None
        self._consecutive_count = 0
        self._batch_results: dict[str, tuple[str, bool]] = {}
        self._batch_keys: list[str] = []

    def reset_turn(self) -> None:
        self._consecutive_key = None
        self._consecutive_count = 0
        self.begin_batch()

    def begin_batch(self) -> None:
        self._batch_results.clear()
        self._batch_keys.clear()

    def end_batch(self) -> None:
        for key in self._batch_keys:
            if key == self._consecutive_key:
                self._consecutive_count += 1
            else:
                self._consecutive_key = key
                self._consecutive_count = 1

    def batch_has_duplicate_keys(
        self, calls: list[tuple[str, Any]]
    ) -> bool:
        """True when two calls in *calls* share the same fingerprint."""
        seen: set[str] = set()
        for name, args in calls:
            key = make_tool_call_key(name, args)
            if key in seen:
                return True
            seen.add(key)
        return False

    def classify(self, tool_name: str, args: Any) -> DedupDecision:
        key = make_tool_call_key(tool_name, args)
        prior = self._batch_results.get(key)
        if prior is not None:
            content, is_error = prior
            return DedupDecision(
                kind="reuse",
                key=key,
                reuse_content=content,
                reuse_is_error=is_error,
            )
        projected = self._projected_streak(key)
        if projected >= REPEAT_FORCE_STOP_STREAK:
            return DedupDecision(
                kind="block",
                key=key,
                projected_streak=projected,
            )
        return DedupDecision(
            kind="execute",
            key=key,
            projected_streak=projected,
        )

    def record(
        self,
        key: str,
        content: str,
        *,
        is_error: bool,
    ) -> None:
        """Remember a batch result so later same-key calls can reuse it.

        Only the first record for a key advances the batch key list (and thus
        the cross-round streak). Later same-batch reuses must not call this
        with a decorated copy, or reminders would stack and streaks double.
        """
        if key not in self._batch_results:
            self._batch_keys.append(key)
        self._batch_results[key] = (content, is_error)

    def decorate_execute_content(self, decision: DedupDecision, content: str) -> str:
        """Append an escalating reminder when the cross-round streak warrants it."""
        streak = decision.projected_streak
        if streak >= REPEAT_REMINDER_2_START:
            return content + _REMINDER_2
        if streak >= REPEAT_REMINDER_1_START:
            return content + _REMINDER_1
        return content

    def reuse_content(self, decision: DedupDecision) -> str:
        base = decision.reuse_content
        return base + _SAME_BATCH_NOTE

    def block_content(self, decision: DedupDecision) -> str:
        return _FORCE_STOP

    def _projected_streak(self, key: str) -> int:
        if key == self._consecutive_key:
            return self._consecutive_count + 1
        return 1
