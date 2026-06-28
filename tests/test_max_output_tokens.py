"""Regression tests for per-model output-token budgets.

GLM-5.2 is a heavy reasoning model: it streams large ``reasoning_content`` and
its reasoning alone exhausts the legacy 4096 cap, so the round is
length-truncated before any answer ``content`` is produced (the engine then
falls back to dumping raw, truncated reasoning as the final answer). It must get
a budget large enough to finish thinking *and* emit the answer.
"""

from __future__ import annotations

from deepseek_tui.config.providers import max_output_tokens_for_model


def test_glm_gets_headroom_above_legacy_cap() -> None:
    assert max_output_tokens_for_model("glm-5.2") == 32_768
    assert max_output_tokens_for_model("GLM-4.6") == 32_768


def test_v4_keeps_large_budget() -> None:
    assert max_output_tokens_for_model("deepseek-v4-pro") == 262_144
    assert max_output_tokens_for_model("deepseek-v4-flash") == 262_144


def test_unknown_model_keeps_default() -> None:
    assert max_output_tokens_for_model("deepseek-chat") == 4096
