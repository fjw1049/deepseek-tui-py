"""Per-turn LLM usage ledger — accumulates every metered model call."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Iterator

from deepseek_tui.protocol.responses import Usage

_usage_source: ContextVar[str | None] = ContextVar("usage_source", default=None)


@contextmanager
def usage_source(source: str) -> Iterator[None]:
    token: Token[str | None] = _usage_source.set(source)
    try:
        yield
    finally:
        _usage_source.reset(token)


def current_usage_source() -> str:
    return _usage_source.get() or "unknown"


@dataclass(slots=True)
class UsageLineItem:
    model: str
    source: str
    usage: Usage
    round_idx: int | None = None


@dataclass
class TurnUsageLedger:
    items: list[UsageLineItem] = field(default_factory=list)

    def reset(self) -> None:
        self.items.clear()

    def add(
        self,
        *,
        model: str,
        source: str,
        usage: Usage | None,
        round_idx: int | None = None,
    ) -> None:
        if usage is None:
            return
        if usage.input_tokens <= 0 and usage.output_tokens <= 0:
            return
        self.items.append(
            UsageLineItem(
                model=model.strip() or "unknown",
                source=source,
                usage=usage,
                round_idx=round_idx,
            )
        )

    def record_metered(self, *, model: str, usage: Usage | None) -> None:
        self.add(model=model, source=current_usage_source(), usage=usage)

    def combined_usage(self) -> Usage | None:
        if not self.items:
            return None
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        cache_creation = 0
        reasoning = 0
        for item in self.items:
            u = item.usage
            input_tokens += u.input_tokens
            output_tokens += u.output_tokens
            cache_read += u.cache_read_input_tokens
            cache_creation += u.cache_creation_input_tokens
            reasoning += u.reasoning_tokens
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_creation,
            reasoning_tokens=reasoning,
        )

    def totals(self) -> dict[str, Any]:
        from deepseek_tui.client.pricing import calculate_turn_cost_estimate_from_usage

        input_tokens = 0
        output_tokens = 0
        cache_hit_tokens = 0
        cache_miss_tokens = 0
        cost_usd = 0.0
        cost_cny = 0.0
        has_cost = False
        models: dict[str, dict[str, Any]] = {}
        sources: dict[str, int] = {}

        for item in self.items:
            u = item.usage
            input_tokens += u.input_tokens
            output_tokens += u.output_tokens
            cache_hit_tokens += u.cache_read_input_tokens
            cache_miss_tokens += u.cache_creation_input_tokens
            sources[item.source] = sources.get(item.source, 0) + 1

            model_bucket = models.setdefault(
                item.model,
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_hit_tokens": 0,
                    "cache_miss_tokens": 0,
                    "cost_usd": 0.0,
                    "cost_cny": 0.0,
                },
            )
            model_bucket["input_tokens"] += u.input_tokens
            model_bucket["output_tokens"] += u.output_tokens
            model_bucket["cache_hit_tokens"] += u.cache_read_input_tokens
            model_bucket["cache_miss_tokens"] += u.cache_creation_input_tokens

            estimate = calculate_turn_cost_estimate_from_usage(item.model, u)
            if estimate is not None and estimate.is_positive:
                has_cost = True
                cost_usd += estimate.usd
                cost_cny += estimate.cny
                model_bucket["cost_usd"] += estimate.usd
                model_bucket["cost_cny"] += estimate.cny

        cache_total = cache_hit_tokens + cache_miss_tokens
        record: dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cache_hit_tokens": cache_hit_tokens,
            "cache_miss_tokens": cache_miss_tokens,
            "turns": len(self.items),
            "token_economy_savings_tokens": 0,
            "models": models,
            "sources": sources,
        }
        if has_cost:
            record["cost_usd"] = cost_usd
            record["cost_cny"] = cost_cny
        if cache_total > 0:
            record["cache_hit_rate"] = cache_hit_tokens / cache_total
        return record
