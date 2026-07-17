"""Unified context-pressure signal and ratio-tier policy.

All compaction layers (L0 prune, soft seams, rewrite, cycle) should read
:func:`measure_context_pressure` instead of inventing absolute thresholds
tuned to a single 1M window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from deepseek_tui.config.providers import context_window_for_model
from deepseek_tui.protocol.messages import Message, MessageOrigin, Role, TextBlock

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
SYSTEM_REMINDER_OPEN = "<system-reminder>"
SYSTEM_REMINDER_CLOSE = "</system-reminder>"
USER_QUERY_OPEN = "<user_query>"
USER_QUERY_CLOSE = "</user_query>"
LOCAL_CONTEXT_OPEN = "<local_context>"
LOCAL_CONTEXT_CLOSE = "</local_context>"

_USER_QUERY_RE = re.compile(
    r"<user_query>\s*(.*?)\s*</user_query>",
    re.DOTALL | re.IGNORECASE,
)

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


def wrap_system_reminder(body: str) -> str:
    """Wrap injected runtime text in a Claude-Code-style reminder envelope."""
    trimmed = body.strip()
    if trimmed.startswith(SYSTEM_REMINDER_OPEN):
        return trimmed
    return f"{SYSTEM_REMINDER_OPEN}\n{trimmed}\n{SYSTEM_REMINDER_CLOSE}"


def format_user_query_message(query: str) -> str:
    """Format a real user goal for replay after compaction/cycle."""
    trimmed = query.strip()
    if not trimmed:
        return ""
    if trimmed.startswith(USER_QUERY_OPEN):
        return trimmed
    return f"{USER_QUERY_OPEN}\n{trimmed}\n{USER_QUERY_CLOSE}"


def extract_user_query_text(text: str) -> str:
    """Pull the inner ``<user_query>`` body, or fall back to the query portion."""
    if not text:
        return ""
    match = _USER_QUERY_RE.search(text)
    if match:
        return match.group(1).strip()
    # Drop structured attachments if present (new or legacy glue).
    cut = text
    for marker in (LOCAL_CONTEXT_OPEN, "\n\n---\n", "\n---\n"):
        idx = cut.find(marker)
        if idx >= 0:
            cut = cut[:idx]
            break
    return cut.strip()


def is_compaction_bridge_message(message: Message) -> bool:
    """True when *message* is our rewrite bridge carrier."""
    if message.origin is MessageOrigin.COMPACTION_BRIDGE:
        return True
    if message.role != Role.USER:
        return False
    text = message.text_content()
    return bool(text) and COMPACTION_BRIDGE_PREFIX in text and ARCHIVED_CONTEXT_OPEN in text


def is_synthetic_user_message(message: Message) -> bool:
    """True for injected user-role messages that are not the human's request."""
    if message.role != Role.USER:
        return True
    if message.origin in {
        MessageOrigin.SYSTEM_REMINDER,
        MessageOrigin.COMPACTION_BRIDGE,
        MessageOrigin.SOFT_SEAM,
        MessageOrigin.CYCLE_SEED,
    }:
        return True
    if message.origin is MessageOrigin.REAL_USER:
        return False
    text = message.text_content().lstrip()
    if not text:
        return True
    if is_compaction_bridge_message(message):
        return True
    if text.startswith(SYSTEM_REMINDER_OPEN) or "<system-reminder>" in text[:80]:
        return True
    if text.startswith("[CYCLE STATE") or text.startswith("[CYCLE BRIEFING"):
        return True
    if text.startswith("[System]"):
        return True
    if text.startswith("**Important**: The user asked"):
        return True
    if ARCHIVED_CONTEXT_OPEN in text and 'level="' in text:
        return True
    return False


def find_last_real_user_query(messages: list[Message]) -> str | None:
    """Return the latest real user goal text (without attachment bodies)."""
    for message in reversed(messages):
        if is_synthetic_user_message(message):
            continue
        query = extract_user_query_text(message.text_content())
        if query:
            return query
    return None


def _messages_contain_real_query(messages: list[Message], query: str) -> bool:
    needle = query.strip()
    if not needle:
        return True
    for message in messages:
        if is_synthetic_user_message(message):
            continue
        text = message.text_content()
        if needle == extract_user_query_text(text) or needle in text:
            return True
    return False


def extract_compaction_bridge_text(messages: list[Message]) -> str | None:
    """Return the text of the first rewrite bridge message, if any."""
    for msg in messages:
        if not is_compaction_bridge_message(msg):
            continue
        text = msg.text_content()
        if text:
            return text
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
    *,
    last_real_query: str | None = None,
) -> list[Message]:
    """Return messages with a leading bridge and optional replayed user goal."""
    from deepseek_tui.protocol.messages import Message as Msg

    rest = [m for m in messages if not is_compaction_bridge_message(m)]
    out: list[Message] = [
        Msg.user(bridge_text, origin=MessageOrigin.COMPACTION_BRIDGE),
    ]
    query = (last_real_query or "").strip()
    if query and not _messages_contain_real_query(rest, query):
        out.append(
            Msg.user(
                format_user_query_message(query),
                origin=MessageOrigin.REAL_USER,
            )
        )
    out.extend(rest)
    return out
