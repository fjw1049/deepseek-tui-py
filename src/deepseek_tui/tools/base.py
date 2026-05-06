from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from deepseek_tui.tools.context import ToolContext


class ToolCapability(str, Enum):
    """Capabilities a tool may have or require.

    Mirrors Rust's `tools/spec.rs::ToolCapability`.
    """

    READ_ONLY = "read_only"
    WRITES_FILES = "writes_files"
    EXECUTES_CODE = "executes_code"
    NETWORK = "network"
    SANDBOXABLE = "sandboxable"
    REQUIRES_APPROVAL = "requires_approval"


class ApprovalRequirement(str, Enum):
    """Approval requirement for a tool.

    Mirrors Rust's `tools/spec.rs::ApprovalRequirement`.

    * AUTO: never needs approval (safe, read-only operations)
    * SUGGEST: hint that the user should approve, but allow skipping
    * REQUIRED: always require explicit user approval
    """

    AUTO = "auto"
    SUGGEST = "suggest"
    REQUIRED = "required"


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

    # --- Optional metadata with sensible defaults --------------------

    def approval_requirement(self) -> ApprovalRequirement:
        """Return whether this tool needs user approval before running.

        Default is :attr:`ApprovalRequirement.AUTO`. Override in subclasses.
        Mirrors Rust `ToolSpec::approval_requirement` (defaults to ``Auto``).
        """
        return ApprovalRequirement.AUTO

    def defer_loading(self) -> bool:
        """Whether the model should defer loading the tool's full schema.

        Default ``False``. Mirrors Rust `ToolSpec::defer_loading`.
        """
        return False

    def is_read_only(self) -> bool:
        """True iff the tool's capabilities include READ_ONLY.

        Mirrors Rust `ToolSpec::is_read_only` (default impl).
        """
        return ToolCapability.READ_ONLY in self.capabilities()

    def supports_parallel(self) -> bool:
        return True
