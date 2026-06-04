"""Post-turn pipeline protocol."""

from __future__ import annotations

from typing import Protocol

from deepseek_tui.post_turn.evidence import TurnEvidence


class PostTurnPipeline(Protocol):
    name: str

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def after_turn(self, evidence: TurnEvidence) -> None: ...

    async def flush_before_loss(self, evidence: TurnEvidence) -> None: ...
