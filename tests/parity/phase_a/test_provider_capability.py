"""Parity tests for the provider capability matrix.

Mirrors the unit tests in ``crates/tui/src/config.rs`` and
``crates/tui/src/models.rs`` for ``ApiProvider::parse``,
``ProviderKind::parse``, ``provider_capability``,
``context_window_for_model`` (including the ``NNNk`` hint path),
``canonical_model_name``, ``normalize_model_name``, and
``deprecation_for_model``.
"""

from __future__ import annotations

import pytest

from deepseek_tui.config.provider_registry import (
    DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS,
    DEFAULT_COMPACTION_MESSAGE_THRESHOLD,
    DEFAULT_COMPACTION_TOKEN_THRESHOLD,
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    MODEL_ALIASES,
    PROVIDER_DEFAULTS,
    ApiProvider,
    ProviderKind,
    RequestPayloadMode,
    canonical_model_name,
    compaction_message_threshold_for_model,
    compaction_threshold_for_model,
    context_window_for_model,
    deprecation_for_model,
    normalize_model,
    normalize_model_name,
    provider_capability,
)

# ---------------------------------------------------------------------------
# 1. ProviderKind / ApiProvider parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("deepseek", ProviderKind.DEEPSEEK),
        ("DeepSeek", ProviderKind.DEEPSEEK),
        ("deep-seek", ProviderKind.DEEPSEEK),
        ("nvidia", ProviderKind.NVIDIA_NIM),
        ("nvidia-nim", ProviderKind.NVIDIA_NIM),
        ("nvidia_nim", ProviderKind.NVIDIA_NIM),
        ("nim", ProviderKind.NVIDIA_NIM),
        ("openai", ProviderKind.OPENAI),
        ("open-ai", ProviderKind.OPENAI),
        ("openrouter", ProviderKind.OPENROUTER),
        ("open_router", ProviderKind.OPENROUTER),
        ("novita", ProviderKind.NOVITA),
        ("  NOVITA  ", ProviderKind.NOVITA),  # trim + ci
    ],
)
def test_provider_kind_parse_accepts_known_aliases(
    alias: str, expected: ProviderKind
) -> None:
    assert ProviderKind.parse(alias) is expected


def test_provider_kind_parse_returns_none_for_unknown() -> None:
    assert ProviderKind.parse("anthropic") is None
    assert ProviderKind.parse("") is None
    assert ProviderKind.parse("   ") is None


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("deepseek", ApiProvider.DEEPSEEK),
        ("deep-seek", ApiProvider.DEEPSEEK),
        ("deepseek-cn", ApiProvider.DEEPSEEK_CN),
        ("deepseek_china", ApiProvider.DEEPSEEK_CN),
        ("deepseekcn", ApiProvider.DEEPSEEK_CN),
        ("deepseek-china", ApiProvider.DEEPSEEK_CN),
        ("nvidia", ApiProvider.NVIDIA_NIM),
        ("nvidia-nim", ApiProvider.NVIDIA_NIM),
        ("nvidia_nim", ApiProvider.NVIDIA_NIM),
        ("nim", ApiProvider.NVIDIA_NIM),
        ("openrouter", ApiProvider.OPENROUTER),
        ("open_router", ApiProvider.OPENROUTER),
        ("novita", ApiProvider.NOVITA),
        ("fireworks", ApiProvider.FIREWORKS),
        ("fireworks-ai", ApiProvider.FIREWORKS),
        ("sglang", ApiProvider.SGLANG),
        ("sg-lang", ApiProvider.SGLANG),
    ],
)
def test_api_provider_parse_accepts_known_aliases(
    alias: str, expected: ApiProvider
) -> None:
    assert ApiProvider.parse(alias) is expected


def test_api_provider_parse_returns_none_for_unknown() -> None:
    assert ApiProvider.parse("openai") is None  # NB: not in ApiProvider!
    assert ApiProvider.parse("claude") is None
    assert ApiProvider.parse("") is None


def test_api_provider_all_has_seven_variants_in_picker_order() -> None:
    assert ApiProvider.all() == [
        ApiProvider.DEEPSEEK,
        ApiProvider.DEEPSEEK_CN,
        ApiProvider.NVIDIA_NIM,
        ApiProvider.OPENROUTER,
        ApiProvider.NOVITA,
        ApiProvider.FIREWORKS,
        ApiProvider.SGLANG,
    ]


def test_api_provider_display_name() -> None:
    assert ApiProvider.DEEPSEEK.display_name == "DeepSeek"
    assert ApiProvider.DEEPSEEK_CN.display_name == "DeepSeek (中国)"
    assert ApiProvider.NVIDIA_NIM.display_name == "NVIDIA NIM"
    assert ApiProvider.SGLANG.display_name == "SGLang"


