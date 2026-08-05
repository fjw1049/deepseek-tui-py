"""AutomationManager unit tests (parity subset; no live LLM)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.tools.automation import (
    MISFIRE_GRACE_SECS,
    AutomationManager,
    AutomationRunStatus,
    AutomationSchedule,
    AutomationStatus,
    CreateAutomationRequest,
    UpdateAutomationRequest,
)
from deepseek_tui.tools.runtime import create_tool_runtime


@pytest.mark.asyncio
async def test_automations_requires_tasks_fail_fast() -> None:
    cfg = Config(features=FeatureConfig(automations=True, tasks=False))
    with pytest.raises(ValueError, match="requires features.tasks"):
        await create_tool_runtime(config=cfg)


def test_cron_schedule_is_anchored_to_the_wall_clock() -> None:
    """'every 2 hours' means 10:00/12:00/14:00, not 'creation time + 2h'."""
    sched = AutomationSchedule.parse("0 */2 * * *", "Asia/Shanghai")
    after = datetime(2026, 8, 4, 9, 37, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    fires = []
    for _ in range(3):
        after = sched.next_after(after)
        fires.append(after.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%H:%M"))
    assert fires == ["10:00", "12:00", "14:00"]


def test_weekly_schedule_survives_a_dst_transition() -> None:
    """The old RRULE math drifted to 10:00 across the spring-forward."""
    sched = AutomationSchedule.parse("0 9 * * MON", "America/New_York")
    ny = ZoneInfo("America/New_York")
    # 2026-03-08 is the US spring-forward; the next Monday follows it.
    start = datetime(2026, 3, 6, 12, 0, tzinfo=ny)
    fired = sched.next_after(start).astimezone(ny)
    assert (fired.month, fired.day) == (3, 9)
    assert (fired.hour, fired.minute) == (9, 0)


def test_invalid_schedule_is_rejected_at_parse_time() -> None:
    with pytest.raises(ValueError, match="Invalid cron expression"):
        AutomationSchedule.parse("0 25 * * *", "Asia/Shanghai")
    with pytest.raises(ValueError, match="Unknown timezone"):
        AutomationSchedule.parse("0 9 * * *", "Mars/Olympus")


def test_create_requires_schedule_or_run_at(tmp_path: Path) -> None:
    mgr = AutomationManager.open(tmp_path / "auto")
    with pytest.raises(ValueError, match="schedule.*or run_at"):
        mgr.create_automation(CreateAutomationRequest(name="n", prompt="p"))


def test_create_list_update_automation(tmp_path: Path) -> None:
    mgr = AutomationManager.open(tmp_path / "auto")
    created = mgr.create_automation(
        CreateAutomationRequest(
            name="morning",
            prompt="digest",
            schedule="0 * * * *",
            delivery={"mode": "feishu", "chat_id": "ou_x"},
            digest={"sources": ["feishu:today_local"]},
        )
    )
    assert created.delivery is not None
    assert created.timezone  # defaulted from the host
    listed = mgr.list_automations()
    assert len(listed) == 1
    updated = mgr.update_automation(
        created.id,
        UpdateAutomationRequest(name="evening"),
    )
    assert updated.name == "evening"
    paused = mgr.pause_automation(created.id)
    assert paused.status is AutomationStatus.PAUSED
    resumed = mgr.resume_automation(created.id)
    assert resumed.status is AutomationStatus.ACTIVE


def _daily_automation_due(mgr: AutomationManager, *, seconds_ago: float) -> str:
    """A daily 09:00 job whose slot came due ``seconds_ago`` in the past."""
    record = mgr.create_automation(
        CreateAutomationRequest(
            name="daily report",
            prompt="report",
            schedule="0 9 * * *",
        )
    )
    due = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    record.next_run_at = due.isoformat()
    mgr.save_automation(record)
    return record.id


def _one_shot_due(mgr: AutomationManager, *, seconds_ago: float) -> str:
    """A one-shot job whose target time passed ``seconds_ago``."""
    run_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    record = mgr.create_automation(
        CreateAutomationRequest(
            name="remind me",
            prompt="remind",
            run_at=run_at.isoformat(),
        )
    )
    assert record.is_one_shot
    return record.id


@pytest.fixture
def fired_slots(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every enqueued run instead of touching the TaskManager."""
    slots: list[str] = []

    async def fake_enqueue(self, automation, run, task_manager):  # type: ignore[no-untyped-def] # noqa: ANN001, ANN202
        run.task_id = f"task-{len(slots)}"
        run.status = AutomationRunStatus.QUEUED
        slots.append(run.scheduled_for)

    monkeypatch.setattr(AutomationManager, "_enqueue_run_task", fake_enqueue)
    return slots


