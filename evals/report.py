"""Artifact writing, redaction, and metric aggregation."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.schema import RunSummary, TrialResult

_SECRET_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "x-api-key",
}
_SECRET_TEXT = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+|\b(sk-[A-Za-z0-9_-]{8,})"
)


def redact(value: Any) -> Any:
    """Remove credentials recursively without destroying token metrics."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in _SECRET_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_TEXT.sub(lambda match: f"{match.group(1) or ''}[REDACTED]", value)
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(redact(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def append_result(path: Path, result: TrialResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        payload = redact(result.model_dump(mode="json"))
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def summarize(run_id: str, results: list[TrialResult]) -> RunSummary:
    metric_values: dict[str, list[float]] = defaultdict(list)
    for result in results:
        if result.grade is None:
            continue
        for name, value in result.grade.metrics.items():
            metric_values[name].append(float(value))

    decided = [result for result in results if result.status != "skipped"]
    passed = sum(result.status == "passed" for result in results)
    failed = sum(result.status == "failed" for result in results)
    errors = sum(result.status == "error" for result in results)
    metrics = {
        name: {
            "count": len(values),
            "mean": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
        }
        for name, values in sorted(metric_values.items())
        if values
    }
    metrics["run.pass_rate"] = {
        "count": len(decided),
        "mean": passed / len(decided) if decided else 0.0,
        "min": passed / len(decided) if decided else 0.0,
        "max": passed / len(decided) if decided else 0.0,
    }
    return RunSummary(
        run_id=run_id,
        completed_at=datetime.now(timezone.utc).isoformat(),
        total=len(results),
        passed=passed,
        failed=failed,
        skipped=sum(result.status == "skipped" for result in results),
        errors=errors,
        metrics=metrics,
    )
