"""Per-vendor reasoning-effort mapping.

The composer offers five tiers (low/medium/high/xhigh/max) and internal
callers also use ``off``. Every vendor exposes a different knob, so this
module translates the tier into that vendor's own request fields.

Sources (vendor docs, not verified against live endpoints):

- DeepSeek (api-docs.deepseek.com/guides/thinking_mode): ``thinking.type``
  enabled/disabled, ``reasoning_effort`` low/high/max; thinking is on by
  default at high. Anthropic format: ``output_config.effort``.
- GLM-4.5 … 5.1: ``thinking.type`` enabled/disabled (docs.z.ai).
- GLM-5.2: adds ``reasoning_effort`` high/max (third-party docs).
- GLM-5.3 / 5.3-Flash: forced thinking, cannot be disabled (docs.z.ai);
  ``reasoning_effort`` low/high/max, default max, ``medium`` rejected
  (third-party docs).
- Kimi K3: no ``thinking`` field, always reasons; ``reasoning_effort``
  low/high/max, default max. K2.7-code and ``*-thinking`` always think and
  take neither field. K2.5/K2.6: ``thinking.type`` enabled/disabled
  (platform.kimi.ai).
- Qwen3.8: ``enable_thinking`` + ``reasoning_effort`` low/medium/xhigh,
  default xhigh; must not be combined with ``thinking_budget``. Qwen3 …
  3.7: ``enable_thinking`` + ``thinking_budget``. QwQ / ``*-thinking``
  always think (docs.qwencloud.com).
- Doubao Seed: ``thinking.type`` enabled/disabled (Volcengine Ark).
- Anthropic format (help.aliyun.com/zh/model-studio/anthropic-api-messages):
  ``output_config.effort`` for glm-5.3 (low/high/max), glm-5.2 and
  deepseek-v4 (high/max), qwen3.8 (low/medium/xhigh); ``budget_tokens`` is
  being deprecated and glm-5.3 ignores it. Kimi K3 is undocumented there
  and gets ``output_config.effort`` too.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

TIERS = ("off", "low", "medium", "high", "xhigh", "max")
_ALIASES = {
    "minimal": "low",
    "mid": "medium",
    "highest": "max",
    "maximum": "max",
    "disabled": "off",
    "none": "off",
    "false": "off",
}

# Tier -> OpenAI-format request fields. A missing tier means the model
# cannot honour it; an empty dict means the server default already matches.
Profile = dict[str, dict[str, Any]]

_ON = {"thinking": {"type": "enabled"}}
_OFF = {"thinking": {"type": "disabled"}}
_TOGGLE: Profile = {"off": _OFF, **{tier: _ON for tier in TIERS[1:]}}
_ALWAYS_THINKS: Profile = {tier: {} for tier in TIERS[1:]}


def _efforts(low: str, medium: str, high: str, top: str, **base: Any) -> Profile:
    """Collapse the five tiers onto a vendor's ``reasoning_effort`` levels."""
    levels = {"low": low, "medium": medium, "high": high, "xhigh": top, "max": top}
    return {tier: {**base, "reasoning_effort": level} for tier, level in levels.items()}


DEEPSEEK: Profile = {"off": _OFF, **_efforts("low", "high", "high", "max", **_ON)}
_GLM_52: Profile = {"off": _OFF, **_efforts("high", "high", "high", "max", **_ON)}
_GLM_53: Profile = _efforts("low", "high", "high", "max")
_KIMI_K3: Profile = _efforts("low", "high", "high", "max")
_QWEN_38: Profile = {
    "off": {"enable_thinking": False},
    **_efforts("low", "medium", "xhigh", "xhigh", enable_thinking=True),
}
_QWEN_HYBRID: Profile = {
    "off": {"enable_thinking": False},
    "low": {"enable_thinking": True, "thinking_budget": 1024},
    "medium": {"enable_thinking": True, "thinking_budget": 8192},
    "high": {"enable_thinking": True},
    "xhigh": {"enable_thinking": True},
    "max": {"enable_thinking": True},
}
_QWEN_ALWAYS_THINKS: Profile = {
    **_ALWAYS_THINKS,
    "low": {"thinking_budget": 1024},
    "medium": {"thinking_budget": 8192},
}

# How a family's tiers travel on the Anthropic format: as a thinking
# ``budget_tokens``, as ``output_config.effort``, or not at all.
_BUDGET = "budget"
_EFFORT = "effort"
_ANTHROPIC_BUDGETS = {"low": 1024, "medium": 4096, "high": 8192, "xhigh": 16384, "max": 32768}
_ANTHROPIC_MIN_BUDGET = 1024

_REASONING_KEYS = (
    "thinking",
    "reasoning_effort",
    "enable_thinking",
    "thinking_budget",
    "output_config",
)


