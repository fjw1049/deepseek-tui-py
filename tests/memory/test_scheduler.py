from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deepseek_tui.memory.pipeline import L1Scheduler


@pytest.mark.asyncio
async def test_l1_scheduler_warmup_thresholds_progress() -> None:
    batches: list[list[dict[str, Any]]] = []

    async def run_extraction(_thread_id: str, batch: list[dict[str, Any]]) -> None:
        batches.append(batch)

    scheduler = L1Scheduler(
        every_n=5,
        idle_timeout_s=999,
        warmup_enabled=True,
        run_extraction=run_extraction,
    )
    try:
        scheduler.notify_messages("thr", [{"content": "one"}])
        await asyncio.gather(*list(scheduler._tasks))
        assert [len(batch) for batch in batches] == [1]

        scheduler.notify_messages("thr", [{"content": "two-a"}])
        assert len(batches) == 1
        scheduler.notify_messages("thr", [{"content": "two-b"}])
        await asyncio.gather(*list(scheduler._tasks))
        assert [len(batch) for batch in batches] == [1, 2]

        for idx in range(3):
            scheduler.notify_messages("thr", [{"content": f"four-{idx}"}])
        assert len(batches) == 2
        scheduler.notify_messages("thr", [{"content": "four-3"}])
        await asyncio.gather(*list(scheduler._tasks))
        assert [len(batch) for batch in batches] == [1, 2, 4]
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_l1_scheduler_can_disable_warmup() -> None:
    batches: list[list[dict[str, Any]]] = []

    async def run_extraction(_thread_id: str, batch: list[dict[str, Any]]) -> None:
        batches.append(batch)

    scheduler = L1Scheduler(
        every_n=3,
        idle_timeout_s=999,
        warmup_enabled=False,
        run_extraction=run_extraction,
    )
    try:
        scheduler.notify_messages("thr", [{"content": "one"}])
        scheduler.notify_messages("thr", [{"content": "two"}])
        assert batches == []
        scheduler.notify_messages("thr", [{"content": "three"}])
        await asyncio.gather(*list(scheduler._tasks))
        assert [len(batch) for batch in batches] == [3]
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_l1_scheduler_flush_drains_already_queued_job() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    batches: list[list[dict[str, Any]]] = []

    async def run_extraction(_thread_id: str, batch: list[dict[str, Any]]) -> None:
        started.set()
        await release.wait()
        batches.append(batch)

    scheduler = L1Scheduler(
        every_n=5,
        idle_timeout_s=999,
        warmup_enabled=True,
        run_extraction=run_extraction,
    )
    try:
        scheduler.notify_messages("thr", [{"content": "one"}])
        await started.wait()
        flush_task = asyncio.create_task(scheduler.flush_session("thr"))
        await asyncio.sleep(0)
        assert not flush_task.done()
        release.set()
        await flush_task
        assert [len(batch) for batch in batches] == [1]
    finally:
        release.set()
        await scheduler.stop()


@pytest.mark.asyncio
async def test_l1_scheduler_dedup_while_running() -> None:
    """A second trigger while L1 is in flight must re-buffer, not start a 2nd job."""
    started = asyncio.Event()
    release = asyncio.Event()
    batches: list[list[dict[str, Any]]] = []

    async def run_extraction(_thread_id: str, batch: list[dict[str, Any]]) -> None:
        started.set()
        await release.wait()
        batches.append(batch)

    scheduler = L1Scheduler(
        every_n=1,
        idle_timeout_s=999,
        warmup_enabled=False,
        run_extraction=run_extraction,
    )
    try:
        # First trigger starts job1, which hangs on `release`.
        scheduler.notify_messages("thr", [{"content": "one"}])
        await started.wait()
        running = [t for t in scheduler._tasks if t.get_name() == "l1-extract-thr"]
        assert len(running) == 1

        # Second trigger while job1 runs: must NOT spawn a second extract task.
        scheduler.notify_messages("thr", [{"content": "two"}])
        await asyncio.sleep(0)
        running = [
            t
            for t in scheduler._tasks
            if t.get_name() == "l1-extract-thr" and not t.done()
        ]
        assert len(running) == 1, "dedup failed: a second L1 job was started"
        assert batches == []
        # The second batch was re-buffered, not dropped.
        assert scheduler._states["thr"].pending_messages == [{"content": "two"}]

        # Release job1; flush then drains the re-buffered batch as a 2nd run.
        release.set()
        await scheduler.flush_session("thr")
        assert [b for batch in batches for b in batch] == [
            {"content": "one"},
            {"content": "two"},
        ]
    finally:
        release.set()
        await scheduler.stop()
