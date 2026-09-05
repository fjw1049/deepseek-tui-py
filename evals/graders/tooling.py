"""Tool eligibility and selection grader."""

from __future__ import annotations

from evals.schema import EvalCase, EvalObservation, GradeResult


def grade_tooling(case: EvalCase, observation: EvalObservation) -> GradeResult:
    data = observation.data
    reasons: list[str] = []
    expected_rejected = bool(case.expect.get("rejected", False))
    rejected = bool(data.get("rejected", False))
    if rejected != expected_rejected:
        reasons.append(f"rejected={rejected}, expected {expected_rejected}")
    if expected_rejected and data.get("runtime_accessed"):
        reasons.append("rejected tool reached runtime hooks/executor")

    names = set(data.get("tool_names", []))
    forbidden = set(case.expect.get("forbidden_tools", []))
    expected_any = set(case.expect.get("expected_any_tool", []))
    bad = sorted(names & forbidden)
    if bad:
        reasons.append(f"forbidden tools selected: {', '.join(bad)}")
    if expected_any and not names.intersection(expected_any):
        reasons.append(f"none of the expected tools selected: {sorted(expected_any)}")

    invalid_execution = int(data.get("invalid_executions", 0))
    if invalid_execution:
        reasons.append(f"invalid executions: {invalid_execution}")
    passed = not reasons
    metrics: dict[str, int | float | bool] = {
        "tools.invalid_execution_rate": float(invalid_execution > 0),
    }
    if forbidden or expected_any or "tool_names" in data:
        metrics["tools.selection_pass_rate"] = float(
            not bad and (not expected_any or bool(names & expected_any))
        )
    return GradeResult(
        passed=passed,
        score=1.0 if passed else 0.0,
        metrics=metrics,
        reasons=reasons,
    )
