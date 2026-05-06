from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ErrorKind(str, Enum):
    CONFIG = "config"
    AUTH = "auth"
    NETWORK = "network"
    TOOL = "tool"
    RATE_LIMIT = "rate_limit"
    INTERNAL = "internal"


class ErrorEnvelope(BaseModel):
    kind: ErrorKind
    message: str
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
