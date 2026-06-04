"""Orchestrates post-turn pipelines (memory + evolution)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.post_turn.pipeline import PostTurnPipeline

logger = logging.getLogger(__name__)


class PostTurnOrchestrator:
    def __init__(
        self,
        pipelines: list[PostTurnPipeline],
        *,
        flush_timeout_s: float = 30.0,
    ) -> None:
        self._pipelines = list(pipelines)
        self._flush_timeout_s = flush_timeout_s

    async def start(self) -> None:
        for pipeline in self._pipelines:
            await pipeline.start()

    async def stop(self) -> None:
        for pipeline in reversed(self._pipelines):
            await pipeline.stop()

    async def after_turn(self, evidence: TurnEvidence) -> None:
        for pipeline in self._pipelines:
            try:
                await pipeline.after_turn(evidence)
            except Exception:
                logger.exception(
                    "post_turn after_turn failed pipeline=%s", pipeline.name
                )

    async def flush_before_loss(self, evidence: TurnEvidence) -> None:
        flush_ev = replace(evidence, flush_mode=True)
        for pipeline in self._pipelines:
            try:
                await asyncio.wait_for(
                    pipeline.flush_before_loss(flush_ev),
                    timeout=self._flush_timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning("post_turn flush timeout pipeline=%s", pipeline.name)
            except Exception:
                logger.exception(
                    "post_turn flush failed pipeline=%s", pipeline.name
                )

    def on_main_tool_called(self, tool_name: str) -> None:
        for pipeline in self._pipelines:
            if hasattr(pipeline, "on_main_tool_called"):
                pipeline.on_main_tool_called(tool_name)
