"""Compare a run summary with committed absolute regression gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def compare_files(baseline_path: Path, summary_path: Path) -> list[str]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return compare_metrics(baseline, summary)


def compare_metrics(baseline: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    observed = summary.get("metrics", {})
    for name, gate in baseline.get("gates", {}).items():
        aggregate = observed.get(name)
        if not isinstance(aggregate, dict) or "mean" not in aggregate:
            failures.append(f"missing metric: {name}")
            continue
        value = float(aggregate["mean"])
        if "min" in gate and value < float(gate["min"]):
            failures.append(f"{name}={value:.6g} below minimum {gate['min']}")
        if "max" in gate and value > float(gate["max"]):
            failures.append(f"{name}={value:.6g} above maximum {gate['max']}")
    return failures
