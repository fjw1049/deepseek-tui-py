from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureKind(Enum):
    USER_CANCEL = "user_cancel"
    FATAL = "fatal"
    CONTEXT_OVERFLOW = "context_overflow"
    TRANSIENT = "transient"


class FailureAction(Enum):
    PAUSE_NOW = "pause_now"
    COUNTED = "counted"
    OVERFLOW_WAIT = "overflow_wait"


_USER_CANCEL_REASONS = frozenset(
    {
        "user_cancelled",
        "interrupt_requested",
    }
)

_FATAL_MARKERS = (
    "quota",
    "rate_limit",
    "unauthorized",
    "authentication",
    "invalid_api_key",
    "permission_denied",
    "engine_error",
)


def classify_failure(reason: str) -> FailureKind:
    normalized = (reason or "").strip().lower()
    if normalized in _USER_CANCEL_REASONS:
        return FailureKind.USER_CANCEL
    if normalized == "context_overflow":
        return FailureKind.CONTEXT_OVERFLOW
    if any(marker in normalized for marker in _FATAL_MARKERS):
        return FailureKind.FATAL
    return FailureKind.TRANSIENT


@dataclass(slots=True)
class GoalRecovery:
    max_consecutive_failures: int = 3
    max_overflow_failures: int = 3
    consecutive_failures: int = 0
    overflow_failures: int = 0

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.overflow_failures = 0

    def evaluate_failure(self, reason: str) -> FailureAction:
        kind = classify_failure(reason)
        if kind in {FailureKind.USER_CANCEL, FailureKind.FATAL}:
            return FailureAction.PAUSE_NOW
        if kind == FailureKind.CONTEXT_OVERFLOW:
            self.overflow_failures += 1
            if self.overflow_failures >= self.max_overflow_failures:
                return FailureAction.PAUSE_NOW
            return FailureAction.OVERFLOW_WAIT
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_consecutive_failures:
            return FailureAction.PAUSE_NOW
        return FailureAction.COUNTED
