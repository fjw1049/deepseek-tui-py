"""Evolution-specific turn signals (not base gates)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from deepseek_tui.post_turn.evidence import TurnEvidence

_CORRECTION_RE = re.compile(
    r"(不对|应该|别用|error|wrong|incorrect|instead|不要|错了)",
    re.IGNORECASE,
)
_REMEMBER_PROCEDURE_RE = re.compile(
    r"(记住流程|保存为 skill|save as skill|remember (?:the )?procedure|"
    r"remember how to|下次这样)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class EvolutionSignals:
    high_tool_rounds: bool = False
    recovery_after_failure: bool = False
    user_correction: bool = False
    explicit_remember_procedure: bool = False
    load_skill_gap: bool = False

    def any(self) -> bool:
        return any(
            getattr(self, field.name)
            for field in __import__("dataclasses").fields(self)
        )


def detect_signals(
    evidence: TurnEvidence,
    messages: list[dict[str, Any]],
    *,
    min_tool_calls: int = 5,
) -> EvolutionSignals:
    text = evidence.user_text.strip()
    high_tool_rounds = evidence.tool_rounds >= min_tool_calls
    user_correction = bool(_CORRECTION_RE.search(text))
    explicit_remember_procedure = bool(_REMEMBER_PROCEDURE_RE.search(text))
    recovery_after_failure = _detect_recovery_after_failure(messages)
    load_skill_gap = _detect_load_skill_gap(messages)
    return EvolutionSignals(
        high_tool_rounds=high_tool_rounds,
        recovery_after_failure=recovery_after_failure,
        user_correction=user_correction,
        explicit_remember_procedure=explicit_remember_procedure,
        load_skill_gap=load_skill_gap,
    )


def _detect_recovery_after_failure(messages: list[dict[str, Any]]) -> bool:
    saw_error = False
    for msg in messages:
        content = str(msg.get("content", "") or "")
        role = str(msg.get("role", "") or "")
        if role == "tool" and ("error" in content.lower() or content.startswith("Error")):
            saw_error = True
        elif saw_error and role in ("tool", "assistant") and content.strip():
            if "error" not in content.lower()[:20]:
                return True
    return False


def _detect_load_skill_gap(messages: list[dict[str, Any]]) -> bool:
    loaded_skill = False
    for msg in messages:
        content = str(msg.get("content", "") or "").lower()
        if "load_skill" in content or "loaded skill" in content:
            loaded_skill = True
        if loaded_skill and msg.get("role") == "tool":
            if content.startswith("error") or " failed" in content:
                return True
    return False
