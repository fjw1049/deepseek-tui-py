"""Sub-agent run result types (workflow + structured output)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AgentRunOutput:
    """Result of one sub-agent loop execution."""

    text: str
    structured: dict[str, Any] | list[Any] | None = None
