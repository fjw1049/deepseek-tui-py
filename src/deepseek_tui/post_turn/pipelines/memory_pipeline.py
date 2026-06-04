"""Smart memory capture pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.post_turn.gates import GateConfig, should_capture

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config
    from deepseek_tui.memory.coordinator import MemoryCoordinator


class MemoryPipeline:
    name = "memory"

    def __init__(self, coordinator: MemoryCoordinator, config: Config) -> None:
        self._coordinator = coordinator
        self._config = config

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def after_turn(self, evidence: TurnEvidence) -> None:
        if not self._coordinator.enabled:
            return
        smart = self._config.memory.smart
        cfg = GateConfig(
            min_chars=smart.capture_min_user_chars,
            skip_slash=smart.capture_skip_slash_commands,
        )
        if not should_capture(evidence, cfg):
            return
        inp = evidence.to_capture_input()
        await self._coordinator.capture_after_turn(
            thread_id=inp.thread_id,
            user_text=inp.user_text,
            workspace=inp.workspace,
            messages=inp.messages,
            had_tool_calls=inp.had_tool_calls,
            success=inp.success,
        )

    async def flush_before_loss(self, evidence: TurnEvidence) -> None:
        await self._coordinator.flush_session(evidence.thread_id)
