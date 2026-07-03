"""Turn/thread usage aggregation (token + cost buckets).

Builds usage records from engine results and aggregates per-thread and
per-model buckets for the HTTP API responses.
"""

from __future__ import annotations

from typing import Any

from deepseek_tui.engine.events import TurnCompleteEvent
from deepseek_tui.server.threads.models import TurnRecord

def build_turn_usage_record(*, usage: Any, model: str) -> dict[str, Any]:
    """Persist a per-turn usage delta on ``TurnRecord.usage``."""
    from deepseek_tui.client.pricing import calculate_turn_cost_estimate_from_usage
    from deepseek_tui.protocol.responses import Usage

    u = usage if isinstance(usage, Usage) else Usage.model_validate(usage)
    input_tokens = max(0, int(u.input_tokens))
    output_tokens = max(0, int(u.output_tokens))
    record: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cache_hit_tokens": max(0, int(u.cache_read_input_tokens)),
        "cache_miss_tokens": max(0, int(u.cache_creation_input_tokens)),
        "turns": 1,
        "token_economy_savings_tokens": 0,
    }
    estimate = calculate_turn_cost_estimate_from_usage(model, u)
    if estimate is not None and estimate.is_positive:
        record["cost_usd"] = estimate.usd
        record["cost_cny"] = estimate.cny
    model_id = model.strip() or "unknown"
    record["models"] = {
        model_id: {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_hit_tokens": record["cache_hit_tokens"],
            "cache_miss_tokens": record["cache_miss_tokens"],
            "cost_usd": float(record.get("cost_usd", 0.0) or 0.0),
            "cost_cny": float(record.get("cost_cny", 0.0) or 0.0),
            "turns": 1,
        }
    }
    return record


def turn_usage_from_engine_or_event(
    *,
    engine: Any | None,
    event: TurnCompleteEvent | None,
    model: str,
) -> dict[str, Any] | None:
    ledger = getattr(engine, "turn_usage_ledger", None) if engine is not None else None
    if ledger is not None and ledger.items:
        return ledger.totals()
    if event is not None and event.usage is not None:
        return build_turn_usage_record(usage=event.usage, model=model)
    return None


def _usage_counter_value(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return 0


def _usage_counter_float(usage: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)
    return 0.0


def _empty_thread_usage_bucket(thread_id: str) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cache_miss_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_cny": 0.0,
        "cache_savings_usd": 0.0,
        "cache_savings_cny": 0.0,
        "token_economy_savings_tokens": 0,
        "token_economy_savings_usd": 0.0,
        "token_economy_savings_cny": 0.0,
        "turns": 0,
        "cache_hit_rate": None,
    }


def _turn_usage_has_cache_telemetry(usage: dict[str, Any]) -> bool:
    return any(key in usage for key in ("cache_hit_tokens", "cache_miss_tokens"))


def _add_turn_usage_to_bucket(
    bucket: dict[str, Any],
    usage: dict[str, Any],
) -> bool:
    bucket["input_tokens"] += _usage_counter_value(
        usage, "input_tokens", "prompt_tokens"
    )
    bucket["output_tokens"] += _usage_counter_value(
        usage, "output_tokens", "completion_tokens"
    )
    hit = _usage_counter_value(usage, "cache_hit_tokens")
    miss = _usage_counter_value(usage, "cache_miss_tokens")
    has_cache = _turn_usage_has_cache_telemetry(usage)
    if has_cache:
        bucket["cached_tokens"] += hit
        bucket["cache_miss_tokens"] += miss
    bucket["total_tokens"] += _usage_counter_value(usage, "total_tokens")
    if bucket["total_tokens"] <= 0:
        bucket["total_tokens"] = bucket["input_tokens"] + bucket["output_tokens"]
    bucket["cost_usd"] += _usage_counter_float(usage, "cost_usd")
    bucket["cost_cny"] += _usage_counter_float(usage, "cost_cny")
    bucket["token_economy_savings_tokens"] += _usage_counter_value(
        usage, "token_economy_savings_tokens"
    )
    bucket["turns"] += max(1, _usage_counter_value(usage, "turns"))
    return has_cache


