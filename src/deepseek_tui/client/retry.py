from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_transparent_retries: int = 2
    max_error_retries: int = 5
    base_delay: float = 0.2
    max_delay: float = 10.0

    def transparent_delay(self, attempt: int) -> float:
        return float(min(self.base_delay * (2**attempt), self.max_delay))

    def error_delay(self, attempt: int) -> float:
        return float(min(self.base_delay * (2**attempt), self.max_delay))
