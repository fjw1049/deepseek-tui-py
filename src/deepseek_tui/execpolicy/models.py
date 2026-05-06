from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolCategory(Enum):
    READ_ONLY = "read_only"
    FILE_WRITE = "file_write"
    CODE_EXEC = "code_exec"
    NETWORK = "network"
    DESTRUCTIVE = "destructive"


@dataclass(slots=True)
class ApprovalRequest:
    tool_name: str
    risk_level: RiskLevel
    category: ToolCategory
    reason: str
    input_summary: str = ""


class ApprovalDecision(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    APPROVED_SESSION = "approved_session"


@dataclass(slots=True)
class PolicyRule:
    """A single policy rule matching tool patterns to decisions."""

    pattern: str
    decision: ApprovalDecision
    risk_threshold: RiskLevel = RiskLevel.LOW
    categories: list[ToolCategory] = field(default_factory=list)

    def matches(self, tool_name: str, category: ToolCategory) -> bool:
        if self.categories and category not in self.categories:
            return False
        if self.pattern == "*":
            return True
        return tool_name == self.pattern or tool_name.startswith(self.pattern.rstrip("*"))
