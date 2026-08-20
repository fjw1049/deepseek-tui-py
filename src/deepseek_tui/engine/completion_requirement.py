"""Machine-checkable end condition for a role.

The harness can test this without asking the model whether it is done.
Recovery injects a reminder and re-runs with the same tool catalog.
Exhausted recoveries accept the last result; they do not fail the turn.

Callers own the ``satisfied`` predicate (a required tool name, a SUMMARY
body, an exit-plan call, …). This module only answers: should we recover?
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompletionRequirement:
    name: str
    reminder: str
    max_retries: int = 2

    def should_recover(
        self,
        *,
        satisfied: bool,
        fired: int,
        abort: bool = False,
    ) -> bool:
        if abort or satisfied or self.max_retries <= 0:
            return False
        return fired < self.max_retries
