"""Reduce engine lifecycle events into display-ready action batches."""

from __future__ import annotations

from deepseek_tui.engine.events import AgentRoundCompleteEvent
from deepseek_tui.presentation.models import ActionBatchView, TerminalActionStatus
from deepseek_tui.presentation.semantics import (
    BatchKind,
    Phase,
    batch_intent_text,
    classify_batch,
    infer_next_phase,
    template_narration,
)

_TOOL_WRAPPER_PREFIXES = (
    "[TOOL_CALL]",
    "<deepseek:tool_call",
    "<tool_call",
    "<invoke ",
    "<function_calls>",
)


class TurnPresentationReducer:
    """Track action-batch state without depending on a concrete UI."""

    def __init__(self, locale: str = "zh") -> None:
        self.locale = locale
        self.phase = Phase.EXPLORE
        self.round_count = 0
        self._active_batch: ActionBatchView | None = None
        self._batch_by_tool_id: dict[str, ActionBatchView] = {}

    def on_round_complete(
        self, event: AgentRoundCompleteEvent
    ) -> ActionBatchView | None:
        """Declare a batch after the model round and before tool execution."""
        if not event.tool_calls:
            return None
        batch_kind = classify_batch(event.tool_calls)
        self.phase = infer_next_phase(
            self.phase, batch_kind, has_tool_error=False
        )
        self.round_count += 1
        summary = batch_intent_text(
            batch_kind, event.tool_calls, locale=self.locale
        )
        intent = _usable_preface(event.preface_text)
        if intent is None:
            intent = template_narration(
                locale=self.locale,
                batch=batch_kind,
                tool_calls=event.tool_calls,
            )
        batch = ActionBatchView(
            round_idx=event.round_idx,
            expected_tool_ids=tuple(tool.id for tool in event.tool_calls),
            phase=self.phase.value,
            intent_text=intent,
            batch_summary=summary,
            batch_kind=batch_kind.value,
        )
        self._active_batch = batch
        for tool_call_id in batch.expected_tool_ids:
            self._batch_by_tool_id[tool_call_id] = batch
        return batch

    def on_tool_result(
        self, tool_call_id: str, *, success: bool
    ) -> ActionBatchView | None:
        status: TerminalActionStatus = "done" if success else "failed"
        return self._record_terminal(tool_call_id, status=status)

    def on_tool_approval_required(self, tool_call_id: str) -> None:
        batch = self._batch_by_tool_id.get(tool_call_id)
        if batch is not None:
            batch.mark_approval_required(tool_call_id)

    def on_tool_denied(self, tool_call_id: str) -> ActionBatchView | None:
        batch = self._batch_by_tool_id.get(tool_call_id)
        if batch is not None:
            batch.mark_approval_required(tool_call_id)
        return self._record_terminal(tool_call_id, status="denied")

    def mark_non_collapsible(self, tool_call_id: str) -> None:
        batch = self._batch_by_tool_id.get(tool_call_id)
        if batch is not None:
            batch.mark_non_collapsible(tool_call_id)

    def on_turn_cancelled(self) -> ActionBatchView | None:
        batch = self._active_batch
        if batch is not None and batch.status == "running":
            batch.status = "cancelled"
        self._detach_batch(batch)
        return batch

    def reset(self) -> None:
        self.phase = Phase.EXPLORE
        self.round_count = 0
        self._active_batch = None
        self._batch_by_tool_id.clear()

    def _record_terminal(
        self,
        tool_call_id: str,
        *,
        status: TerminalActionStatus,
    ) -> ActionBatchView | None:
        batch = self._batch_by_tool_id.get(tool_call_id)
        if batch is None:
            return None
        completed = batch.receive_terminal(tool_call_id, status=status)
        if not completed:
            return None
        if batch.has_error:
            self.phase = infer_next_phase(
                Phase(batch.phase),
                BatchKind(batch.batch_kind),
                has_tool_error=True,
            )
        self._detach_batch(batch)
        return batch

    def _detach_batch(self, batch: ActionBatchView | None) -> None:
        if batch is None:
            return
        for tool_call_id in batch.expected_tool_ids:
            if self._batch_by_tool_id.get(tool_call_id) is batch:
                del self._batch_by_tool_id[tool_call_id]
        if self._active_batch is batch:
            self._active_batch = None


def _usable_preface(text: str | None) -> str | None:
    if not text:
        return None
    stripped = text.strip()
    if not stripped or len(stripped) > 200:
        return None
    if any(stripped.startswith(prefix) for prefix in _TOOL_WRAPPER_PREFIXES):
        return None
    return stripped.splitlines()[0][:120]
