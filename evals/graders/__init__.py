"""Grader registry. Security facts stay deterministic; prose is secondary."""

from __future__ import annotations

from collections.abc import Callable

from evals.graders.authority import grade_authority
from evals.graders.cache import grade_cache
from evals.graders.completion import grade_completion
from evals.graders.constraints import grade_constraints
from evals.graders.tooling import grade_tooling
from evals.schema import EvalCase, EvalObservation, GradeResult

Grader = Callable[[EvalCase, EvalObservation], GradeResult]

GRADERS: dict[str, Grader] = {
    "authority": grade_authority,
    "cache": grade_cache,
    "completion": grade_completion,
    "constraints": grade_constraints,
    "tooling": grade_tooling,
}


def grade(case: EvalCase, observation: EvalObservation) -> GradeResult:
    try:
        grader = GRADERS[case.grader]
    except KeyError as exc:
        raise ValueError(f"unknown grader: {case.grader}") from exc
    return grader(case, observation)
