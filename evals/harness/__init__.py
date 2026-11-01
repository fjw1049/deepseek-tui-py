"""Harness registry for deterministic probes and opt-in live model runs."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable
from pathlib import Path

from evals.harness.judge_probe import run_judge_probe
from evals.harness.live import run_live_cache, run_live_decision
from evals.harness.offline import (
    run_authority_prompt,
    run_cache_prefix,
    run_compaction_state,
    run_tool_boundary,
)
from evals.harness.product import ProductServer, run_product_session
from evals.harness.workspace import run_workspace_task
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
        max_cost_usd: float | None = None,
        prompt_suffix: str = "",
        judge_provider: str | None = None,
        judge_model: str | None = None,
        max_input_tokens: int | None = None,
        turn_timeout_seconds: float = 900.0,
        artifacts_dir: Path = Path("."),
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.remaining_live_requests = remaining_live_requests
        self.max_cost_usd = max_cost_usd
        self.prompt_suffix = prompt_suffix
        self.judge_provider = judge_provider
        self.judge_model = judge_model
        self.max_input_tokens = max_input_tokens
        self.turn_timeout_seconds = turn_timeout_seconds
        self.artifacts_dir = artifacts_dir
        self.requests = 0
        self.metered_requests = 0
        self.priced_requests = 0
        self.cost_usd = 0.0
        self.usage: dict[str, int | float] = {}
        self.trace: list[dict[str, object]] = []
        self._server: _SharedServer = _SharedServer()

    def fork(self) -> HarnessContext:
        """One trial's view: its own trace, budgets as they stand, the shared server."""
        trial = copy.copy(self)
        trial.usage = dict(self.usage)
        trial.trace = []
        return trial

    def absorb(self, trial: HarnessContext, before: HarnessContext) -> None:
        """Add what a finished trial spent, measured from its fork point."""
        spent = before.remaining_live_requests - trial.remaining_live_requests
        self.remaining_live_requests -= spent
        self.requests += trial.requests - before.requests
        self.metered_requests += trial.metered_requests - before.metered_requests
        self.priced_requests += trial.priced_requests - before.priced_requests
        self.cost_usd += trial.cost_usd - before.cost_usd
        for key, value in trial.usage.items():
            self.usage[key] = self.usage.get(key, 0) + value - before.usage.get(key, 0)

    async def product_server(self) -> ProductServer:
        return await self._server.get(self.provider, self.model)

    async def close(self) -> None:
        await self._server.close()


class _SharedServer:
    """Started by the first trial that needs it; every parallel trial then shares it."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._server: ProductServer | None = None
        self._failure: Exception | None = None

    async def get(self, provider: str | None, model: str | None) -> ProductServer:
        async with self._lock:
            if self._failure is not None:
                raise self._failure
            if self._server is None:
                server = ProductServer(provider, model)
                self._server = server
                try:
                    await server.start()
                    await server.preflight()
                except Exception as exc:
                    self._failure = exc
                    raise
            return self._server

    async def close(self) -> None:
        if self._server is not None:
            await self._server.close()


HARNESSES: dict[str, Harness] = {
    "authority_prompt": run_authority_prompt,
    "cache_prefix": run_cache_prefix,
    "compaction_state": run_compaction_state,
    "judge_probe": run_judge_probe,
    "live_decision": run_live_decision,
    "live_cache": run_live_cache,
    "product_session": run_product_session,
    "tool_boundary": run_tool_boundary,
    "workspace_task": run_workspace_task,
}


async def run_harness(case: EvalCase, context: HarnessContext) -> EvalObservation:
    try:
        harness = HARNESSES[case.runner]
    except KeyError as exc:
        raise ValueError(f"unknown runner: {case.runner}") from exc
    return await harness(case, context)