@pytest.mark.asyncio
async def test_slots_missed_during_downtime_do_not_backfill(
    tmp_path: Path, fired_slots: list[str]
) -> None:
    """Three days offline must not replay one slot per tick."""
    mgr = AutomationManager.open(tmp_path / "auto")
    automation_id = _daily_automation_due(mgr, seconds_ago=3 * 86400)

    for _ in range(6):
        await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]

    assert fired_slots == []
    assert _parse(mgr.get_automation(automation_id).next_run_at) > datetime.now(
        timezone.utc
    )


@pytest.mark.asyncio
async def test_slot_within_grace_fires_exactly_once(
    tmp_path: Path, fired_slots: list[str]
) -> None:
    """A slot just missed (app started late) still fires — but only once."""
    mgr = AutomationManager.open(tmp_path / "auto")
    automation_id = _daily_automation_due(mgr, seconds_ago=MISFIRE_GRACE_SECS - 60)

    for _ in range(6):
        await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]

    assert len(fired_slots) == 1
    assert _parse(mgr.get_automation(automation_id).next_run_at) > datetime.now(
        timezone.utc
    )


@pytest.mark.asyncio
async def test_stale_one_shot_still_fires_and_then_completes(
    tmp_path: Path, fired_slots: list[str]
) -> None:
    """A missed one-shot is irreplaceable, so it catches up however late."""
    mgr = AutomationManager.open(tmp_path / "auto")
    automation_id = _one_shot_due(mgr, seconds_ago=3 * 86400)

    for _ in range(6):
        await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]

    assert len(fired_slots) == 1
    record = mgr.get_automation(automation_id)
    assert record.status is AutomationStatus.COMPLETED
    assert record.next_run_at is None


@pytest.mark.asyncio
async def test_completed_one_shot_cannot_be_resumed(
    tmp_path: Path, fired_slots: list[str]
) -> None:
    """Resuming would leave it active but unschedulable forever."""
    mgr = AutomationManager.open(tmp_path / "auto")
    automation_id = _one_shot_due(mgr, seconds_ago=60)
    await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]
    assert mgr.get_automation(automation_id).status is AutomationStatus.COMPLETED

    with pytest.raises(ValueError, match="already ran"):
        mgr.resume_automation(automation_id)


@pytest.mark.asyncio
async def test_completed_one_shot_cannot_be_revived_via_pause_resume(
    tmp_path: Path, fired_slots: list[str]
) -> None:
    """pause overwrites COMPLETED, so the guard must not trust status alone."""
    mgr = AutomationManager.open(tmp_path / "auto")
    automation_id = _one_shot_due(mgr, seconds_ago=60)
    await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]
    assert mgr.get_automation(automation_id).status is AutomationStatus.COMPLETED

    # Laundering the COMPLETED status through PAUSED must not open a hole.
    mgr.pause_automation(automation_id)
    with pytest.raises(ValueError, match="already ran"):
        mgr.resume_automation(automation_id)


@pytest.mark.asyncio
async def test_exhausted_one_shot_can_be_resumed_when_given_a_cron_schedule(
    tmp_path: Path, fired_slots: list[str]
) -> None:
    """Resuming while switching to a recurring schedule is legitimate."""
    mgr = AutomationManager.open(tmp_path / "auto")
    automation_id = _one_shot_due(mgr, seconds_ago=60)
    await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]
    assert mgr.get_automation(automation_id).status is AutomationStatus.COMPLETED

    revived = mgr.update_automation(
        automation_id,
        UpdateAutomationRequest(
            status=AutomationStatus.ACTIVE, schedule="0 9 * * *"
        ),
    )
    assert revived.status is AutomationStatus.ACTIVE
    assert revived.next_run_at is not None  # re-armed to the next cron slot


