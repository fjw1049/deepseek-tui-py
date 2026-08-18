"""Unknown models default to 500K — never the old 128K fallback."""

from __future__ import annotations

from deepseek_tui.config.providers import (
    CUSTOM_MODEL_CONTEXT_WINDOW_TOKENS,
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    context_window_for_model,
)


def test_unknown_model_default_is_500k_not_128k() -> None:
    assert DEFAULT_CONTEXT_WINDOW_TOKENS == 500_000
    assert CUSTOM_MODEL_CONTEXT_WINDOW_TOKENS == 500_000
    for model in ("kimi-k3", "kimi-k2.6", "glm-5.1", "glm-5.2", "custom-foo"):
        assert context_window_for_model(model) == 500_000


def test_known_models_keep_their_own_windows() -> None:
    assert context_window_for_model("deepseek-v4-pro") == 1_000_000
    assert context_window_for_model("gpt-4o") == 128_000
    assert context_window_for_model("claude-sonnet") == 200_000
