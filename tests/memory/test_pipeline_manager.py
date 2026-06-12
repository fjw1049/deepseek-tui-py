from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deepseek_tui.memory.l2 import SceneExtractionResult
from deepseek_tui.memory.pipeline import MemoryPipelineConfig, MemoryPipelineManager


@pytest.mark.asyncio
async def test_pipeline_flush_runs_l2_and_triggered_l3(tmp_path) -> None:
    l2_batches: list[list[dict[str, Any]]] = []
    l3_reasons: list[str] = []

    async def run_l2(_thread_id: str, scenes: list[dict[str, Any]]) -> SceneExtractionResult:
        l2_batches.append(scenes)
        blocks = tmp_path / "scene_blocks"
        blocks.mkdir(parents=True, exist_ok=True)
        (blocks / "work.md").write_text("# Work\n", encoding="utf-8")
        return SceneExtractionResult(scenes_processed=1, latest_cursor="cursor-1")

    async def run_l3(reason: str, workspace: str | None = None) -> None:
        l3_reasons.append(reason)

    pipeline = MemoryPipelineManager(
        data_dir=tmp_path,
        config=MemoryPipelineConfig(
            l2_delay_after_l1_seconds=999,
            l2_min_interval_seconds=0,
            l2_max_interval_seconds=999,
            l3_persona_interval=50,
        ),
        run_l2=run_l2,
        run_l3=run_l3,
    )
    try:
        pipeline.notify_l1_completed(
            "thr",
            scenes=[{"scene_name": "Work", "memories": [{"content": "x"}]}],
            inserted=1,
        )
        await pipeline.flush_session("thr")
        assert len(l2_batches) == 1
        assert l3_reasons
    finally:
        await pipeline.stop()


@pytest.mark.asyncio
async def test_pipeline_l2_can_be_disabled(tmp_path) -> None:
    called = False

    async def run_l2(_thread_id: str, _scenes: list[dict[str, Any]]) -> SceneExtractionResult:
        nonlocal called
        called = True
        return SceneExtractionResult()

    async def run_l3(_reason: str, _workspace: str | None = None) -> None:
        raise AssertionError("L3 should not run")

    pipeline = MemoryPipelineManager(
        data_dir=tmp_path,
        config=MemoryPipelineConfig(l2_enabled=False),
        run_l2=run_l2,
        run_l3=run_l3,
    )
    try:
        pipeline.notify_l1_completed(
            "thr",
            scenes=[{"scene_name": "Work", "memories": [{"content": "x"}]}],
            inserted=1,
        )
        await pipeline.flush_session("thr")
        assert not called
    finally:
        await pipeline.stop()


@pytest.mark.asyncio
async def test_pipeline_timer_runs_l2_without_flush(tmp_path) -> None:
    ran = asyncio.Event()

    async def run_l2(_thread_id: str, _scenes: list[dict[str, Any]]) -> SceneExtractionResult:
        ran.set()
        return SceneExtractionResult(scenes_processed=0)

    async def run_l3(_reason: str, _workspace: str | None = None) -> None:
        return None

    pipeline = MemoryPipelineManager(
        data_dir=tmp_path,
        config=MemoryPipelineConfig(
            l2_delay_after_l1_seconds=0,
            l2_min_interval_seconds=0,
            l2_max_interval_seconds=999,
        ),
        run_l2=run_l2,
        run_l3=run_l3,
    )
    try:
        pipeline.notify_l1_completed(
            "thr",
            scenes=[{"scene_name": "Work", "memories": [{"content": "x"}]}],
            inserted=1,
        )
        await asyncio.wait_for(ran.wait(), timeout=1)
    finally:
        await pipeline.stop()


@pytest.mark.asyncio
async def test_pipeline_retries_failed_l2_job(tmp_path) -> None:
    attempts = 0
    done = asyncio.Event()

    async def run_l2(_thread_id: str, _scenes: list[dict[str, Any]]) -> SceneExtractionResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        done.set()
        return SceneExtractionResult(scenes_processed=0)

    async def run_l3(_reason: str, _workspace: str | None = None) -> None:
        return None

    pipeline = MemoryPipelineManager(
        data_dir=tmp_path,
        config=MemoryPipelineConfig(
            l2_delay_after_l1_seconds=0,
            l2_min_interval_seconds=0,
            l2_retry_delay_seconds=0,
        ),
        run_l2=run_l2,
        run_l3=run_l3,
    )
    try:
        pipeline.notify_l1_completed(
            "thr",
            scenes=[{"scene_name": "Work", "memories": [{"content": "x"}]}],
            inserted=1,
        )
        await asyncio.wait_for(done.wait(), timeout=1)
        assert attempts == 2
    finally:
        await pipeline.stop()


def test_pipeline_gc_prunes_cold_session(tmp_path) -> None:
    async def run_l2(_thread_id: str, _scenes: list[dict[str, Any]]) -> SceneExtractionResult:
        return SceneExtractionResult()

    async def run_l3(_reason: str, _workspace: str | None = None) -> None:
        return None

    pipeline = MemoryPipelineManager(
        data_dir=tmp_path,
        config=MemoryPipelineConfig(
            session_gc_every_notifications=1,
            l2_session_active_window_hours=0,
            session_gc_inactive_multiplier=0,
        ),
        run_l2=run_l2,
        run_l3=run_l3,
    )
    try:
        pipeline.notify_l1_completed("old", scenes=None, inserted=1)
        checkpoint = pipeline._checkpoint.read()
        checkpoint.pipeline_states["old"].last_active_at = 1
        pipeline._checkpoint.write(checkpoint)
        pipeline.notify_l1_completed("new", scenes=None, inserted=1)
        checkpoint = pipeline._checkpoint.read()
        assert "old" not in checkpoint.pipeline_states
        assert "new" in checkpoint.pipeline_states
    finally:
        # stop is async; no tasks are started in this test.
        pass
