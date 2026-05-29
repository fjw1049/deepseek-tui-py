from __future__ import annotations

import pytest

from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.memory.coordinator import MemoryCoordinator
from deepseek_tui.memory.provider import CaptureInput, RecallResult


class _StubProvider:
    def __init__(self) -> None:
        self.started = False
        self.captures: list[CaptureInput] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        pass

    async def recall(
        self, thread_id: str, query: str, *, workspace: str | None = None
    ) -> RecallResult:
        return RecallResult(l1_context=f"mem:{query}", inject_position="user")

    async def capture(self, inp: CaptureInput) -> None:
        self.captures.append(inp)

    async def flush_session(self, thread_id: str) -> None:
        pass


def _config(*, smart_enabled: bool = True, mode: str = "hybrid") -> Config:
    return Config(
        memory=MemoryConfig(
            enabled=True,
            mode=mode,
            smart=MemorySmartConfig(enabled=smart_enabled),
        )
    )


@pytest.mark.asyncio
async def test_coordinator_disabled_is_noop() -> None:
    provider = _StubProvider()
    coord = MemoryCoordinator(_config(smart_enabled=False), provider)
    assert coord.recall_enabled_for_turn() is False
    assert coord.should_capture_turn("hello", had_tool_calls=True, success=True) is False
    assert await coord.recall_for_turn("t", "q", workspace="/w") is None


@pytest.mark.asyncio
async def test_coordinator_recall_and_capture() -> None:
    provider = _StubProvider()
    coord = MemoryCoordinator(_config(), provider)
    await coord.start()
    recall = await coord.recall_for_turn("thr_1", "database pool", workspace="/proj")
    assert recall is not None
    assert "database pool" in recall.l1_context

    await coord.capture_after_turn(
        thread_id="thr_1",
        user_text="please tune the database connection pool",
        workspace="/proj",
        messages=[],
        had_tool_calls=True,
        success=True,
    )
    assert len(provider.captures) == 1
    await coord.stop()


def test_thread_memory_mode_overrides_global_recall() -> None:
    coord = MemoryCoordinator(_config(mode="manual"), _StubProvider())
    assert coord.recall_enabled_for_turn() is False
    assert coord.recall_enabled_for_turn("hybrid") is True
    assert coord.memory_md_enabled() is True
    assert coord.memory_md_enabled("auto") is False
