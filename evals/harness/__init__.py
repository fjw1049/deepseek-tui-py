"""Harness registry for deterministic probes and opt-in live model runs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from evals.harness.live import run_live_cache, run_live_decision
from evals.harness.offline import (
    run_authority_prompt,
    run_cache_prefix,
    run_compaction_state,
    run_completion_evidence,
    run_tool_boundary,
)
from evals.schema import EvalCase, EvalObservation

Harness = Callable[[EvalCase, "HarnessContext"], Awaitable[EvalObservation]]


class HarnessContext:
    def __init__(
        self,
        *,
        workspace: str,
        provider: str | None = None,
        model: str | None = None,
        max_output_tokens: int = 2048,
        remaining_live_requests: int = 0,
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.remaining_live_requests = remaining_live_requests


HARNESSES: dict[str, Harness] = {
    "authority_prompt": run_authority_prompt,
    "cache_prefix": run_cache_prefix,
    "compaction_state": run_compaction_state,
    "completion_evidence": run_completion_evidence,
    "live_decision": run_live_decision,
    "live_cache": run_live_cache,
    "tool_boundary": run_tool_boundary,
}


async def run_harness(
    case: EvalCase, context: HarnessContext
) -> EvalObservation:
    try:
        harness = HARNESSES[case.runner]
    except KeyError as exc:
        raise ValueError(f"unknown runner: {case.runner}") from exc
    return await harness(case, context)
