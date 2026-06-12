"""Capture → recall contract without live LLM."""

from __future__ import annotations

import pytest

from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.memory.coordinator import MemoryCoordinator
from deepseek_tui.memory.seed import NativeMemoryProvider
from deepseek_tui.memory.coordinator import CaptureInput


class _FakeClient:
    async def stream_with_retry(self, request):  # noqa: ANN001
        if False:
            yield


def _config(tmp_path) -> Config:
    return Config(
        memory=MemoryConfig(
            enabled=True,
            mode="hybrid",
            smart=MemorySmartConfig(
                enabled=True,
                data_dir=str(tmp_path / "mem"),
                l1_every_n=99,
            ),
        )
    )


@pytest.mark.asyncio
async def test_insert_then_recall_via_coordinator(tmp_path) -> None:
    cfg = _config(tmp_path)
    provider = NativeMemoryProvider(cfg, _FakeClient())  # type: ignore[arg-type]
    await provider.start()
    try:
        provider._store.insert_memory(
            content="The staging API base URL is https://staging.example.com",
            mem_type="instruction",
            workspace=str(tmp_path.resolve()),
            thread_id="thr_contract",
            confidence=1.0,
        )
        coord = MemoryCoordinator(cfg, provider)
        recall = await coord.recall_for_turn(
            "thr_contract",
            "staging API URL",
            workspace=str(tmp_path.resolve()),
        )
        assert recall is not None
        assert "staging.example.com" in recall.l1_context
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_capture_l0_without_l1_when_every_n_high(tmp_path) -> None:
    cfg = _config(tmp_path)
    provider = NativeMemoryProvider(cfg, _FakeClient())  # type: ignore[arg-type]
    await provider.start()
    try:
        coord = MemoryCoordinator(cfg, provider)
        await coord.capture_after_turn(
            thread_id="thr_l0",
            user_text="Explain how connection pooling works in detail please",
            workspace=str(tmp_path.resolve()),
            messages=[{"role": "assistant", "content": "Pooling reuses connections."}],
            had_tool_calls=False,
            success=True,
        )
        l0_dir = tmp_path / "mem" / "l0"
        assert l0_dir.is_dir()
        assert provider._store.count_memories_for_thread("thr_l0") == 0
    finally:
        await provider.stop()
