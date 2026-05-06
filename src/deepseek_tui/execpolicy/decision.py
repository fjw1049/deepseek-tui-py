"""Execpolicy decision enum.

Mirrors ``crates/tui/src/execpolicy/decision.rs`` (27 LOC).

Rust serde shape: camelCase ``"allow" | "prompt" | "forbidden"`` when
serialised as a string. The Rust enum derives ``Ord`` with the variant
order ``Allow < Prompt < Forbidden``, which :meth:`Policy.check` relies
on when aggregating multiple matches (the most-restrictive decision
wins). We preserve that ordering here.
"""

from __future__ import annotations

from enum import Enum
from functools import total_ordering
from typing import cast

from .errors import ExecPolicyError

__all__ = ["Decision"]


@total_ordering
class Decision(str, Enum):
    """Decision for a command evaluation.

    * ``ALLOW``      — run without further approval
    * ``PROMPT``     — request explicit user approval
    * ``FORBIDDEN``  — block outright
    """

    ALLOW = "allow"
    PROMPT = "prompt"
    FORBIDDEN = "forbidden"

    @classmethod
    def parse(cls, raw: str) -> Decision:
        """Parse a string; raise :class:`ExecPolicyError` on unknown values.

        Mirrors Rust ``Decision::parse`` (decision.rs:19-26).
        """
        try:
            return cls(raw)
        except ValueError as err:
            raise ExecPolicyError.invalid_decision(raw) from err

    # --- Ordering (ALLOW < PROMPT < FORBIDDEN) ----------------------

    _RANKS: dict[str, int] = {}  # type: ignore[misc]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Decision):
            return NotImplemented
        ranks = _RANK
        return ranks[cast(str, self.value)] < ranks[cast(str, other.value)]


# Module-level rank table (kept separate from the enum class so the
# Enum machinery doesn't try to turn it into a member).
_RANK: dict[str, int] = {
    Decision.ALLOW.value: 0,
    Decision.PROMPT.value: 1,
    Decision.FORBIDDEN.value: 2,
}