def aggregate_thread_usage_bucket(
    thread_id: str,
    turns: list[TurnRecord],
    *,
    live_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bucket = _empty_thread_usage_bucket(thread_id)
    has_cache_telemetry = False
    for turn in turns:
        usage = turn.usage
        if not isinstance(usage, dict) or not usage:
            continue
        has_cache_telemetry = (
            _add_turn_usage_to_bucket(bucket, usage) or has_cache_telemetry
        )
    if isinstance(live_usage, dict) and live_usage:
        has_cache_telemetry = (
            _add_turn_usage_to_bucket(bucket, live_usage) or has_cache_telemetry
        )
    cache_total = bucket["cached_tokens"] + bucket["cache_miss_tokens"]
    bucket["cache_hit_rate"] = (
        bucket["cached_tokens"] / cache_total
        if has_cache_telemetry and cache_total > 0
        else None
    )
    return bucket


def thread_usage_bucket_has_data(bucket: dict[str, Any]) -> bool:
    return (
        bucket["total_tokens"] > 0
        or bucket["cached_tokens"] > 0
        or bucket["cache_miss_tokens"] > 0
        or bucket["cost_usd"] > 0
        or bucket["cost_cny"] > 0
        or bucket["token_economy_savings_tokens"] > 0
        or bucket["turns"] > 0
    )


def _empty_model_usage_bucket(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_cny": 0.0,
        "turns": 0,
    }


def _merge_model_usage_bucket(
    session: dict[str, dict[str, Any]],
    model_id: str,
    bucket: dict[str, Any],
) -> None:
    normalized = (model_id or "unknown").strip() or "unknown"
    target = session.setdefault(normalized, _empty_model_usage_bucket(normalized))
    input_tokens = _usage_counter_value(bucket, "input_tokens", "prompt_tokens")
    output_tokens = _usage_counter_value(
        bucket, "output_tokens", "completion_tokens"
    )
    target["input_tokens"] += input_tokens
    target["output_tokens"] += output_tokens
    target["total_tokens"] += _usage_counter_value(bucket, "total_tokens")
    if target["total_tokens"] <= 0:
        target["total_tokens"] = target["input_tokens"] + target["output_tokens"]
    target["cost_usd"] += _usage_counter_float(bucket, "cost_usd")
    target["cost_cny"] += _usage_counter_float(bucket, "cost_cny")
    target["turns"] += max(1, _usage_counter_value(bucket, "turns"))


def accumulate_model_usage_from_turn(
    session: dict[str, dict[str, Any]],
    turn_usage: dict[str, Any] | None,
    *,
    fallback_model: str,
) -> None:
    if not isinstance(turn_usage, dict) or not turn_usage:
        return
    models = turn_usage.get("models")
    if isinstance(models, dict) and models:
        for model_id, bucket in models.items():
            if isinstance(bucket, dict):
                _merge_model_usage_bucket(session, str(model_id), bucket)
        return
    fallback = (fallback_model or "unknown").strip() or "unknown"
    _merge_model_usage_bucket(session, fallback, turn_usage)


def session_model_usage_response(
    session: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    buckets = sorted(
        session.values(),
        key=lambda item: (
            -int(item.get("total_tokens", 0) or 0),
            str(item.get("model", "")),
        ),
    )
    totals = _empty_model_usage_bucket("total")
    totals.pop("model", None)
    for bucket in buckets:
        totals["input_tokens"] += int(bucket.get("input_tokens", 0) or 0)
        totals["output_tokens"] += int(bucket.get("output_tokens", 0) or 0)
        totals["total_tokens"] += int(bucket.get("total_tokens", 0) or 0)
        totals["cost_usd"] += float(bucket.get("cost_usd", 0.0) or 0.0)
        totals["cost_cny"] += float(bucket.get("cost_cny", 0.0) or 0.0)
        totals["turns"] += int(bucket.get("turns", 0) or 0)
    if not buckets:
        return {
            "group_by": "model",
            "scope": "session",
            "buckets": [],
            "totals": totals,
        }
    return {
        "group_by": "model",
        "scope": "session",
        "buckets": buckets,
        "totals": totals,
    }


def thread_usage_response(
    thread_id: str,
    turns: list[TurnRecord],
    *,
    live_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bucket = aggregate_thread_usage_bucket(
        thread_id, turns, live_usage=live_usage
    )
    if not thread_usage_bucket_has_data(bucket):
        return {
            "group_by": "thread",
            "buckets": [],
            "totals": {**bucket, "thread_count": 0},
        }
    totals = {**bucket, "thread_count": 1}
    return {
        "group_by": "thread",
        "buckets": [bucket],
        "totals": totals,
    }
