"""Periodic turn counter scheduler shared by L1 and evolution nudges."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _KeyState:
    count: int = 0
    last_payload: Any = None
    last_notify_ts: float = field(default_factory=time.monotonic)


class PeriodicTurnScheduler:
    def __init__(self, *, every_n: int, idle_timeout_s: float = 0.0, warmup_enabled: bool = True):
        self._every_n = max(1, every_n)
        self._idle_timeout_s = idle_timeout_s
        self._warmup_enabled = warmup_enabled
        self._states: dict[str, _KeyState] = {}

    def notify(self, key: str, payload: Any) -> None:
        state = self._states.setdefault(key, _KeyState())
        state.count += 1
        state.last_payload = payload
        state.last_notify_ts = time.monotonic()

    def is_due(self, key: str) -> bool:
        state = self._states.get(key)
        if state is None:
            return False
        if state.count >= self._effective_threshold(state.count):
            return True
        if (
            self._idle_timeout_s > 0
            and state.count > 0
            and (time.monotonic() - state.last_notify_ts) >= self._idle_timeout_s
        ):
            return True
        return False

    def reset(self, key: str) -> None:
        if key in self._states:
            self._states[key] = _KeyState()

    def count(self, key: str) -> int:
        return self._states.get(key, _KeyState()).count

    def last_payload(self, key: str) -> Any:
        return self._states.get(key, _KeyState()).last_payload

    def _effective_threshold(self, current_count: int) -> int:
        if not self._warmup_enabled or self._every_n <= 1:
            return self._every_n
        if current_count <= 1:
            return 1
        warmup = 2
        while warmup < self._every_n and current_count >= warmup:
            if current_count < warmup * 2:
                return warmup
            warmup *= 2
        return self._every_n
