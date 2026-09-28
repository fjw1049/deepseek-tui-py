"""Presentation-layer state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ToolActionStatus = Literal["running", "done", "failed", "denied", "cancelled"]
TerminalActionStatus = Literal["done", "failed", "denied"]
BatchStatus = Literal["running", "done", "partial_fail", "cancelled"]


@dataclass(frozen=True, slots=True)
class ToolActionView:
    tool_call_id: str
    tool_name: str
    status: ToolActionStatus
    summary: str
    detail: str
    started_at: float
    finished_at: float | None = None
    success: bool | None = None


@dataclass(slots=True)
class ActionBatchView:
    round_idx: int
    expected_tool_ids: tuple[str, ...]
    phase: str
    intent_text: str | None
    batch_summary: str
    batch_kind: str
    status: BatchStatus = "running"
    has_error: bool = False
    completed_ids: set[str] = field(default_factory=set)
    failed_ids: set[str] = field(default_factory=set)
    denied_ids: set[str] = field(default_factory=set)
    approval_ids: set[str] = field(default_factory=set)
    non_collapsible_ids: set[str] = field(default_factory=set)

    _expected_ids: frozenset[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # IDs are fixed for the lifetime of a batch; consumers only read this view.
        self._expected_ids = frozenset(self.expected_tool_ids)
        if len(self._expected_ids) != len(self.expected_tool_ids):
            raise ValueError("Duplicate tool IDs in batch")

    @property
    def terminal_ids(self) -> set[str]:
        return self.completed_ids | self.failed_ids | self.denied_ids

    @property
    def is_terminal(self) -> bool:
        return self.status != "running"

    @property
    def all_results_received(self) -> bool:
        return bool(self._expected_ids) and self.terminal_ids >= self._expected_ids

    @property
    def has_approval(self) -> bool:
        return bool(self.approval_ids)

    @property
    def can_collapse(self) -> bool:
        return not self.has_approval and not self.non_collapsible_ids

    def mark_approval_required(self, tool_call_id: str) -> None:
        if tool_call_id in self._expected_ids:
            self.approval_ids.add(tool_call_id)

    def mark_non_collapsible(self, tool_call_id: str) -> None:
        if tool_call_id in self._expected_ids:
            self.non_collapsible_ids.add(tool_call_id)

    def receive_terminal(
        self,
        tool_call_id: str,
        *,
        status: TerminalActionStatus,
    ) -> bool:
        """Record one terminal action idempotently and report batch completion."""
        if (
            self.is_terminal or tool_call_id not in self._expected_ids
            or tool_call_id in self.completed_ids
            or tool_call_id in self.failed_ids
            or tool_call_id in self.denied_ids
        ):
            return False
        if status == "done":
            self.completed_ids.add(tool_call_id)
        elif status == "denied":
            self.denied_ids.add(tool_call_id)
            self.has_error = True
        else:
            self.failed_ids.add(tool_call_id)
            self.has_error = True
        # The three sets are disjoint; avoid rebuilding their union per result.
        received = len(self.completed_ids) + len(self.failed_ids) + len(self.denied_ids)
        if received < len(self._expected_ids):
            return False
        self.status = "partial_fail" if self.has_error else "done"
        return True
