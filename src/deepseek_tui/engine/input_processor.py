"""Engine-facing entry for user turn preprocessing."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.context import (
    ContextConfig,
    ProcessedTurnInput,
    UserTurnInput,
    process_turn_input,
)


def prepare_turn_for_model(
    content: str,
    *,
    workspace: Path,
    cwd: Path | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    config: ContextConfig | None = None,
) -> ProcessedTurnInput:
    """Expand ``@mentions`` before the message is sent to the LLM."""
    del turn_id  # reserved for per-turn artifact namespacing
    return process_turn_input(
        UserTurnInput(raw_text=content),
        workspace=workspace,
        cwd=cwd,
        session_id=session_id,
        config=config,
    )