def normalize_effort(effort: str | None) -> str | None:
    """Map an effort value (with aliases) onto ``TIERS``; None when unset or unknown."""
    if effort is None or not effort.strip():
        return None
    key = effort.strip().lower()
    key = _ALIASES.get(key, key)
    if key not in TIERS:
        logger.info("reasoning_effort_unknown effort=%s", effort)
        return None
    return key


def _version(match: re.Match[str]) -> tuple[int, int]:
    return int(match[1]), int(match[2] or 0)


def is_deepseek_reasoning_model(model: str) -> bool:
    """DeepSeek V4+ models (any host) that take DeepSeek's thinking fields."""
    return re.search(r"deepseek-(v[4-9]|v\d{2,}|flash|pro)", model.lower()) is not None


def _family(model: str) -> tuple[Profile, str | None] | None:
    """Return ``(openai profile, anthropic style)`` for a known model family."""
    if is_deepseek_reasoning_model(model):
        return DEEPSEEK, _EFFORT
    name = model.strip().lower().rsplit("::", 1)[-1].rsplit("/", 1)[-1]
    # Verified gateway alias; normalize only for capability lookup.
    if name == "qwen-3-8-max":
        name = "qwen3.8-max"
    if m := re.match(r"glm-(\d+)(?:\.(\d+))?", name):
        version = _version(m)
        if version >= (5, 3):
            return _GLM_53, _EFFORT
        if version >= (5, 2):
            return _GLM_52, _EFFORT
        return (_TOGGLE, _BUDGET) if version >= (4, 5) else None
    if m := re.match(r"kimi-k(\d+)(?:\.(\d+))?", name):
        version = _version(m)
        if version >= (3, 0):
            return _KIMI_K3, _EFFORT
        if "thinking" in name or "code" in name:
            return _ALWAYS_THINKS, None
        return (_TOGGLE, _BUDGET) if version >= (2, 5) else None
    if name.startswith("qwq") or (name.startswith("qwen") and "thinking" in name):
        return _QWEN_ALWAYS_THINKS, _BUDGET
    if m := re.match(r"qwen(\d+)(?:\.(\d+))?", name):
        version = _version(m)
        if version < (3, 0) or "instruct" in name or "coder" in name:
            return None
        return (_QWEN_38, _EFFORT) if version >= (3, 8) else (_QWEN_HYBRID, _BUDGET)
    if re.match(r"qwen-(plus|flash|turbo)", name):
        return _QWEN_HYBRID, _BUDGET
    if name.startswith("doubao-seed"):
        return _TOGGLE, _BUDGET
    return None


def _unsupported(model: str, effort: str | None, protocol: str) -> None:
    logger.info(
        "reasoning_effort_unsupported model=%s effort=%s protocol=%s", model, effort, protocol
    )


def openai_reasoning_fields(
    model: str, effort: str | None, *, deepseek: bool = False
) -> tuple[str | None, dict[str, Any]]:
    """Return ``(tier, fields)`` to merge into an OpenAI-format payload.

    ``deepseek`` marks an endpoint known to take DeepSeek's fields; without
    it DeepSeek models get nothing, since other hosts may reject them.
    ``fields`` is empty when nothing should be sent: no selection, an
    unregistered model, or a tier the model cannot honour.
    """
    tier = normalize_effort(effort)
    family = _family(model)
    if deepseek:
        profile: Profile | None = DEEPSEEK
    elif family is None or family[0] is DEEPSEEK:
        profile = None
    else:
        profile = family[0]
    if tier is None or profile is None:
        return tier, {}
    if tier not in profile:
        _unsupported(model, effort, "openai")
        return tier, {}
    return tier, copy.deepcopy(profile[tier])


def anthropic_reasoning_fields(
    model: str, effort: str | None, max_tokens: int
) -> tuple[str | None, dict[str, Any]]:
    """Return ``(tier, fields)`` to merge into an Anthropic-format payload.

    ``off`` disables thinking for any model unless its family cannot turn it
    off. Other tiers only apply to registered families: a ``budget_tokens``
    that fits below ``max_tokens``, or ``output_config.effort``.
    """
    tier = normalize_effort(effort)
    family = _family(model)
    if tier == "off":
        if family is not None and "off" not in family[0]:
            _unsupported(model, effort, "anthropic")
            return tier, {}
        return tier, {"thinking": {"type": "disabled"}}
    if tier is None or family is None:
        return tier, {}
    profile, style = family
    if tier not in profile or style is None:
        _unsupported(model, effort, "anthropic")
        return tier, {}
    if style == _EFFORT:
        return tier, {"output_config": {"effort": profile[tier]["reasoning_effort"]}}
    budget = min(_ANTHROPIC_BUDGETS[tier], max_tokens - 1)
    if budget < _ANTHROPIC_MIN_BUDGET:
        return tier, {}
    return tier, {"thinking": {"type": "enabled", "budget_tokens": budget}}


def sent_reasoning_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """The reasoning-control fields actually present in a request payload."""
    return {key: payload[key] for key in _REASONING_KEYS if key in payload}
