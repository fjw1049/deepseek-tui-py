"""Per-model cost estimation.

DeepSeek's published rates have **three** input tiers (cache hit / cache miss
/ output) and ship in two currencies (USD + CNY). The v4 Pro model is on a
limited-time 75% discount that auto-expires ``2026-05-31 15:59 UTC``; this
module honors that cutover so the cost chip flips to base rates the second
the discount lapses.

Cost source-of-truth for the TUI footer comes from
:func:`calculate_turn_cost_estimate_from_usage`, which respects the
``prompt_cache_hit_tokens`` / ``prompt_cache_miss_tokens`` fields DeepSeek
returns alongside ``prompt_tokens`` (already plumbed through
:class:`deepseek_tui.protocol.responses.Usage`).
"""

from __future__ import annotations


from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from deepseek_tui.protocol.responses import Usage


class CostCurrency(str, Enum):
    """Cost display currency.

    Accepts both short codes (``usd`` / ``cny``) and common aliases
    (``yuan`` / ``rmb`` / ``$`` / ``¥``) via :meth:`from_setting`.
    """

    USD = "usd"
    CNY = "cny"

    @classmethod
    def from_setting(cls, value: str) -> CostCurrency | None:
        normalised = value.strip().lower()
        if normalised in ("usd", "dollar", "dollars", "$"):
            return cls.USD
        if normalised in ("cny", "rmb", "yuan", "¥"):
            return cls.CNY
        return None

    @property
    def symbol(self) -> str:
        return "$" if self is CostCurrency.USD else "¥"


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Cost estimate in both official DeepSeek pricing currencies.

    Carry both so the UI can switch currency without re-pricing the turn.
    """

    usd: float = 0.0
    cny: float = 0.0

    @property
    def is_positive(self) -> bool:
        return self.usd > 0.0 or self.cny > 0.0

    def amount(self, currency: CostCurrency) -> float:
        return self.usd if currency is CostCurrency.USD else self.cny

    def __add__(self, other: CostEstimate) -> CostEstimate:
        return CostEstimate(usd=self.usd + other.usd, cny=self.cny + other.cny)


@dataclass(frozen=True, slots=True)
class _CurrencyPricing:
    """Per-million-token rates in one currency.

    Three tiers match DeepSeek's billing surface: hits against the
    context cache are ~100× cheaper than misses, which is why the
    footer's ``cache N%`` chip is load-bearing UX.
    """

    input_cache_hit_per_million: float
    input_cache_miss_per_million: float
    output_per_million: float


@dataclass(frozen=True, slots=True)
class _ModelPricing:
    usd: _CurrencyPricing
    cny: _CurrencyPricing


# DeepSeek's v4 Pro limited-time 75% discount runs through this UTC instant.
_V4_PRO_DISCOUNT_ENDS_AT = datetime(2026, 5, 31, 15, 59, 0, tzinfo=timezone.utc)


_V4_PRO_DISCOUNTED = _ModelPricing(
    usd=_CurrencyPricing(
        input_cache_hit_per_million=0.003625,
        input_cache_miss_per_million=0.435,
        output_per_million=0.87,
    ),
    cny=_CurrencyPricing(
        input_cache_hit_per_million=0.025,
        input_cache_miss_per_million=3.0,
        output_per_million=6.0,
    ),
)

_V4_PRO_BASE = _ModelPricing(
    usd=_CurrencyPricing(
        input_cache_hit_per_million=0.0145,
        input_cache_miss_per_million=1.74,
        output_per_million=3.48,
    ),
    cny=_CurrencyPricing(
        input_cache_hit_per_million=0.1,
        input_cache_miss_per_million=12.0,
        output_per_million=24.0,
    ),
)

_V4_FLASH = _ModelPricing(
    usd=_CurrencyPricing(
        input_cache_hit_per_million=0.0028,
        input_cache_miss_per_million=0.14,
        output_per_million=0.28,
    ),
    cny=_CurrencyPricing(
        input_cache_hit_per_million=0.02,
        input_cache_miss_per_million=1.0,
        output_per_million=2.0,
    ),
)


def _pricing_for_model_at(model: str, now: datetime) -> _ModelPricing | None:
    """Return per-million pricing for ``model`` at instant ``now``.

    Returns ``None`` for unknown or non-DeepSeek-Platform models so the
    UI can hide the cost chip rather than report a misleading zero.
    """
    lower = model.lower()
    if lower.startswith("deepseek-ai/"):
        # NVIDIA NIM-hosted DeepSeek uses NIM's catalog/account terms,
        # not DeepSeek Platform pricing. Showing DeepSeek $ here would
        # lie to the user — hide instead.
        return None
    if "deepseek" not in lower:
        return None
    if "v4-pro" in lower or "v4pro" in lower:
        return _V4_PRO_DISCOUNTED if now <= _V4_PRO_DISCOUNT_ENDS_AT else _V4_PRO_BASE
    # Everything else under the DeepSeek brand follows the v4-flash
    # rate card (covers ``deepseek-chat`` / ``deepseek-reasoner``
    # legacy aliases as well, which DeepSeek bills at v4-flash rates).
    return _V4_FLASH


def calculate_turn_cost_estimate_from_usage(
    model: str, usage: Usage, *, now: datetime | None = None
) -> CostEstimate | None:
    """Cost for one turn, honoring DeepSeek's three-tier billing.

    ``now`` is exposed for tests so the v4-pro discount cutover is
    deterministic.
    """
    pricing = _pricing_for_model_at(model, now or datetime.now(timezone.utc))
    if pricing is None:
        return None
    return CostEstimate(
        usd=_estimate_in_currency(pricing.usd, usage),
        cny=_estimate_in_currency(pricing.cny, usage),
    )


def _estimate_in_currency(rates: _CurrencyPricing, usage: Usage) -> float:
    """Apply the three-tier rate table to a single Usage payload."""
    hit_tokens = usage.cache_read_input_tokens
    miss_tokens = usage.cache_creation_input_tokens
    accounted = hit_tokens + miss_tokens
    # Defensive: when only `prompt_tokens` is reported (older payloads
    # or off-API providers), bill the unaccounted remainder at miss
    # rates so we never silently undercount.
    uncategorised = max(0, usage.input_tokens - accounted)
    hit_cost = hit_tokens / 1_000_000 * rates.input_cache_hit_per_million
    miss_cost = (miss_tokens + uncategorised) / 1_000_000 * rates.input_cache_miss_per_million
    out_cost = usage.output_tokens / 1_000_000 * rates.output_per_million
    return hit_cost + miss_cost + out_cost


def format_cost_amount(cost: float, currency: CostCurrency = CostCurrency.USD) -> str:
    """Compact formatter for the footer cost chip.

    - ``< 0.0001`` → ``<$0.0001`` (just signals "non-zero")
    - ``0.0001 .. 0.01`` → 4-digit precision (``$0.0034``)
    - ``>= 0.01`` → 2-digit precision (``$0.42``)
    """
    symbol = currency.symbol
    if cost < 0.0001:
        return f"<{symbol}0.0001"
    if cost < 0.01:
        return f"{symbol}{cost:.4f}"
    return f"{symbol}{cost:.2f}"


def format_cost_estimate(
    estimate: CostEstimate, currency: CostCurrency = CostCurrency.USD
) -> str:
    """Convenience over :func:`format_cost_amount` for a dual-currency estimate."""
    return format_cost_amount(estimate.amount(currency), currency)


# ---- Backwards-compat shim ------------------------------------------------
#
# The original Python port exposed a class-y ``ModelPricing`` + ``PricingTable``
# pair that nothing in-tree actually wired up. Re-export thin equivalents so
# any out-of-tree caller (tests, scripts) that imported them keeps working
# while the new function-driven API drives production.


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Legacy flat 2-tier rate card.

    Pre-2026-05-12 code used this 2-tier shape
    (one input rate, one output rate). The real DeepSeek surface is
    3-tier; the canonical entry point is
    :func:`calculate_turn_cost_estimate_from_usage`. Kept here only so
    consumers that imported ``ModelPricing`` don't break.
    """

    input_per_million: float
    output_per_million: float
    cache_write_per_million: float = 0.0
    cache_read_per_million: float = 0.0

    def estimate_cost(self, usage: Usage) -> float:
        return (
            usage.input_tokens / 1_000_000 * self.input_per_million
            + usage.output_tokens / 1_000_000 * self.output_per_million
            + usage.cache_creation_input_tokens / 1_000_000 * self.cache_write_per_million
            + usage.cache_read_input_tokens / 1_000_000 * self.cache_read_per_million
        )


class PricingTable:
    """Legacy shim — prefer :func:`calculate_turn_cost_estimate_from_usage`."""

    def __init__(self) -> None:
        # Approximate published USD rates so legacy callers reading this
        # table still get a plausible number. Real pricing decisions go
        # through ``calculate_turn_cost_estimate_from_usage``.
        self._pricing: dict[str, ModelPricing] = {
            "deepseek-chat": ModelPricing(
                input_per_million=0.14,
                output_per_million=0.28,
                cache_read_per_million=0.0028,
            ),
            "deepseek-reasoner": ModelPricing(
                input_per_million=0.55,
                output_per_million=2.19,
                cache_read_per_million=0.014,
            ),
        }

    def get(self, model_name: str) -> ModelPricing | None:
        return self._pricing.get(model_name)
