"""One record for every time the harness steps into the model's loop.

A gate, reminder or prune that leaves no trace cannot be evaluated: nobody can
say how often it helped or how often it got in the way. Sites call ``record``
and stay ignorant of the turn; the Engine binds the sink that adds the round
and carries the record to the thread's event log as ``harness.intervention``.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

InterventionKind = Literal[
    "reminder", "gate", "goal_audit", "tool_list", "guard", "prune", "compaction", "dedup",
]


@dataclass(frozen=True, slots=True)
class Intervention:
    kind: InterventionKind
    reason: str
    outcome: str
    tokens_affected: int = 0


_sink: ContextVar[Callable[[Intervention], None] | None] = ContextVar(
    "harness_intervention_sink", default=None
)


def bind_sink(sink: Callable[[Intervention], None]) -> None:
    """Route this task's records (and tasks it spawns) to ``sink``."""
    _sink.set(sink)


def record(
    kind: InterventionKind, reason: str, *, outcome: str, tokens_affected: int = 0
) -> None:
    sink = _sink.get()
    if sink is not None:
        sink(Intervention(kind, reason[:300], outcome, tokens_affected))
