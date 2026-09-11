"""Outcome verification for bounded real-engine file tasks."""

from evals.schema import EvalCase, EvalObservation, GradeResult


def grade_workspace(case: EvalCase, observation: EvalObservation) -> GradeResult:
    checks = observation.data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("workspace verification evidence is missing")
    failures = [str(check["name"]) for check in checks if check.get("passed") is not True]
    return GradeResult(
        passed=not failures,
        score=(len(checks) - len(failures)) / len(checks),
        metrics={"task.success_rate": float(not failures)},
        reasons=failures,
    )
