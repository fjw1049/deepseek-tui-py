"""Reasoning-effort tiers reach every model family as that vendor's own fields.

The composer offers low/medium/high/xhigh/max and internal callers send
``off``; before this mapping every non-DeepSeek model silently dropped them.
"""

from __future__ import annotations

import pytest

from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.chat_messages import _should_include_reasoning
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.client.factory import _infer_thinking_supported
from deepseek_tui.client.reasoning import sent_reasoning_fields
from deepseek_tui.protocol.messages import Message, MessageRequest

_ON = {"thinking": {"type": "enabled"}}
_OFF = {"thinking": {"type": "disabled"}}


def _effort(level: str, **base: object) -> dict:
    return {**base, "reasoning_effort": level}


def _request(model: str, effort: str | None, **overrides: object) -> MessageRequest:
    return MessageRequest(
        model=model,
        messages=[Message.user("hi")],
        reasoning_effort=effort,
        **overrides,  # type: ignore[arg-type]
    )


def _openai_sent(
    model: str,
    effort: str | None,
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    **overrides: object,
) -> dict:
    client = DeepSeekClient(api_key="k", base_url=base_url)
    client.dynamic_thinking = True
    return sent_reasoning_fields(client._build_payload(_request(model, effort, **overrides)))


def _anthropic_payload(model: str, effort: str | None, **overrides: object) -> dict:
    client = AnthropicCompatClient(api_key="k", base_url="https://api.example")
    return client._build_payload(_request(model, effort, **overrides))


@pytest.mark.parametrize(
    ("model", "effort", "expected"),
    [
        # DeepSeek: thinking is on by default, so off must disable it
        # explicitly; five tiers collapse onto low / high / max.
        ("deepseek-flash", "off", _OFF),
        ("deepseek-flash", "low", _effort("low", **_ON)),
        ("deepseek-flash", "medium", _effort("high", **_ON)),
        ("deepseek-v4-pro", "high", _effort("high", **_ON)),
        ("deepseek-v4-pro", "xhigh", _effort("max", **_ON)),
        ("deepseek/deepseek-v4.1-flash", "max", _effort("max", **_ON)),
        # GLM-5.3 / 5.3-Flash: forced thinking; low / high / max only.
        ("glm-5.3", "off", {}),
        ("glm-5.3", "low", _effort("low")),
        ("glm-5.3", "medium", _effort("high")),
        ("glm-5.3-flash", "high", _effort("high")),
        ("glm-5.3-flash", "xhigh", _effort("max")),
        ("glm-5.3-flash", "max", _effort("max")),
        # GLM-5.2: toggle plus high / max.
        ("glm-5.2", "off", _OFF),
        ("glm-5.2", "low", _effort("high", **_ON)),
        ("glm-5.2", "max", _effort("max", **_ON)),
        # GLM-4.5 … 5.1: toggle only.
        ("glm-5.1", "off", _OFF),
        ("glm-4.7-flash", "max", _ON),
        # Kimi K3: no thinking field, cannot disable; low / high / max.
        ("kimi-k3", "off", {}),
        ("kimi-k3", "low", _effort("low")),
        ("moonshotai/kimi-k3", "medium", _effort("high")),
        ("kimi-k3", "max", _effort("max")),
        # Kimi K2.7-code / *-thinking always think; K2.6 toggles.
        ("kimi-k2.7-code", "off", {}),
        ("kimi-k2.7-code", "high", {}),
        ("kimi-k2-thinking", "low", {}),
        ("kimi-k2.6", "off", _OFF),
        ("kimi-k2.6", "high", _ON),
        ("kimi-k2-0905-preview", "high", {}),
        # Qwen3.8: enable_thinking + reasoning_effort low / medium / xhigh.
        ("qwen3.8-max", "off", {"enable_thinking": False}),
        ("qwen3.8-max", "low", _effort("low", enable_thinking=True)),
        ("qwen3.8-plus", "medium", _effort("medium", enable_thinking=True)),
        ("qwen3.8-plus", "high", _effort("xhigh", enable_thinking=True)),
        ("qwen3.8-flash", "max", _effort("xhigh", enable_thinking=True)),
        # Qwen3 … 3.7: enable_thinking + thinking_budget.
        ("qwen3.5-plus", "off", {"enable_thinking": False}),
        ("qwen3-max", "low", {"enable_thinking": True, "thinking_budget": 1024}),
        ("qwen-plus", "medium", {"enable_thinking": True, "thinking_budget": 8192}),
        ("qwen3.7-plus", "max", {"enable_thinking": True}),
        ("qwq-plus", "off", {}),
        ("qwq-plus", "low", {"thinking_budget": 1024}),
        ("qwen3-coder-plus", "high", {}),
        # Doubao Seed: toggle.
        ("doubao-seed-2.0-code", "off", _OFF),
        ("doubao-seed-2.0-code", "high", _ON),
        # Aliases and unknown models / values.
        ("glm-5.2", "highest", _effort("max", **_ON)),
        ("glm-5.1", "disabled", _OFF),
        ("glm-5.1", "turbo", {}),
        ("glm-5.1", None, {}),
        ("some-custom-model", "high", {}),
    ],
)
def test_openai_payload_carries_vendor_reasoning_fields(model, effort, expected) -> None:
    assert _openai_sent(model, effort) == expected