@pytest.mark.asyncio
async def test_pausing_keeps_the_one_shot_target_time(tmp_path: Path) -> None:
    """Pausing must not destroy the time the user asked for."""
    mgr = AutomationManager.open(tmp_path / "auto")
    run_at = datetime.now(timezone.utc) + timedelta(days=1)
    created = mgr.create_automation(
        CreateAutomationRequest(name="n", prompt="p", run_at=run_at.isoformat())
    )
    paused = mgr.pause_automation(created.id)
    assert paused.next_run_at == created.next_run_at
    resumed = mgr.resume_automation(created.id)
    assert resumed.next_run_at == created.next_run_at


def test_naive_run_at_is_read_in_the_job_timezone(tmp_path: Path) -> None:
    mgr = AutomationManager.open(tmp_path / "auto")
    record = mgr.create_automation(
        CreateAutomationRequest(
            name="n",
            prompt="p",
            run_at="2026-08-05T09:00:00",
            timezone="Asia/Shanghai",
        )
    )
    assert record.next_run_at is not None
    # 09:00 Shanghai == 01:00 UTC
    assert _parse(record.next_run_at) == datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_corrupt_record_does_not_stall_the_tick(
    tmp_path: Path, fired_slots: list[str]
) -> None:
    """One garbage .json beside a healthy job must not stop scheduling."""
    mgr = AutomationManager.open(tmp_path / "auto")
    healthy_id = _daily_automation_due(mgr, seconds_ago=MISFIRE_GRACE_SECS - 60)
    # A half-written / hand-broken file lands in the same dir.
    (mgr.automations_dir / "broken.json").write_text("{ not json", encoding="utf-8")

    records = mgr.list_automations()
    assert [r.id for r in records] == [healthy_id]  # broken one dropped

    await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]
    assert len(fired_slots) == 1  # healthy job still fired


@pytest.mark.asyncio
async def test_reconcile_forwards_thread_manager_for_notify(
    tmp_path: Path,
) -> None:
    """mode=notify delivery on the scheduler path must reach the thread manager.

    Regression: reconcile_run_statuses used to call try_deliver_completed_run
    without thread_manager, so notify could only log — never append a notice.
    """
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.tools.automation import AutomationRunRecord
    from deepseek_tui.tools.task import TaskStatus

    mgr = AutomationManager.open(tmp_path / "auto")
    created = mgr.create_automation(
        CreateAutomationRequest(
            name="notify-job",
            prompt="p",
            schedule="0 9 * * *",
            delivery={"mode": "notify", "thread_id": "th-1"},
        )
    )
    # A run already enqueued (RUNNING, linked to a task) awaiting reconcile.
    run = AutomationRunRecord(
        id="run-1",
        automation_id=created.id,
        scheduled_for=created.next_run_at or "2026-08-05T01:00:00+00:00",
        status=AutomationRunStatus.RUNNING,
        created_at=datetime.now(timezone.utc).isoformat(),
        task_id="task-1",
    )
    mgr.save_run(run)

    thread_manager = MagicMock()
    thread_manager.append_automation_notice = AsyncMock()
    mgr.thread_manager = thread_manager

    task = MagicMock()
    task.status = TaskStatus.COMPLETED
    task.result_summary = "# Report\n\nAll good."
    task.thread_id = "th-1"
    task.turn_id = None
    task.started_at = None
    task.ended_at = None
    task_manager = MagicMock()
    task_manager.get_task = AsyncMock(return_value=task)

    await mgr.reconcile_run_statuses(task_manager)

    thread_manager.append_automation_notice.assert_awaited_once()
    assert thread_manager.append_automation_notice.await_args.args[0] == "th-1"


def _parse(value: str | None) -> datetime:
    assert value is not None
    return datetime.fromisoformat(value)
