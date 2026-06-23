"""Provider catalogue + capability matrix.

Mirrors three Rust sources:

* ``crates/config/src/lib.rs``       —   ProviderKind enum, defaults
* ``crates/tui/src/config.rs``       —   ApiProvider enum (7 variants),
                                          ProviderCapability,
                                          ModelDeprecation, payload mode,
                                          canonical_model_name,
                                          normalize_model_name,
                                          provider_capability,
                                          deprecation_for_model
* ``crates/tui/src/models.rs``       —   context_window_for_model,
                                          compaction_threshold_for_model,
                                          compaction_message_threshold_for_model
                                          + DEFAULT_CONTEXT_WINDOW_TOKENS,
                                          DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS,
                                          DEFAULT_COMPACTION_*_THRESHOLD

Backwards-compatibility: the legacy ``PROVIDER_DEFAULTS``, ``MODEL_ALIASES``,
``normalize_model``, and ``context_window_for_model`` symbols stay
available under their old names; they now delegate to the Rust-parity
implementations below.
"""

from __future__ import annotations



from dataclasses import dataclass
from enum import Enum

__all__ = [
    "ApiProvider",
    "DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS",
    "DEFAULT_COMPACTION_MESSAGE_THRESHOLD",
    "DEFAULT_COMPACTION_TOKEN_THRESHOLD",
    "DEFAULT_CONTEXT_WINDOW_TOKENS",
    "MODEL_ALIASES",
    "ModelDeprecation",
    "PROVIDER_DEFAULTS",
    "ProviderCapability",
    "ProviderDefaults",
    "ProviderKind",
    "RequestPayloadMode",
    "canonical_model_name",
    "compaction_message_threshold_for_model",
    "compaction_threshold_for_model",
    "context_window_for_model",
    "deprecation_for_model",
    "max_output_tokens_for_model",
    "normalize_model",
    "normalize_model_name",
    "provider_capability",
]


# ---------------------------------------------------------------------------
# Constants (mirror crates/tui/src/models.rs:5-8)
# ---------------------------------------------------------------------------

DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS = 1_000_000
DEFAULT_COMPACTION_TOKEN_THRESHOLD = 50_000
DEFAULT_COMPACTION_MESSAGE_THRESHOLD = 50

# 80% of context window is the compaction threshold (models.rs:273).
_COMPACTION_THRESHOLD_PERCENT = 80


# ---------------------------------------------------------------------------
# ProviderKind (config/lib.rs:25-59)
# ---------------------------------------------------------------------------


