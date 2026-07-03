"""Provider catalogue + model/context-window resolution."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS",
    "DEFAULT_CONTEXT_WINDOW_TOKENS",
    "PROVIDER_DEFAULTS",
    "ProviderDefaults",
    "canonical_model_name",
    "context_window_for_model",
    "context_window_override",
    "max_output_tokens_for_model",
    "normalize_model",
    "register_provider_context_windows",
    "set_context_window_override",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEEPSEEK_V4_CONTEXT_WINDOW_TOKENS = 1_000_000
# Default window for custom provider models the static table below doesn't
# recognize (e.g. ``[providers.hs] model = "glm-5.2"``). Overridable per
# provider via ``[providers.X] context_window = ...``.
CUSTOM_MODEL_CONTEXT_WINDOW_TOKENS = 500_000


# ---------------------------------------------------------------------------
# Model name canonicalisation
# ---------------------------------------------------------------------------


def canonical_model_name(model: str) -> str | None:
    """Canonicalise common model aliases to stable DeepSeek IDs.

    Returns ``None`` when the model is not a known alias.
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


# ---------------------------------------------------------------------------
# Context window
# ---------------------------------------------------------------------------


_CURRENT_DEEPSEEK_V4_ALIASES = frozenset(
    {"deepseek-chat", "deepseek-reasoner", "deepseek-r1", "deepseek-v3", "deepseek-v3.2"}
)


def _deepseek_context_window_hint(model_lower: str) -> int | None:
    """Scan for a ``<n>k`` suffix and return a valid tokens count.

    Only accepts 8-1024 kilo-tokens, and requires
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


# Config-driven per-model context windows. Populated from
# ``[providers.X]`` tables at config load / engine creation so custom
# provider models (unknown to the static table below) get a usable window.
_context_window_overrides: dict[str, int] = {}


def set_context_window_override(model: str, window: int) -> None:
    """Pin ``model``'s context window (tokens). No-op for invalid input."""
    key = model.strip().lower()
    if key and window > 0:
        _context_window_overrides[key] = window


def context_window_override(model: str) -> int | None:
    return _context_window_overrides.get(model.strip().lower())


def register_provider_context_windows(config: object) -> None:
    """Register context windows for every ``[providers.X]`` model in ``config``.

    - ``[providers.X.context_windows]`` (model id → tokens, written by the
      Workbench custom-endpoint UI) wins for the models it names.
    - ``context_window`` on the provider table applies to its default model.
    - A custom model the static table doesn't recognize defaults to
      :data:`CUSTOM_MODEL_CONTEXT_WINDOW_TOKENS` (500K).
    Idempotent; safe to call on every config load / engine creation.
    """
    providers = getattr(config, "providers", None) or {}
    for entry in providers.values():
        per_model = getattr(entry, "context_windows", None) or {}
        for model_id, window in per_model.items():
            if isinstance(window, int) and window > 0:
                set_context_window_override(str(model_id), window)
        model = (getattr(entry, "model", None) or "").strip()
        if not model or model in per_model:
            continue
        window = getattr(entry, "context_window", None)
        if isinstance(window, int) and window > 0:
            set_context_window_override(model, window)
        elif (
            context_window_override(model) is None
            and _context_window_for_model_optional(model) is None
        ):
            set_context_window_override(model, CUSTOM_MODEL_CONTEXT_WINDOW_TOKENS)


def context_window_for_model(model: str) -> int:
    """Return the context-window size in tokens for ``model``.

    Preserves the legacy Python signature (always returns an ``int``).
    Config-registered overrides (``[providers.X] context_window`` / custom
    model default) win; otherwise delegates to the logic in
    :func:`_context_window_for_model_optional` and falls back to
    :data:`DEFAULT_CONTEXT_WINDOW_TOKENS` when the model is unknown.
    """
    override = context_window_override(model)
    if override is not None:
        return override
    resolved = _context_window_for_model_optional(model)
    return resolved if resolved is not None else DEFAULT_CONTEXT_WINDOW_TOKENS


def _context_window_for_model_optional(model: str) -> int | None:
    """``context_window_for_model`` returning ``None`` for unknown."""
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
        return 1_000_000
    # Qwen
    if "qwen" in lower:
        if "long" in lower:
            return 1_000_000
        return 131_072
    return None


def max_output_tokens_for_model(model: str) -> int:
    """Return the default per-request output limit for a model."""
    model_lower = model.lower()
    is_v4_pro = "v4-pro" in model_lower or model_lower == "deepseek-v4pro"
    is_v4_flash = (
        "v4-flash" in model_lower
        or model_lower == "deepseek-v4flash"
        or model_lower == "deepseek-v4"
    )
    if is_v4_pro or is_v4_flash:
        return 262_144
    # GLM (e.g. GLM-5.2) streams large reasoning_content. The legacy 4096 cap
    # is exhausted by reasoning alone, so the round is length-truncated before
    # any answer `content` is produced — the engine then falls back to dumping
    # raw (truncated) reasoning as the final answer. Give it room to finish
    # thinking *and* emit the answer. context_input_budget clamps the output
    # reservation to window//4, so a larger cap never starves the input budget.
    if "glm" in model_lower:
        return 32_768
    return 4096


# ---------------------------------------------------------------------------
# Provider defaults
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderDefaults:
    """Default base URL + default model for a provider."""

    base_url: str
    model: str
    flash_model: str | None = None
    protocol: str = "openai"


# Defaults table.
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


def normalize_model(model: str) -> str:
    """Legacy shim. Returns the canonical model name if known, else ``model``."""
    canonical = canonical_model_name(model)
    return canonical if canonical is not None else model
