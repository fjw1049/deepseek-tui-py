"""Feed the reviewer a planted result. Measures the reviewer, not the agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from evals.judge import judge_probe
from evals.schema import EvalCase, EvalObservation

if TYPE_CHECKING:
    from evals.harness import HarnessContext


async def run_judge_probe(case: EvalCase, context: HarnessContext) -> EvalObservation:
    return EvalObservation(data={"judge": await judge_probe(case, context)})
