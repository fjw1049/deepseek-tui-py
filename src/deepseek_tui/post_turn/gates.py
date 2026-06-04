"""Shared turn quality gates for memory capture and evolution review."""

from __future__ import annotations

import re
from dataclasses import dataclass

from deepseek_tui.post_turn.evidence import TurnEvidence

_CONFIRM_ONLY = re.compile(
    r"^(?:好的?|继续|ok|okay|yes|yep|sure|thanks?|thank you|got it|"
    r"明白|知道了|嗯|行|可以|收到)[\s!.。]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GateConfig:
    min_chars: int = 20
    skip_slash: bool = True
    skip_confirmations: bool = True
    require_success: bool = True


def passes_base_gate(evidence: TurnEvidence, cfg: GateConfig) -> bool:
    if cfg.require_success and not evidence.success:
        return False
    text = evidence.user_text.strip()
    if cfg.skip_slash and text.startswith("/"):
        return False
    if len(text) < cfg.min_chars:
        return False
    if cfg.skip_confirmations and _CONFIRM_ONLY.match(text):
        return False
    return True


def should_capture(evidence: TurnEvidence, cfg: GateConfig) -> bool:
    if not evidence.success:
        return False
    if evidence.had_tool_calls:
        return True
    return passes_base_gate(evidence, cfg)


def should_review(
    evidence: TurnEvidence,
    *,
    cfg: GateConfig,
    scheduler_due: bool,
    signals: object,
) -> bool:
    if evidence.flush_mode:
        return True
    if not evidence.success:
        return False
    if not passes_base_gate(evidence, cfg):
        return False
    if scheduler_due:
        return True
    any_fn = getattr(signals, "any", None)
    if callable(any_fn):
        return bool(any_fn())
    return False
