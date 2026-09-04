"""Structural and provider-reported cache grader."""

from __future__ import annotations

from evals.schema import EvalCase, EvalObservation, GradeResult


def grade_cache(case: EvalCase, observation: EvalObservation) -> GradeResult:
    data = observation.data
    reasons: list[str] = []
    actual = data.get("first_divergence")
    expected = case.expect.get("first_divergence")
    if actual != expected:
        reasons.append(f"first_divergence={actual!r}, expected {expected!r}")
    for key in ("system_cache_control", "tool_cache_control"):
        if key in case.expect and bool(data.get(key)) != bool(case.expect[key]):
            reasons.append(f"{key}={data.get(key)!r}, expected {case.expect[key]!r}")
    minimum_reads = int(case.expect.get("minimum_cache_read_tokens", 0))
    cache_reads = int(observation.usage.get("cache_read_input_tokens", 0))
    if cache_reads < minimum_reads:
        reasons.append(f"cache reads {cache_reads} below minimum {minimum_reads}")
    passed = not reasons
    metrics: dict[str, int | float | bool] = {
        "cache.structural_pass_rate": float(actual == expected),
    }
    if "cache_read_input_tokens" in observation.usage:
        metrics["cache.read_tokens"] = cache_reads
    return GradeResult(
        passed=passed,
        score=1.0 if passed else 0.0,
        metrics=metrics,
        reasons=reasons,
    )
