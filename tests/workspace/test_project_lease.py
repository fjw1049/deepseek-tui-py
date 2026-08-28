from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeThreadManager,
    RuntimeThreadManagerConfig,
)
from deepseek_tui.server.threads.models import RuntimeTurnStatus, TurnRecord
from deepseek_tui.workspace.project_lease import ProjectLease, ThreadLease


@pytest.mark.asyncio
async def test_project_lease_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    first = ProjectLease(root)
    second = ProjectLease(root)
    assert await first.acquire(nonblocking=True)
    assert await second.acquire(nonblocking=True) is False
    first.release()
    assert await second.acquire(nonblocking=True)
    second.release()
    assert first.path.parent == (tmp_path / "home" / "locks")
    assert os.getpid() > 0


@pytest.mark.asyncio
async def test_thread_lease_is_exclusive_and_scoped_by_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    first = ThreadLease("thr_same")
    second = ThreadLease("thr_same")
    other = ThreadLease("thr_other")

    assert await first.acquire(nonblocking=True)
    assert await second.acquire(nonblocking=True) is False
    assert await other.acquire(nonblocking=True)
    first.release()
    assert await second.acquire(nonblocking=True)

    second.release()
    other.release()
    assert first.path.parent == (tmp_path / "home" / "locks" / "threads")


@pytest.mark.asyncio
async def test_startup_recovery_does_not_interrupt_live_runtime_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    manager_cfg = RuntimeThreadManagerConfig.from_task_data_dir(tasks)
    config = Config(
        features=FeatureConfig(
            mcp=False, tasks=False, subagents=False, automations=False
        )
    )
    first = RuntimeThreadManager(
        config=config,
        workspace=tmp_path,
        manager_cfg=manager_cfg,
        llm_client=object(),
    )
    thread = await first.create_thread(CreateThreadRequest())
    now = datetime.now(timezone.utc)
    first.store.save_turn(
        TurnRecord(
            id="turn_live",
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="live",
            created_at=now,
            started_at=now,
        )
    )
    lease = ThreadLease(thread.id)
    assert await lease.acquire(nonblocking=True)

    second = RuntimeThreadManager(
        config=config,
        workspace=tmp_path,
        manager_cfg=manager_cfg,
        llm_client=object(),
    )
    assert second.store.load_turn("turn_live").status == RuntimeTurnStatus.IN_PROGRESS

    lease.release()
    third = RuntimeThreadManager(
        config=config,
        workspace=tmp_path,
        manager_cfg=manager_cfg,
        llm_client=object(),
    )
    assert third.store.load_turn("turn_live").status == RuntimeTurnStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_manager_thread_operation_reentry_is_task_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    manager = RuntimeThreadManager(
        config=Config(
            features=FeatureConfig(
                mcp=False, tasks=False, subagents=False, automations=False
            )
        ),
        workspace=tmp_path,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tasks),
        llm_client=object(),
    )
    lease = await manager._claim_new_thread_lease("thr_owned")

    # Nested manager calls in the owning request remain valid.
    async with manager._hold_thread_operation("thr_owned"):
        pass

    async def competing_task() -> None:
        async with manager._hold_thread_operation("thr_owned"):
            pass

    with pytest.raises(ValueError, match="active operation"):
        await asyncio.create_task(competing_task())

    await manager._release_thread_lease("thr_owned", expected=lease)