class ProviderKind(str, Enum):
    """Mirror of Rust ``ProviderKind`` enum (kebab-case).

    Used by ``ConfigToml`` on the wire. Five canonical providers; the
    live TUI exposes more (see :class:`ApiProvider`).
    """

    DEEPSEEK = "deepseek"
    NVIDIA_NIM = "nvidia-nim"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    NOVITA = "novita"

    @classmethod
    def parse(cls, value: str) -> ProviderKind | None:
        normalized = value.strip().lower()
        match normalized:
            case "deepseek" | "deep-seek":
                return cls.DEEPSEEK
            case "nvidia" | "nvidia-nim" | "nvidia_nim" | "nim":
                return cls.NVIDIA_NIM
            case "openai" | "open-ai":
                return cls.OPENAI
            case "openrouter" | "open_router":
                return cls.OPENROUTER
            case "novita":
                return cls.NOVITA
        return None

    @property
    def canonical(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# ApiProvider (tui/config.rs:44-113) — 7 variants, superset of ProviderKind
# ---------------------------------------------------------------------------


class ApiProvider(str, Enum):
    """Mirror of Rust ``ApiProvider`` enum (snake_case on the wire).

    Includes two variants ``ProviderKind`` does not: ``DeepseekCN``
    (a mainland-China regional endpoint) and ``Fireworks`` / ``Sglang``.
    """

    DEEPSEEK = "deepseek"
    DEEPSEEK_CN = "deepseek-cn"
    NVIDIA_NIM = "nvidia-nim"
    OPENROUTER = "openrouter"
    NOVITA = "novita"
    FIREWORKS = "fireworks"
    SGLANG = "sglang"
    VOLCENGINE_ARK = "volcengine-ark"
    VOLCENGINE_ARK_ANTHROPIC = "volcengine-ark-anthropic"

    @classmethod
    def parse(cls, value: str) -> ApiProvider | None:
        normalized = value.strip().lower()
        match normalized:
            case "deepseek" | "deep-seek":
                return cls.DEEPSEEK
            case (
                "deepseek-cn"
                | "deepseek_china"
                | "deepseekcn"
                | "deepseek-china"
            ):
                return cls.DEEPSEEK_CN
            case "nvidia" | "nvidia-nim" | "nvidia_nim" | "nim":
                return cls.NVIDIA_NIM
            case "openrouter" | "open_router":
                return cls.OPENROUTER
            case "novita":
                return cls.NOVITA
            case "fireworks" | "fireworks-ai":
                return cls.FIREWORKS
            case "sglang" | "sg-lang":
                return cls.SGLANG
            case "volcengine-ark" | "volcengine_ark" | "volc-ark" | "ark":
                return cls.VOLCENGINE_ARK
            case "volcengine-ark-anthropic" | "ark-anthropic":
                return cls.VOLCENGINE_ARK_ANTHROPIC
        return None

    @property
    def display_name(self) -> str:
        return {
            ApiProvider.DEEPSEEK: "DeepSeek",
            ApiProvider.DEEPSEEK_CN: "DeepSeek (中国)",
            ApiProvider.NVIDIA_NIM: "NVIDIA NIM",
            ApiProvider.OPENROUTER: "OpenRouter",
            ApiProvider.NOVITA: "Novita AI",
            ApiProvider.FIREWORKS: "Fireworks AI",
            ApiProvider.SGLANG: "SGLang",
            ApiProvider.VOLCENGINE_ARK: "火山引擎方舟",
            ApiProvider.VOLCENGINE_ARK_ANTHROPIC: "火山引擎方舟 (Anthropic)",
        }[self]

    @classmethod
    def all(cls) -> list[ApiProvider]:
        """Picker-order list of providers (matches Rust ``ApiProvider::all``)."""
        return [
            cls.DEEPSEEK,
            cls.DEEPSEEK_CN,
            cls.NVIDIA_NIM,
            cls.OPENROUTER,
            cls.NOVITA,
            cls.FIREWORKS,
            cls.SGLANG,
            cls.VOLCENGINE_ARK,
            cls.VOLCENGINE_ARK_ANTHROPIC,
        ]


# ---------------------------------------------------------------------------
# Capability matrix data classes
# ---------------------------------------------------------------------------


class RequestPayloadMode(str, Enum):
    """Mirror of Rust ``RequestPayloadMode`` (config.rs:144-151)."""

    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES_API = "responses_api"


@dataclass(frozen=True, slots=True)
class ModelDeprecation:
    """Mirror of Rust ``ModelDeprecation`` (config.rs:153-162)."""

    alias: str
    replacement: str
    notice: str


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """Mirror of Rust ``ProviderCapability`` (config.rs:121-142)."""

    provider: ApiProvider
    resolved_model: str
    context_window: int
    max_output: int
    thinking_supported: bool
    cache_telemetry_supported: bool
    request_payload_mode: RequestPayloadMode
    deprecation: ModelDeprecation | None = None


# ---------------------------------------------------------------------------
# Deprecation registry (mirror config.rs:165-197)
# ---------------------------------------------------------------------------

_DEEPSEEK_LEGACY_NOTICE = (
    "Deprecated; will be removed in a future release. "
    "Use 'deepseek-v4-flash' instead."
)

_DEEPSEEK_LEGACY_ALIASES: tuple[ModelDeprecation, ...] = tuple(
    ModelDeprecation(alias=a, replacement="deepseek-v4-flash", notice=_DEEPSEEK_LEGACY_NOTICE)
    for a in (
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-r1",
        "deepseek-v3",
        "deepseek-v3.2",
    )
)


def deprecation_for_model(model: str) -> ModelDeprecation | None:
    """Return the deprecation record for a legacy model alias, or ``None``.

    Mirrors Rust ``deprecation_for_model`` (config.rs:204-207).
    """
    lower = model.strip().lower()
    for record in _DEEPSEEK_LEGACY_ALIASES:
        if record.alias == lower:
            return record
    return None


# ---------------------------------------------------------------------------
# Model name canonicalisation (mirror config.rs:273-310)
# ---------------------------------------------------------------------------


def canonical_model_name(model: str) -> str | None:
    """Canonicalise common model aliases to stable DeepSeek IDs.

    Returns ``None`` when the model is not a known alias. Mirrors
    Rust ``canonical_model_name`` (config.rs:273-282).
    """
    lower = model.strip().lower()
    if lower in ("deepseek-v4-pro", "deepseek-v4pro"):
        return "deepseek-v4-pro"
    if lower in ("deepseek-v4-flash", "deepseek-v4flash"):
        return "deepseek-v4-flash"
    if lower in (
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-r1",
        "deepseek-v3",
        "deepseek-v3.2",
    ):
        return "deepseek-v4-flash"
    return None


def normalize_model_name(model: str) -> str | None:
    """Normalize a configured/runtime model name.

    Accepts known aliases *plus* any valid ``deepseek*`` model ID so
    future releases work without code changes. Mirrors Rust
    ``normalize_model_name`` (config.rs:289-310).
    """
    trimmed = model.strip()
    if not trimmed:
        return None

    canonical = canonical_model_name(trimmed)
    if canonical is not None:
        return canonical

    normalized = trimmed.lower()
    if not normalized.startswith("deepseek"):
        return None

    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_.:/")
    if all(ch in allowed for ch in normalized):
        return normalized
    return None


# ---------------------------------------------------------------------------
# Context window (mirror models.rs:204-261)
# ---------------------------------------------------------------------------


_CURRENT_DEEPSEEK_V4_ALIASES = frozenset(
    {"deepseek-chat", "deepseek-reasoner", "deepseek-r1", "deepseek-v3", "deepseek-v3.2"}
)


def _deepseek_context_window_hint(model_lower: str) -> int | None:
    """Scan for a ``<n>k`` suffix and return a valid tokens count.

    Matches Rust ``deepseek_context_window_hint`` byte-by-byte
    (models.rs:232-261): only accepts 8-1024 kilo-tokens, and requires
    the number to be non-alphanumeric-bordered on both sides so embedded
    digits (like ``v4`` or model-ID versions) don't trigger.
    """
    n = len(model_lower)
    i = 0
    while i < n:
        ch = model_lower[i]
        if ch.isdigit():
            start = i
            while i < n and model_lower[i].isdigit():
                i += 1
            if i >= n or model_lower[i] != "k":
                continue
            # Boundary check: start-1 and i+1 must be non-alnum.
            before_ok = start == 0 or not model_lower[start - 1].isalnum()
            after_ok = i + 1 >= n or not model_lower[i + 1].isalnum()
            if not (before_ok and after_ok):
                continue
            try:
                kilo_tokens = int(model_lower[start:i])
            except ValueError:
                continue
            if 8 <= kilo_tokens <= 1024:
                return kilo_tokens * 1000
        else:
            i += 1
    return None


def context_window_for_model(model: str) -> int:
    """Return the context-window size in tokens for ``model``.

    Preserves the legacy Python signature (always returns an ``int``).
    Internally delegates to the Rust-parity logic in
    :func:`_context_window_for_model_optional` and falls back to
    :data:`DEFAULT_CONTEXT_WINDOW_TOKENS` when the model is unknown.
    """
    resolved = _context_window_for_model_optional(model)
    return resolved if resolved is not None else DEFAULT_CONTEXT_WINDOW_TOKENS


def _context_window_for_model_optional(model: str) -> int | None:
    """Rust-parity ``context_window_for_model`` returning ``None`` for unknown."""
    lower = model.lower()
    if "deepseek" in lower:
        hint = _deepseek_context_window_hint(lower)
        if hint is not None:
            return hint
        if "v4" in lower or lower in _CURRENT_DEEPSEEK_V4_ALIASES:
            return DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS
        return DEFAULT_CONTEXT_WINDOW_TOKENS
    if "claude" in lower:
        return 200_000
    # GPT models
    if "gpt" in lower or "o1" in lower or "o3" in lower or "o4" in lower:
        # GPT-4.1 / o3 / o4-mini support 1M context
        if any(tag in lower for tag in ("gpt-4.1", "o3", "o4")):
            return 1_000_000
        return 128_000
    # Google Gemini
    if "gemini" in lower:
        if "2.5" in lower:
            return 1_000_000
        return 1_000_000
    # Qwen
    if "qwen" in lower:
        if "long" in lower:
            return 1_000_000
        return 131_072
    return None


# ---------------------------------------------------------------------------
# Compaction thresholds (mirror models.rs:266-294)
#
# NOTE: compaction_threshold_for_model / compaction_message_threshold_for_model
# are dead code — kept for Rust parity but never called. The Python engine
# uses CompactionConfig.token_threshold / auto_floor_tokens directly, now
# driven by real provider input_tokens (see engine.capacity.should_compact).
# Safe to wire up if/when per-model adaptive thresholds are wanted.
# ---------------------------------------------------------------------------


def compaction_threshold_for_model(model: str) -> int:
    """80% of the model's context window (or :data:`DEFAULT_COMPACTION_TOKEN_THRESHOLD`)."""
    window = _context_window_for_model_optional(model)
    if window is None:
        return DEFAULT_COMPACTION_TOKEN_THRESHOLD
    return (window * _COMPACTION_THRESHOLD_PERCENT) // 100


def compaction_message_threshold_for_model(model: str) -> int:
    """Message-count threshold, scaled with context window.

    Matches Rust's intent: larger windows tolerate more messages. The
    Rust function derives this from the window; we clamp to the default
    when the window is unknown.
    """
    window = _context_window_for_model_optional(model)
    if window is None:
        return DEFAULT_COMPACTION_MESSAGE_THRESHOLD
    # Rust ``compaction_message_threshold_for_model`` (models.rs:293) uses
    # the same 80%-of-window heuristic scaled to messages; at the Python
    # level we match "V4 1M window → roughly 10× default, otherwise
    # default" to keep behaviour stable without exposing model-specific
    # knobs that Rust keeps private.
    if window >= DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS:
        return DEFAULT_COMPACTION_MESSAGE_THRESHOLD * 10
    return DEFAULT_COMPACTION_MESSAGE_THRESHOLD


# ---------------------------------------------------------------------------
# ProviderCapability resolution (mirror config.rs:209-266)
# ---------------------------------------------------------------------------


def provider_capability(
    provider: ApiProvider, resolved_model: str
) -> ProviderCapability:
    """Compute the static capability record for a provider + model pair.

    Mirrors Rust ``provider_capability`` (config.rs:215-266). All fields
    are derived from release docs / API guides, never from live probing.
    """
    model_lower = resolved_model.lower()
    is_v4_pro = "v4-pro" in model_lower or model_lower == "deepseek-v4pro"
    is_v4_flash = (
        "v4-flash" in model_lower
        or model_lower == "deepseek-v4flash"
        or model_lower == "deepseek-v4"
    )

    # Context window: V4 → 1M; otherwise fall through to the model lookup.
    if is_v4_pro or is_v4_flash:
        window = DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS
    else:
        probed = _context_window_for_model_optional(resolved_model)
        window = probed if probed is not None else DEFAULT_CONTEXT_WINDOW_TOKENS

    max_output = max_output_tokens_for_model(resolved_model)

    # thinking_supported: DeepSeek v4 + OpenAI reasoning models + Claude
    # thinking models. This flag gates whether reasoning_effort / thinking
    # fields are sent in the request payload.
    thinking_supported = is_v4_pro or is_v4_flash
    if not thinking_supported:
        thinking_supported = any(
            tag in model_lower
            for tag in ("o1", "o3", "o4", "-thinking", "reasoner")
        )

    cache_telemetry_supported = provider in (
        ApiProvider.DEEPSEEK,
        ApiProvider.DEEPSEEK_CN,
        ApiProvider.NVIDIA_NIM,
    )

    return ProviderCapability(
        provider=provider,
        resolved_model=resolved_model,
        context_window=window,
        max_output=max_output,
        thinking_supported=thinking_supported,
        cache_telemetry_supported=cache_telemetry_supported,
        request_payload_mode=RequestPayloadMode.CHAT_COMPLETIONS,
        deprecation=deprecation_for_model(resolved_model),
    )


def max_output_tokens_for_model(model: str) -> int:
    """Return the default per-request output limit for a model."""
    model_lower = model.lower()
    is_v4_pro = "v4-pro" in model_lower or model_lower == "deepseek-v4pro"
    is_v4_flash = (
        "v4-flash" in model_lower
        or model_lower == "deepseek-v4flash"
        or model_lower == "deepseek-v4"
    )
    return 262_144 if (is_v4_pro or is_v4_flash) else 4096


# ---------------------------------------------------------------------------
# Backwards-compatible legacy API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderDefaults:
    """Default base URL + default model for a provider."""

    base_url: str
    model: str
    flash_model: str | None = None
    protocol: str = "openai"


# Defaults table — model strings match the Rust ``DEFAULT_*_MODEL`` constants.
PROVIDER_DEFAULTS: dict[str, ProviderDefaults] = {
    "deepseek": ProviderDefaults(
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        flash_model="deepseek-v4-flash",
    ),
    "openai": ProviderDefaults(
        base_url="https://api.openai.com/v1",
        model="gpt-4.1",
    ),
    "nvidia-nim": ProviderDefaults(
        base_url="https://integrate.api.nvidia.com/v1",
        model="deepseek-ai/deepseek-v4-pro",
        flash_model="deepseek-ai/deepseek-v4-flash",
    ),
    "openrouter": ProviderDefaults(
        base_url="https://openrouter.ai/api/v1",
        model="deepseek/deepseek-v4-pro",
        flash_model="deepseek/deepseek-v4-flash",
    ),
    "novita": ProviderDefaults(
        base_url="https://api.novita.ai/v1",
        model="deepseek/deepseek-v4-pro",
        flash_model="deepseek/deepseek-v4-flash",
    ),
    "fireworks": ProviderDefaults(
        base_url="https://api.fireworks.ai/inference/v1",
        model="accounts/fireworks/models/deepseek-v4-pro",
    ),
    "sglang": ProviderDefaults(
        base_url="http://localhost:30000/v1",
        model="deepseek-ai/DeepSeek-V4-Pro",
    ),
    "volcengine-ark": ProviderDefaults(
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        model="GLM-5.2",
    ),
    "volcengine-ark-anthropic": ProviderDefaults(
        base_url="https://ark.cn-beijing.volces.com/api/coding",
        model="GLM-5.2",
        protocol="anthropic",
    ),
}


# Legacy alias map — same data surface the old module exposed. Kept as a
# public dict because engine / client code may look it up directly.
MODEL_ALIASES: dict[str, str] = {
    record.alias: record.replacement for record in _DEEPSEEK_LEGACY_ALIASES
}
# Also populate canonical self-aliases so legacy callers that feed in
# ``deepseek-v4pro`` still get back a normalized name.
MODEL_ALIASES.setdefault("deepseek-v4pro", "deepseek-v4-pro")
MODEL_ALIASES.setdefault("deepseek-v4flash", "deepseek-v4-flash")


def normalize_model(model: str) -> str:
    """Legacy shim. Returns the canonical model name if known, else ``model``."""
    canonical = canonical_model_name(model)
    return canonical if canonical is not None else model