@pytest.mark.parametrize("model", ["glm-5.3", "glm-5.3-flash", "kimi-k3", "qwen3.8-max"])
def test_supported_tiers_produce_distinct_requests(model) -> None:
    sent = [_openai_sent(model, effort) for effort in ("low", "high", "max")]
    assert sent[0] != sent[1]
    assert sent[0] != sent[2]


@pytest.mark.parametrize(
    "model",
    ["deepseek-flash", "deepseek-v4.1-flash", "deepseek/deepseek-v4-pro", "deepseek-v5-pro"],
)
def test_latest_deepseek_models_detected_on_any_host(model) -> None:
    assert _infer_thinking_supported("https://openrouter.ai/api/v1", model)


def test_deepseek_fields_need_a_deepseek_capable_endpoint() -> None:
    client = DeepSeekClient(api_key="k", base_url="https://example.com/v1")
    payload = client._build_payload(_request("deepseek-flash", "high"))
    assert sent_reasoning_fields(payload) == {}


def test_forced_tool_choice_drops_enable_but_keeps_off() -> None:
    forced = {"tool_choice": "required"}
    assert _openai_sent("glm-5.1", "high", **forced) == {}
    assert _openai_sent("glm-5.1", "off", **forced) == _OFF
    assert _openai_sent("deepseek-flash", "off", **forced) == _OFF


def test_extra_body_overrides_vendor_fields() -> None:
    sent = _openai_sent("glm-5.1", "high", extra_body={"thinking": {"type": "disabled"}})
    assert sent == _OFF


def test_unsupported_tier_is_logged(caplog) -> None:
    with caplog.at_level("INFO", logger="deepseek_tui.client.reasoning"):
        assert _openai_sent("kimi-k3", "off") == {}
    assert "reasoning_effort_unsupported model=kimi-k3 effort=off protocol=openai" in caplog.text


# --- reasoning_content replay -------------------------------------------------


@pytest.mark.parametrize(
    ("model", "effort", "expected"),
    [
        ("deepseek-flash", "high", True),
        ("deepseek-flash", "off", False),
        ("kimi-k3", "high", True),
        ("kimi-k3", "off", True),
        ("kimi-k2.7-code", "off", True),
        ("kimi-k2.6", "high", True),
        ("kimi-k2.6", "off", False),
        ("kimi-k2-0905-preview", "high", False),
        ("glm-5.3", "high", False),
    ],
)
def test_reasoning_replay_follows_vendor_rules(model, effort, expected) -> None:
    assert _should_include_reasoning(model, effort) is expected


# --- Anthropic format -------------------------------------------------------


@pytest.mark.parametrize(
    ("effort", "budget"),
    [("low", 1024), ("medium", 4096), ("high", 8192), ("xhigh", 16384), ("max", 32768)],
)
def test_anthropic_tiers_map_to_budget(effort, budget) -> None:
    payload = _anthropic_payload("glm-5.1", effort, max_tokens=65536)
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": budget}


def _effort_config(level: str) -> dict:
    return {"output_config": {"effort": level}}


@pytest.mark.parametrize(
    ("model", "effort", "expected"),
    [
        ("deepseek-flash", "off", _OFF),
        ("deepseek-flash", "low", _effort_config("low")),
        ("deepseek-v4-pro", "medium", _effort_config("high")),
        ("deepseek-v4.1-flash", "xhigh", _effort_config("max")),
        ("glm-5.3", "off", {}),
        ("glm-5.3", "low", _effort_config("low")),
        ("glm-5.3", "medium", _effort_config("high")),
        ("glm-5.3-flash", "max", _effort_config("max")),
        ("glm-5.2", "off", _OFF),
        ("glm-5.2", "low", _effort_config("high")),
        ("kimi-k3", "off", {}),
        ("kimi-k3", "low", _effort_config("low")),
        ("kimi-k3", "max", _effort_config("max")),
        ("qwen3.8-max", "off", _OFF),
        ("qwen3.8-max", "medium", _effort_config("medium")),
        ("qwen3.8-flash", "max", _effort_config("xhigh")),
        ("kimi-k2.7-code", "high", {}),
    ],
)
def test_anthropic_payload_carries_vendor_effort(model, effort, expected) -> None:
    payload = _anthropic_payload(model, effort, max_tokens=65536)
    assert sent_reasoning_fields(payload) == expected


def test_anthropic_effort_survives_custom_sampling() -> None:
    payload = _anthropic_payload("glm-5.3", "low", temperature=0.1, max_tokens=768)
    assert payload["output_config"] == {"effort": "low"}


def test_anthropic_budget_fits_below_max_tokens() -> None:
    assert _anthropic_payload("glm-5.1", "max", max_tokens=8000)["thinking"] == {
        "type": "enabled",
        "budget_tokens": 7999,
    }
    assert "thinking" not in _anthropic_payload("glm-5.1", "max", max_tokens=768)


def test_anthropic_unregistered_model_keeps_only_off() -> None:
    assert "thinking" not in _anthropic_payload("claude-opus-5-5", "high", max_tokens=65536)
    assert _anthropic_payload("claude-opus-5-5", "off")["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"tool_choice": {"type": "tool", "name": "narration"}},
        {"temperature": 0.1},
        {"top_p": 0.9},
        {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 2048}}},
    ],
)
def test_anthropic_enable_yields_to_conflicts_and_config(overrides) -> None:
    payload = _anthropic_payload("glm-5.1", "high", max_tokens=65536, **overrides)
    assert payload.get("thinking") == overrides.get("extra_body", {}).get("thinking")
