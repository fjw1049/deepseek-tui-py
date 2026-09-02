from __future__ import annotations

import asyncio
import errno
import os
import threading
import time
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
from deepseek_tui.workspace import project_lease as project_lease_module
from deepseek_tui.workspace.project_lease import ProjectLease, ThreadLease


class _FakeMsvcrt:
    LK_LOCK = 1
    LK_NBLCK = 2
    LK_UNLCK = 3

    def __init__(self) -> None:
        self._owners: dict[tuple[int, int, int, int], int] = {}
        self.calls: list[int] = []

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.calls.append(mode)
        stat = os.fstat(fd)
        start = os.lseek(fd, 0, os.SEEK_CUR)
        key = (stat.st_dev, stat.st_ino, start, nbytes)
        owner = self._owners.get(key)
        if mode == self.LK_UNLCK:
            if owner != fd:
                raise OSError(errno.EACCES, "lock not owned")
            self._owners.pop(key)
            return
        if owner is not None and owner != fd:
            raise OSError(errno.EACCES, "already locked")
        self._owners[key] = fd


def test_windows_file_lease_backend_is_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _FakeMsvcrt()
    monkeypatch.setattr(project_lease_module, "fcntl", None)
    monkeypatch.setattr(project_lease_module, "msvcrt", backend, raising=False)
    monkeypatch.setattr(project_lease_module, "_LOCK_RETRY_INTERVAL_SECONDS", 0.001)
    first = project_lease_module.FileLease(tmp_path / "windows.lock")
    second = project_lease_module.FileLease(tmp_path / "windows.lock")

    assert first.acquire_blocking(nonblocking=True)
    assert second.acquire_blocking(nonblocking=True) is False
    assert backend.calls == [backend.LK_NBLCK, backend.LK_NBLCK]
    assert first.path.read_text() == f"{os.getpid()}\n"

    def release_first() -> None:
        time.sleep(0.02)
        first.release()

    release_thread = threading.Thread(target=release_first)
    release_thread.start()
    assert second.acquire_blocking()
    release_thread.join()
    assert backend.LK_LOCK not in backend.calls
    assert backend.calls.count(backend.LK_NBLCK) > 2
    second.release()
    assert backend.calls[-1] == backend.LK_UNLCK


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
async def test_cancelled_lease_waiter_cannot_acquire_in_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    first = ProjectLease(root)
    cancelled_waiter = ProjectLease(root)
    successor = ProjectLease(root)

    assert await first.acquire(nonblocking=True)
    waiter = asyncio.create_task(cancelled_waiter.acquire())
    await asyncio.sleep(0.1)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    first.release()
    # A blocking worker leaked by the cancelled task would acquire here and
    # prevent the next legitimate caller from taking the lease.
    await asyncio.sleep(0.1)
    assert cancelled_waiter._fh is None
    assert await successor.acquire(nonblocking=True)
    successor.release()


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
async def test_startup_recovery_makes_stale_publish_request_actionable(
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
    blocker = await manager.create_thread(CreateThreadRequest())
    waiter = await manager.create_thread(CreateThreadRequest())
    waiter.publish_pending = True
    waiter.publish_blocked = True
    waiter.publish_request_action = "keep_project"
    waiter.publish_request_paths = ["app.py"]
    waiter.publish_waiting_on = blocker.id
    manager.store.save_thread(waiter)

    manager._recover_interrupted_state()

    recovered = manager.store.load_thread(waiter.id)
    assert recovered.publish_waiting_on is None
    assert recovered.publish_request_action == "keep_project"
    assert recovered.publish_request_paths == ["app.py"]
    assert recovered.publish_pending is True
    assert recovered.publish_blocked is True


@pytest.mark.asyncio
async def test_startup_recovery_keeps_waiting_for_live_blocker(
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
    blocker = await manager.create_thread(CreateThreadRequest())
    waiter = await manager.create_thread(CreateThreadRequest())
    waiter.publish_pending = True
    waiter.publish_request_action = "apply"
    waiter.publish_waiting_on = blocker.id
    manager.store.save_thread(waiter)
    blocker_lease = ThreadLease(blocker.id)
    assert await blocker_lease.acquire(nonblocking=True)

    manager._recover_interrupted_state()

    recovered = manager.store.load_thread(waiter.id)
    assert recovered.publish_waiting_on == blocker.id
    assert recovered.publish_request_action == "apply"
    blocker_lease.release()


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


def test_permanent_lock_error_raises_instead_of_returning_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lease = project_lease_module.FileLease(tmp_path / "broken.lock")

    def _boom(fd: int, operation: int) -> None:
        raise OSError(errno.ENOSPC, "no space left on device")

    monkeypatch.setattr(project_lease_module.fcntl, "flock", _boom)
    with pytest.raises(OSError, match="no space left"):
        lease.acquire_blocking(nonblocking=True)
