"""Capture gate respects turn outcome success."""

from __future__ import annotations

import pytest

from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.memory.coordinator import MemoryCoordinator
from deepseek_tui.memory.coordinator import CaptureInput


class _CaptureSpy:
    def __init__(self) -> None:
        self.captures: list[CaptureInput] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def recall(self, thread_id: str, query: str, *, workspace: str | None = None):
        from deepseek_tui.memory.coordinator import RecallResult

        return RecallResult()

    async def capture(self, inp: CaptureInput) -> None:
        self.captures.append(inp)

    async def flush_session(self, thread_id: str) -> None:
        pass


def _coord() -> tuple[MemoryCoordinator, _CaptureSpy]:
    cfg = Config(
        memory=MemoryConfig(
            enabled=True,
            mode="hybrid",
            smart=MemorySmartConfig(enabled=True),
        )
    )
    spy = _CaptureSpy()
    return MemoryCoordinator(cfg, spy), spy


@pytest.mark.asyncio
async def test_capture_skipped_when_success_false() -> None:
    coord, spy = _coord()
    await coord.capture_after_turn(
        thread_id="t1",
        user_text="This is a long enough user message for capture",
        workspace="/ws",
        messages=[],
        had_tool_calls=False,
        success=False,
    )
    assert spy.captures == []


@pytest.mark.asyncio
async def test_capture_runs_when_success_true() -> None:
    coord, spy = _coord()
    await coord.capture_after_turn(
        thread_id="t1",
        user_text="This is a long enough user message for capture",
        workspace="/ws",
        messages=[{"role": "assistant", "content": "ok"}],
        had_tool_calls=True,
        success=True,
    )
    assert len(spy.captures) == 1
