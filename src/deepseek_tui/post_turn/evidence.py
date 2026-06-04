"""Turn evidence bundle for post-turn pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deepseek_tui.memory.provider import CaptureInput


@dataclass(slots=True)
class TurnEvidence:
    thread_id: str
    user_text: str
    workspace: str
    messages: list[dict[str, Any]]
    had_tool_calls: bool
    success: bool
    tool_rounds: int = 0
    user_turn_index: int = 0
    turn_id: str = ""
    flush_mode: bool = False

    def to_capture_input(self) -> CaptureInput:
        return CaptureInput(
            thread_id=self.thread_id,
            user_text=self.user_text,
            workspace=self.workspace,
            messages=self.messages,
            had_tool_calls=self.had_tool_calls,
            success=self.success,
        )