def test_provider_kind_canonical_is_wire_value() -> None:
    assert ProviderKind.DEEPSEEK.canonical == "deepseek"
    assert ProviderKind.NVIDIA_NIM.canonical == "nvidia-nim"


# ---------------------------------------------------------------------------
# 2. canonical_model_name / normalize_model_name / deprecation_for_model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("deepseek-v4-pro", "deepseek-v4-pro"),
        ("deepseek-v4pro", "deepseek-v4-pro"),
        ("DEEPSEEK-V4-PRO", "deepseek-v4-pro"),
        (" deepseek-v4-flash ", "deepseek-v4-flash"),
        ("deepseek-chat", "deepseek-v4-flash"),
        ("deepseek-reasoner", "deepseek-v4-flash"),
        ("deepseek-r1", "deepseek-v4-flash"),
        ("deepseek-v3", "deepseek-v4-flash"),
        ("deepseek-v3.2", "deepseek-v4-flash"),
    ],
)
def test_canonical_model_name_covers_known_aliases(
    raw: str, expected: str
) -> None:
    assert canonical_model_name(raw) == expected


def test_canonical_model_name_returns_none_for_unknown() -> None:
    assert canonical_model_name("gpt-4") is None
    assert canonical_model_name("deepseek-v5") is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("deepseek-v4-pro", "deepseek-v4-pro"),
        ("deepseek-chat", "deepseek-v4-flash"),
        ("deepseek-some-future-64k", "deepseek-some-future-64k"),  # accepted
        ("DEEPSEEK-FUTURE", "deepseek-future"),
    ],
)
def test_normalize_model_name_accepts_deepseek_prefixed(
    raw: str, expected: str
) -> None:
    assert normalize_model_name(raw) == expected


def test_normalize_model_name_rejects_non_deepseek() -> None:
    assert normalize_model_name("gpt-4") is None
    assert normalize_model_name("") is None
    assert normalize_model_name("   ") is None


def test_normalize_model_name_rejects_bad_chars() -> None:
    # `*` is outside the allowed alphabet.
    assert normalize_model_name("deepseek-v*-pro") is None


def test_deprecation_for_model_lists_all_five_aliases() -> None:
    for alias in (
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-r1",
        "deepseek-v3",
        "deepseek-v3.2",
    ):
        record = deprecation_for_model(alias)
        assert record is not None, alias
        assert record.alias == alias
        assert record.replacement == "deepseek-v4-flash"
        assert "Deprecated" in record.notice


def test_deprecation_for_model_returns_none_for_current_model() -> None:
    assert deprecation_for_model("deepseek-v4-pro") is None
    assert deprecation_for_model("deepseek-v4-flash") is None


def test_deprecation_for_model_is_case_insensitive() -> None:
    assert deprecation_for_model("DeepSeek-Chat") is not None


# ---------------------------------------------------------------------------
# 3. context_window_for_model
# ---------------------------------------------------------------------------


def test_context_window_v4_is_one_million() -> None:
    assert context_window_for_model("deepseek-v4-pro") == 1_000_000
    assert context_window_for_model("deepseek-v4-flash") == 1_000_000


def test_context_window_legacy_aliases_get_v4_window() -> None:
    # models.rs:214-216 — the five current deepseek legacy aliases all
    # resolve to the 1M context window.
    for alias in (
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-r1",
        "deepseek-v3",
        "deepseek-v3.2",
    ):
        assert context_window_for_model(alias) == DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS


def test_context_window_unknown_deepseek_is_default() -> None:
    # Unknown DeepSeek model IDs default to 128k.
    assert context_window_for_model("deepseek-chat-classic") == DEFAULT_CONTEXT_WINDOW_TOKENS


def test_context_window_claude_is_200k() -> None:
    assert context_window_for_model("claude-3-opus") == 200_000


def test_context_window_unknown_non_deepseek_is_default() -> None:
    # Caller-facing behaviour: returns the default 128k when the model
    # isn't recognised. (The internal optional returns None.)
    assert context_window_for_model("gpt-4") == DEFAULT_CONTEXT_WINDOW_TOKENS


@pytest.mark.parametrize(
    "model,expected",
    [
        ("deepseek-128k", 128_000),
        ("deepseek-256k", 256_000),
        ("deepseek-1024k", 1_024_000),
        ("deepseek-8k", 8_000),
    ],
)
def test_context_window_parses_kilo_suffix(model: str, expected: int) -> None:
    assert context_window_for_model(model) == expected


def test_context_window_ignores_out_of_range_kilo_hints() -> None:
    # 4k < 8 min → ignored → fall back to default 128k (still a deepseek model).
    assert context_window_for_model("deepseek-4k") == DEFAULT_CONTEXT_WINDOW_TOKENS
    # 2048k > 1024 max → ignored.
    assert context_window_for_model("deepseek-2048k") == DEFAULT_CONTEXT_WINDOW_TOKENS


