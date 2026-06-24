"""Persistent Workbench model usage ledger (user-level, 90-day retention)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.config.paths import workbench_usage_ledger_path

LEDGER_SCHEMA_VERSION = 1
RETENTION_DAYS = 90
BUILTIN_DEEPSEEK_PROVIDER_ID = "deepseek"
MODEL_REF_SEPARATOR = "::"


def _usage_number(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return 0


def _usage_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _empty_bucket(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_cny": 0.0,
        "turns": 0,
    }


def _decode_model_ref(value: str) -> tuple[str, str]:
    trimmed = value.strip()
    separator_index = trimmed.find(MODEL_REF_SEPARATOR)
    if separator_index <= 0:
        return BUILTIN_DEEPSEEK_PROVIDER_ID, trimmed
    return trimmed[:separator_index], trimmed[separator_index + len(MODEL_REF_SEPARATOR) :]


def _local_day_key(value: datetime) -> str:
    local = value.astimezone()
    return local.strftime("%Y-%m-%d")


def _empty_ledger() -> dict[str, Any]:
    return {
        "schemaVersion": LEDGER_SCHEMA_VERSION,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "retentionDays": RETENTION_DAYS,
        "processedTurnIds": {},
        "days": {},
        "lifetime": {"models": {}},
    }


def _read_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_ledger()
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return _empty_ledger()
    if not isinstance(parsed, dict):
        return _empty_ledger()
    if parsed.get("schemaVersion") != LEDGER_SCHEMA_VERSION:
        return _empty_ledger()
    if not isinstance(parsed.get("days"), dict):
        parsed["days"] = {}
    if not isinstance(parsed.get("processedTurnIds"), dict):
        parsed["processedTurnIds"] = {}
    lifetime = parsed.get("lifetime")
    if not isinstance(lifetime, dict):
        parsed["lifetime"] = {"models": {}}
    elif not isinstance(lifetime.get("models"), dict):
        lifetime["models"] = {}
    parsed["retentionDays"] = RETENTION_DAYS
    return parsed


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["schemaVersion"] = LEDGER_SCHEMA_VERSION
    ledger["updatedAt"] = datetime.now(timezone.utc).isoformat()
    ledger["retentionDays"] = RETENTION_DAYS
    payload = json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True)
    fd, temp_name = tempfile.mkstemp(prefix="ledger-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _merge_bucket(target: dict[str, Any], source: dict[str, Any]) -> None:
    input_tokens = _usage_number(source.get("input_tokens", source.get("prompt_tokens")))
    output_tokens = _usage_number(source.get("output_tokens", source.get("completion_tokens")))
    total_tokens = _usage_number(source.get("total_tokens"))
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    target["input_tokens"] += input_tokens
    target["output_tokens"] += output_tokens
    target["total_tokens"] += total_tokens
    target["cost_usd"] += _usage_float(source.get("cost_usd"))
    target["cost_cny"] += _usage_float(source.get("cost_cny"))
    target["turns"] += max(1, _usage_number(source.get("turns")))


def _merge_turn_usage_models(
    session: dict[str, dict[str, Any]],
    turn_usage: dict[str, Any],
    *,
    fallback_model: str,
) -> None:
    models = turn_usage.get("models")
    if isinstance(models, dict) and models:
        for model_id, bucket in models.items():
            if isinstance(bucket, dict):
                target = session.setdefault(str(model_id), _empty_bucket(str(model_id)))
                _merge_bucket(target, bucket)
        return
    fallback = (fallback_model or "unknown").strip() or "unknown"
    target = session.setdefault(fallback, _empty_bucket(fallback))
    _merge_bucket(target, turn_usage)


def _merge_turn_into_ledger(
    ledger: dict[str, Any],
    *,
    day: str,
    turn_usage: dict[str, Any],
    fallback_model: str,
) -> None:
    day_bucket = ledger["days"].setdefault(day, {"models": {}, "totals": _empty_bucket("total")})
    models = day_bucket.setdefault("models", {})
    lifetime_models = ledger["lifetime"].setdefault("models", {})
    session: dict[str, dict[str, Any]] = {}

    _merge_turn_usage_models(session, turn_usage, fallback_model=fallback_model)
    for model_ref, bucket in session.items():
        day_model = models.setdefault(model_ref, _empty_bucket(model_ref))
        _merge_bucket(day_model, bucket)
        lifetime_model = lifetime_models.setdefault(model_ref, _empty_bucket(model_ref))
        _merge_bucket(lifetime_model, bucket)

    totals = day_bucket.setdefault("totals", _empty_bucket("total"))
    totals.pop("model", None)
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_cny": 0.0,
        "turns": 0,
    }
    for bucket in models.values():
        _merge_bucket(totals, bucket)
    day_bucket["totals"] = totals


def _prune_old_days(ledger: dict[str, Any]) -> None:
    cutoff = datetime.now().astimezone().date() - timedelta(days=RETENTION_DAYS - 1)
    days = ledger.get("days")
    if not isinstance(days, dict):
        return
    stale_days = [day for day in days if day < cutoff.isoformat()]
    for day in stale_days:
        days.pop(day, None)
    processed = ledger.get("processedTurnIds")
    if not isinstance(processed, dict):
        ledger["processedTurnIds"] = {}
        return
    for turn_id, recorded_day in list(processed.items()):
        if not isinstance(recorded_day, str) or recorded_day < cutoff.isoformat():
            processed.pop(turn_id, None)


def record_turn_usage(
    *,
    turn_id: str,
    ended_at: datetime,
    thread_id: str,
    turn_usage: dict[str, Any] | None,
    fallback_model: str,
) -> None:
    normalized_turn_id = turn_id.strip()
    if not normalized_turn_id or not isinstance(turn_usage, dict) or not turn_usage:
        return
    path = workbench_usage_ledger_path()
    ledger = _read_ledger(path)
    processed = ledger.setdefault("processedTurnIds", {})
    if normalized_turn_id in processed:
        return
    day = _local_day_key(ended_at)
    _merge_turn_into_ledger(
        ledger,
        day=day,
        turn_usage=turn_usage,
        fallback_model=fallback_model,
    )
    processed[normalized_turn_id] = day
    _prune_old_days(ledger)
    _write_ledger(path, ledger)


def prune_usage_provider(provider_id: str) -> None:
    provider = provider_id.strip()
    if not provider:
        return
    path = workbench_usage_ledger_path()
    ledger = _read_ledger(path)

    def should_drop(model_ref: str) -> bool:
        decoded_provider, _ = _decode_model_ref(model_ref)
        return decoded_provider == provider

    for day_bucket in ledger.get("days", {}).values():
        if not isinstance(day_bucket, dict):
            continue
        models = day_bucket.get("models")
        if isinstance(models, dict):
            for model_ref in list(models):
                if should_drop(model_ref):
                    models.pop(model_ref, None)
    lifetime_models = ledger.get("lifetime", {}).get("models")
    if isinstance(lifetime_models, dict):
        for model_ref in list(lifetime_models):
            if should_drop(model_ref):
                lifetime_models.pop(model_ref, None)
    _write_ledger(path, ledger)


def prune_usage_endpoint_model(provider_id: str, model_id: str) -> None:
    provider = provider_id.strip()
    model = model_id.strip()
    if not provider or not model:
        return
    if provider == BUILTIN_DEEPSEEK_PROVIDER_ID:
        target_ref = model
    else:
        target_ref = f"{provider}{MODEL_REF_SEPARATOR}{model}"
    path = workbench_usage_ledger_path()
    ledger = _read_ledger(path)

    for day_bucket in ledger.get("days", {}).values():
        if not isinstance(day_bucket, dict):
            continue
        models = day_bucket.get("models")
        if isinstance(models, dict):
            models.pop(target_ref, None)
    lifetime_models = ledger.get("lifetime", {}).get("models")
    if isinstance(lifetime_models, dict):
        lifetime_models.pop(target_ref, None)
    _write_ledger(path, ledger)
