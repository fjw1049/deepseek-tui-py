"""Turn capture quality gates — re-export from post_turn."""

from __future__ import annotations

from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.post_turn.gates import GateConfig, passes_base_gate, should_capture


def should_capture_turn(
    user_text: str,
    *,
    had_tool_calls: bool,
    success: bool,
    min_chars: int = 20,
    skip_slash: bool = True,
    skip_confirmations: bool = True,
) -> bool:
    evidence = TurnEvidence(
        thread_id="",
        user_text=user_text,
        workspace="",
        messages=[],
        had_tool_calls=had_tool_calls,
        success=success,
    )
    cfg = GateConfig(
        min_chars=min_chars,
        skip_slash=skip_slash,
        skip_confirmations=skip_confirmations,
    )
    return should_capture(evidence, cfg)


__all__ = [
    "GateConfig",
    "passes_base_gate",
    "should_capture_turn",
]