def test_context_window_ignores_embedded_digits_without_k_boundary() -> None:
    # ``v4`` digit sequence has no ``k`` after, must not be mistaken for
    # a context hint. The model still resolves via v4 family lookup.
    assert context_window_for_model("deepseek-v4-pro") == DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS


# ---------------------------------------------------------------------------
# 4. compaction thresholds
# ---------------------------------------------------------------------------


def test_compaction_threshold_is_eighty_percent_of_window() -> None:
    assert compaction_threshold_for_model("deepseek-v4-pro") == (
        DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS * 80 // 100
    )


def test_compaction_threshold_defaults_for_unknown_model() -> None:
    assert compaction_threshold_for_model("unknown") == DEFAULT_COMPACTION_TOKEN_THRESHOLD


def test_compaction_message_threshold_scales_with_window() -> None:
    # V4's 1M window → 10× default.
    assert compaction_message_threshold_for_model("deepseek-v4-pro") == (
        DEFAULT_COMPACTION_MESSAGE_THRESHOLD * 10
    )
    # Unknown → default.
    assert compaction_message_threshold_for_model("weird") == DEFAULT_COMPACTION_MESSAGE_THRESHOLD


# ---------------------------------------------------------------------------
# 5. provider_capability
# ---------------------------------------------------------------------------


def test_provider_capability_v4_pro_on_deepseek() -> None:
    cap = provider_capability(ApiProvider.DEEPSEEK, "deepseek-v4-pro")
    assert cap.provider is ApiProvider.DEEPSEEK
    assert cap.resolved_model == "deepseek-v4-pro"
    assert cap.context_window == DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS
    assert cap.max_output == 262_144
    assert cap.thinking_supported is True
    assert cap.cache_telemetry_supported is True
    assert cap.request_payload_mode is RequestPayloadMode.CHAT_COMPLETIONS
    assert cap.deprecation is None


def test_provider_capability_v4_flash_on_novita() -> None:
    cap = provider_capability(ApiProvider.NOVITA, "deepseek/deepseek-v4-flash")
    assert cap.context_window == DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS
    assert cap.max_output == 262_144
    assert cap.thinking_supported is True
    # Novita is NOT in the cache-telemetry list — only DeepSeek and NVIDIA NIM.
    assert cap.cache_telemetry_supported is False


def test_provider_capability_non_v4_model_gets_4k_max_output() -> None:
    cap = provider_capability(ApiProvider.DEEPSEEK, "deepseek-chat-classic")
    assert cap.max_output == 4096
    assert cap.thinking_supported is False


def test_provider_capability_cache_telemetry_lives_on_deepseek_family() -> None:
    assert provider_capability(
        ApiProvider.DEEPSEEK, "deepseek-v4-pro"
    ).cache_telemetry_supported is True
    assert provider_capability(
        ApiProvider.DEEPSEEK_CN, "deepseek-v4-pro"
    ).cache_telemetry_supported is True
    assert provider_capability(
        ApiProvider.NVIDIA_NIM, "deepseek-ai/deepseek-v4-pro"
    ).cache_telemetry_supported is True
    for p in (
        ApiProvider.OPENROUTER,
        ApiProvider.NOVITA,
        ApiProvider.FIREWORKS,
        ApiProvider.SGLANG,
    ):
        assert (
            provider_capability(p, "deepseek-v4-pro").cache_telemetry_supported
            is False
        ), p


def test_provider_capability_deprecation_is_attached() -> None:
    cap = provider_capability(ApiProvider.DEEPSEEK, "deepseek-chat")
    assert cap.deprecation is not None
    assert cap.deprecation.alias == "deepseek-chat"
    assert cap.deprecation.replacement == "deepseek-v4-flash"


# ---------------------------------------------------------------------------
# 6. Legacy API compatibility
# ---------------------------------------------------------------------------


def test_legacy_normalize_model_returns_canonical_for_known_alias() -> None:
    assert normalize_model("deepseek-chat") == "deepseek-v4-flash"
    assert normalize_model("deepseek-v4-pro") == "deepseek-v4-pro"


def test_legacy_normalize_model_passes_through_unknown() -> None:
    # This is the intentionally-lax behaviour the old callers rely on.
    assert normalize_model("gpt-4") == "gpt-4"


def test_legacy_model_aliases_cover_five_deprecations() -> None:
    for alias in (
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-r1",
        "deepseek-v3",
        "deepseek-v3.2",
    ):
        assert MODEL_ALIASES[alias] == "deepseek-v4-flash"


def test_legacy_provider_defaults_covers_seven_providers() -> None:
    for name in (
        "deepseek",
        "openai",
        "nvidia-nim",
        "openrouter",
        "novita",
        "fireworks",
        "sglang",
    ):
        assert name in PROVIDER_DEFAULTS
