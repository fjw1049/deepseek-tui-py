"""Unified context-pressure signal and ratio-tier policy.

All compaction layers (L0 prune, soft seams, rewrite, cycle) should read
:func:`measure_context_pressure` instead of inventing absolute thresholds
tuned to a single 1M window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from deepseek_tui.config.providers import context_window_for_model
from deepseek_tui.protocol.messages import Message, Role, TextBlock

# Ratio ladder (confirmed product policy).
RATIO_SEAM_L1 = 0.20
RATIO_SEAM_L2 = 0.40
RATIO_L0_PRUNE = 0.50
RATIO_SEAM_L3 = 0.55
RATIO_REWRITE = 0.75
RATIO_CYCLE = 0.90
RATIO_AUTO_FLOOR = 0.20  # below this: ingress truncation only

COMPACTION_BRIDGE_PREFIX = (
    "The conversation history before this point was compacted into the "
    "following summary:\n"
)
ARCHIVED_CONTEXT_OPEN = "<archived_context>"
ARCHIVED_CONTEXT_CLOSE = "</archived_context>"

PressureSource = Literal["real", "estimate"]


@dataclass(frozen=True, slots=True)
class ContextPressure:
    """Snapshot of how full the model context is."""

    tokens: int
    window: int
    ratio: float
    source: PressureSource

    @property
    def at_or_above(self) -> float:
        return self.ratio


def measure_context_pressure(
    model: str,
    messages: list[Message],
    *,
    real_input_tokens: int = 0,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> ContextPressure:
    """Prefer provider ``input_tokens``; fall back to a char-based estimate."""
    window = max(1, int(context_window_for_model(model) or 128_000))
    if real_input_tokens > 0:
        tokens = int(real_input_tokens)
        source: PressureSource = "real"
    else:
        from deepseek_tui.engine.context import estimate_tokens, estimated_input_tokens

        tokens = estimated_input_tokens(messages)
        if system_prompt:
            tokens += estimate_tokens(system_prompt)
        if tools:
            try:
                import json

                tokens += estimate_tokens(json.dumps(tools))
            except (TypeError, ValueError):
                pass
        source = "estimate"
    ratio = min(1.5, tokens / window)  # allow >1.0 under overflow
    return ContextPressure(tokens=tokens, window=window, ratio=ratio, source=source)


def thresholds_for_window(window: int) -> dict[str, int]:
    """Absolute token thresholds derived from a context window."""
    w = max(1, int(window))
    return {
        "seam_l1": int(w * RATIO_SEAM_L1),
        "seam_l2": int(w * RATIO_SEAM_L2),
        "l0_prune": int(w * RATIO_L0_PRUNE),
        "seam_l3": int(w * RATIO_SEAM_L3),
        "rewrite": int(w * RATIO_REWRITE),
        "cycle": int(w * RATIO_CYCLE),
        "auto_floor": int(w * RATIO_AUTO_FLOOR),
    }


def is_compaction_bridge_message(message: Message) -> bool:
    """True when *message* is our rewrite bridge carrier.

    Soft seams are assistant messages with ``level="…"`` and do not use
    :data:`COMPACTION_BRIDGE_PREFIX`. Rewrite bridges are user messages.
    """
    if message.role != Role.USER:
        return False
    for block in message.content:
        if isinstance(block, TextBlock) and block.text:
            text = block.text
            if COMPACTION_BRIDGE_PREFIX in text and ARCHIVED_CONTEXT_OPEN in text:
                return True
    return False


def extract_compaction_bridge_text(messages: list[Message]) -> str | None:
    """Return the text of the first rewrite bridge message, if any."""
    for msg in messages:
        if not is_compaction_bridge_message(msg):
            continue
        for block in msg.content:
            if isinstance(block, TextBlock) and block.text:
                return block.text
    return None


def build_compaction_bridge_text(
    summary: str,
    *,
    working_set_paths: list[str] | None = None,
) -> str:
    """Format a user-role bridge message body (cache-friendly composition)."""
    body = f"{COMPACTION_BRIDGE_PREFIX}{ARCHIVED_CONTEXT_OPEN}\n{summary.strip()}\n{ARCHIVED_CONTEXT_CLOSE}"
    if working_set_paths:
        body += "\n\n**Working Set Files:**\n"
        for path in working_set_paths[:10]:
            body += f"- {path}\n"
    return body


def prepend_compaction_bridge(
    messages: list[Message],
    bridge_text: str,
) -> list[Message]:
    """Return messages with a single leading bridge (replacing any prior bridge)."""
    from deepseek_tui.protocol.messages import Message as Msg

    rest = [m for m in messages if not is_compaction_bridge_message(m)]
    return [Msg.user(bridge_text), *rest]
