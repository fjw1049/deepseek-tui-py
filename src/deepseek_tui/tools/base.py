from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from deepseek_tui.tools.context import ToolContext


class ToolCapability(str, Enum):
    READ_ONLY = "read_only"
    WRITES_FILES = "writes_files"
    EXECUTES_CODE = "executes_code"
    NETWORK = "network"
    SANDBOXABLE = "sandboxable"
    REQUIRES_APPROVAL = "requires_approval"


class ToolError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ToolResult:
    success: bool
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolSpec(ABC):
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> list[ToolCapability]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        raise NotImplementedError

    def supports_parallel(self) -> bool:
        return True
