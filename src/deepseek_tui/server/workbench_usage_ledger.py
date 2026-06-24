"""Persistent Workbench model usage ledger (user-level, 90-day retention)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from deepseek_tui.config.paths import workbench_usage_ledger_path

logger = logging.getLogger(__name__)

LEDGER_SCHEMA_VERSION = 1
RETENTION_DAYS = 90
BUILTIN_DEEPSEEK_PROVIDER_ID = "deepseek"
MODEL_REF_SEPARATOR = "::"
LOCK_TIMEOUT_SECONDS = 30.0
LOCK_RETRY_SECONDS = 0.05


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
    }


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


@contextmanager
def _ledger_file_lock(path: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    lock_path = _lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    acquired = False
    while time.monotonic() < deadline:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()}\n")
            acquired = True
            break
        except FileExistsError:
            time.sleep(LOCK_RETRY_SECONDS)
    if not acquired:
        raise TimeoutError(f"timed out acquiring usage ledger lock: {lock_path}")
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _normalize_ledger(parsed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parsed.get("days"), dict):
        parsed["days"] = {}
    if not isinstance(parsed.get("processedTurnIds"), dict):
        parsed["processedTurnIds"] = {}
    parsed.pop("lifetime", None)
    parsed["schemaVersion"] = LEDGER_SCHEMA_VERSION
    parsed["retentionDays"] = RETENTION_DAYS
    return parsed


def _read_ledger(path: Path) -> tuple[dict[str, Any], bool]:
    """Return ``(ledger, readable)``.

    ``readable`` is ``False`` when an on-disk ledger exists but cannot be loaded
    safely (schema mismatch or corrupt JSON). Callers must not overwrite the
    file in that case.
    """
    if not path.exists():
        return _empty_ledger(), True
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return _empty_ledger(), False
    if not isinstance(parsed, dict):
        return _empty_ledger(), False
    if parsed.get("schemaVersion") != LEDGER_SCHEMA_VERSION:
        return _empty_ledger(), False
    return _normalize_ledger(parsed), True


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload_ledger = _normalize_ledger(dict(ledger))
    payload_ledger["updatedAt"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(payload_ledger, ensure_ascii=False, indent=2, sort_keys=True)
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


def _recompute_day_totals(day_bucket: dict[str, Any]) -> None:
    models = day_bucket.get("models")
    if not isinstance(models, dict):
        day_bucket["models"] = {}
        models = day_bucket["models"]
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_cny": 0.0,
        "turns": 0,
    }
    for bucket in models.values():
        if isinstance(bucket, dict):
            _merge_bucket(totals, bucket)
    day_bucket["totals"] = totals


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
    session: dict[str, dict[str, Any]] = {}

    _merge_turn_usage_models(session, turn_usage, fallback_model=fallback_model)
    for model_ref, bucket in session.items():
        day_model = models.setdefault(model_ref, _empty_bucket(model_ref))
        _merge_bucket(day_model, bucket)

    _recompute_day_totals(day_bucket)


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


def _mutate_ledger(path: Path, mutator: Any) -> None:
    with _ledger_file_lock(path):
        ledger, readable = _read_ledger(path)
        if not readable:
            logger.warning(
                "usage ledger at %s is unreadable; refusing to overwrite on-disk data",
                path,
            )
            return
        mutator(ledger)
        _write_ledger(path, ledger)


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
    _ = thread_id  # reserved for future per-thread rollups

    path = workbench_usage_ledger_path()

    def mutate(ledger: dict[str, Any]) -> None:
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

    _mutate_ledger(path, mutate)


def prune_usage_provider(provider_id: str) -> None:
    provider = provider_id.strip()
    if not provider:
        return
    path = workbench_usage_ledger_path()

    def should_drop(model_ref: str) -> bool:
        decoded_provider, _ = _decode_model_ref(model_ref)
        return decoded_provider == provider

    def mutate(ledger: dict[str, Any]) -> None:
        for day_bucket in ledger.get("days", {}).values():
            if not isinstance(day_bucket, dict):
                continue
            models = day_bucket.get("models")
            if isinstance(models, dict):
                for model_ref in list(models):
                    if should_drop(model_ref):
                        models.pop(model_ref, None)
            _recompute_day_totals(day_bucket)

    _mutate_ledger(path, mutate)


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

    def mutate(ledger: dict[str, Any]) -> None:
        for day_bucket in ledger.get("days", {}).values():
            if not isinstance(day_bucket, dict):
                continue
            models = day_bucket.get("models")
            if isinstance(models, dict):
                models.pop(target_ref, None)
            _recompute_day_totals(day_bucket)

    _mutate_ledger(path, mutate)
