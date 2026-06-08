from __future__ import annotations

from time import monotonic

from deepseek_tui.protocol.responses import Usage


def tokens_from_usage(usage: Usage | None) -> int:
    if usage is None:
        return 0
    return max(0, int(usage.input_tokens)) + max(0, int(usage.output_tokens))


class GoalAccounting:
    def __init__(self) -> None:
        self._turn_started_at: float | None = None

    def start_turn(self) -> None:
        self._turn_started_at = monotonic()

    def finish_turn(self) -> float:
        if self._turn_started_at is None:
            return 0.0
        elapsed = max(0.0, monotonic() - self._turn_started_at)
        self._turn_started_at = None
        return elapsed
