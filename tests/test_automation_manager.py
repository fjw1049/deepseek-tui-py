"""AutomationManager unit tests (parity subset; no live LLM)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import AsyncMock, MagicMock

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
@pytest.mark.parametrize("change", ["pause", "delete"])
async def test_scheduler_does_not_restore_changed_automation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    mgr = AutomationManager.open(tmp_path / "auto")
    automation_id = _daily_automation_due(mgr, seconds_ago=10)

    async def enqueue(self, automation, run, task_manager):
        if change == "pause":
            self.pause_automation(automation_id)
        else:
            self.delete_automation(automation_id)
        run.status = AutomationRunStatus.QUEUED

    monkeypatch.setattr(AutomationManager, "_enqueue_run_task", enqueue)
    await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]
    if change == "pause":
        assert mgr.get_automation(automation_id).status is AutomationStatus.PAUSED
    else:
        with pytest.raises(KeyError):
            mgr.get_automation(automation_id)
        assert mgr.list_runs(automation_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pause", "delete"])
async def test_run_now_does_not_restore_changed_automation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    mgr = AutomationManager.open(tmp_path / "auto")
    automation_id = _daily_automation_due(mgr, seconds_ago=10)

    async def enqueue(self, automation, run, task_manager):
        if change == "pause":
            self.pause_automation(automation_id)
        else:
            self.delete_automation(automation_id)
        run.status = AutomationRunStatus.QUEUED

    monkeypatch.setattr(AutomationManager, "_enqueue_run_task", enqueue)
    await mgr.run_now(automation_id, task_manager=None)  # type: ignore[arg-type]
    if change == "pause":
        assert mgr.get_automation(automation_id).status is AutomationStatus.PAUSED
    else:
        with pytest.raises(KeyError):
            mgr.get_automation(automation_id)
        assert mgr.list_runs(automation_id) == []


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


def _terminal_run_with_pending_delivery(
    mgr: AutomationManager, automation_id: str, attempts: int
) -> AutomationRunRecord:
    from deepseek_tui.tools.automation import AutomationRunRecord as _R

    run = _R(
        id="run-retry",
        automation_id=automation_id,
        scheduled_for="2026-08-05T01:00:00+00:00",
        status=AutomationRunStatus.COMPLETED,
        created_at="2026-08-05T01:00:00+00:00",
        task_id="task-1",
        delivery_attempts=attempts,
        # delivery_done stays False — a prior tick failed and left it pending.
    )
    mgr.save_run(run)
    return run


def _completed_task_manager() -> MagicMock:
    from deepseek_tui.tools.task import TaskStatus

    task = MagicMock()
    task.status = TaskStatus.COMPLETED
    task.result_summary = "Report body."
    task.thread_id = None
    task.turn_id = None
    task.started_at = None
    task.ended_at = None
    task_manager = MagicMock()
    task_manager.get_task = AsyncMock(return_value=task)
    return task_manager


@pytest.mark.asyncio
async def test_reconcile_retries_pending_delivery_on_later_tick(
    tmp_path: Path,
) -> None:
    """A terminal run with a failed delivery must be retried by reconcile.

    Regression: the retry path in try_deliver_completed_run (best_effort=false,
    delivery_attempts < max) relied on "a later tick" calling it again, but
    reconcile skipped terminal runs entirely — attempts stalled at 1 and the
    message was never delivered.
    """
    from unittest.mock import patch

    mgr = AutomationManager.open(tmp_path / "auto")
    created = mgr.create_automation(
        CreateAutomationRequest(
            name="feishu-job",
            prompt="p",
            schedule="0 9 * * *",
            delivery={"mode": "feishu", "to": "oc_test", "best_effort": False},
        )
    )
    _terminal_run_with_pending_delivery(mgr, created.id, attempts=1)

    deliver = AsyncMock()
    with patch("deepseek_tui.automation.pipeline._FeishuSink.deliver", deliver):
        await mgr.reconcile_run_statuses(_completed_task_manager())

    deliver.assert_awaited_once()
    run = mgr.list_runs(created.id)[0]
    assert run.delivery_done is True


@pytest.mark.asyncio
async def test_reconcile_caps_delivery_retry_attempts(tmp_path: Path) -> None:
    """At the attempts cap the run is closed out instead of retried forever."""
    from unittest.mock import patch

    from deepseek_tui.automation.pipeline import _MAX_DELIVERY_ATTEMPTS

    mgr = AutomationManager.open(tmp_path / "auto")
    created = mgr.create_automation(
        CreateAutomationRequest(
            name="feishu-job",
            prompt="p",
            schedule="0 9 * * *",
            delivery={"mode": "feishu", "to": "oc_test", "best_effort": False},
        )
    )
    _terminal_run_with_pending_delivery(
        mgr, created.id, attempts=_MAX_DELIVERY_ATTEMPTS
    )

    deliver = AsyncMock(side_effect=RuntimeError("feishu down"))
    with patch("deepseek_tui.automation.pipeline._FeishuSink.deliver", deliver):
        await mgr.reconcile_run_statuses(_completed_task_manager())

    deliver.assert_awaited_once()
    run = mgr.list_runs(created.id)[0]
    assert run.delivery_done is True
    assert "delivery failed" in (run.error or "")


@pytest.mark.asyncio
async def test_reconcile_ignores_settled_terminal_runs(tmp_path: Path) -> None:
    """Terminal runs with nothing pending must not re-enter delivery."""
    from unittest.mock import patch

    mgr = AutomationManager.open(tmp_path / "auto")
    created = mgr.create_automation(
        CreateAutomationRequest(
            name="feishu-job",
            prompt="p",
            schedule="0 9 * * *",
            delivery={"mode": "feishu", "to": "oc_test", "best_effort": False},
        )
    )
    run = _terminal_run_with_pending_delivery(mgr, created.id, attempts=1)
    run.delivery_done = True
    mgr.save_run(run)

    deliver = AsyncMock()
    with patch("deepseek_tui.automation.pipeline._FeishuSink.deliver", deliver):
        await mgr.reconcile_run_statuses(_completed_task_manager())

    deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_delivers_http_trigger_runs(tmp_path: Path) -> None:
    """Trigger runs under HTTP_TRIGGER_RUNS_KEY get delivered by reconcile.

    Regression: HTTP-trigger delivery relied on a 600 s poller coroutine that
    silently dropped the message when the task outlived the deadline or the
    server restarted. Persisted trigger runs now ride the reconcile loop.
    """
    from unittest.mock import patch

    from deepseek_tui.tools.automation import (
        HTTP_TRIGGER_RUNS_KEY,
        AutomationRunRecord,
    )

    mgr = AutomationManager.open(tmp_path / "auto")
    mgr.save_run(
        AutomationRunRecord(
            id="trig-1",
            automation_id=HTTP_TRIGGER_RUNS_KEY,
            scheduled_for="2026-08-05T01:00:00+00:00",
            status=AutomationRunStatus.RUNNING,
            created_at="2026-08-05T01:00:00+00:00",
            task_id="task-1",
            delivery={"mode": "feishu", "to": "oc_test", "best_effort": True},
        )
    )

    deliver = AsyncMock()
    with patch("deepseek_tui.automation.pipeline._FeishuSink.deliver", deliver):
        await mgr.reconcile_run_statuses(_completed_task_manager())

    deliver.assert_awaited_once()
    run = mgr.list_runs(HTTP_TRIGGER_RUNS_KEY)[0]
    assert run.status is AutomationRunStatus.COMPLETED
    assert run.delivery_done is True
    # The shadow automation must stay invisible to user listings.
    assert all(a.id != HTTP_TRIGGER_RUNS_KEY for a in mgr.list_automations())


def test_edit_one_shot_preserves_or_explicitly_changes_target(tmp_path: Path) -> None:
    mgr = AutomationManager.open(tmp_path / "auto")
    original = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    updated_time = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    job = mgr.create_automation(CreateAutomationRequest(name="once", prompt="test", run_at=original))
    renamed = mgr.update_automation(job.id, UpdateAutomationRequest(name="renamed"))
    assert renamed.next_run_at == original
    rescheduled = mgr.update_automation(job.id, UpdateAutomationRequest(run_at=updated_time))
    assert rescheduled.schedule is None
    assert rescheduled.next_run_at == updated_time
    with pytest.raises(ValueError, match="not both"):
        mgr.update_automation(job.id, UpdateAutomationRequest(schedule="0 * * * *", run_at=updated_time))


@pytest.mark.asyncio
async def test_job_paused_while_an_earlier_job_enqueues_does_not_fire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tick must not fire from its stale listing of a since-paused job."""
    mgr = AutomationManager.open(tmp_path / "auto")
    later = _daily_automation_due(mgr, seconds_ago=10)
    earlier = mgr.get_automation(_daily_automation_due(mgr, seconds_ago=10))
    earlier.updated_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    mgr.save_automation(earlier)  # newest first, so it is ticked first
    fired: list[str] = []

    async def enqueue(self, automation, run, task_manager):  # type: ignore[no-untyped-def] # noqa: ANN001, ANN202
        fired.append(automation.id)
        if automation.id == earlier.id:
            self.pause_automation(later)  # user clicks pause mid-tick
            await asyncio.sleep(0)
        run.task_id = f"task-{automation.id}"

    monkeypatch.setattr(AutomationManager, "_enqueue_run_task", enqueue)
    await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]
    assert fired == [earlier.id]
    assert mgr.list_runs(later) == []


@pytest.mark.asyncio
async def test_slow_delivery_does_not_hold_up_due_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fired_slots: list[str]
) -> None:
    mgr = AutomationManager.open(tmp_path / "auto")
    job = _daily_automation_due(mgr, seconds_ago=10)
    _terminal_run_with_pending_delivery(mgr, job, attempts=0)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_deliver(*_args: object, **_kwargs: object) -> bool:
        entered.set()
        await release.wait()  # a channel that hangs until its timeout
        return False

    monkeypatch.setattr(
        "deepseek_tui.automation.pipeline.try_deliver_completed_run", slow_deliver
    )
    reconcile = asyncio.create_task(mgr.reconcile_run_statuses(_completed_task_manager()))
    await asyncio.wait_for(entered.wait(), timeout=1)
    await asyncio.wait_for(mgr.scheduler_tick(task_manager=None), timeout=1)  # type: ignore[arg-type]
    assert len(fired_slots) == 1
    release.set()
    await reconcile


@pytest.mark.asyncio
async def test_rescheduling_a_finished_one_shot_reactivates_it(
    tmp_path: Path, fired_slots: list[str]
) -> None:
    mgr = AutomationManager.open(tmp_path / "auto")
    automation_id = _one_shot_due(mgr, seconds_ago=60)
    await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]
    assert mgr.get_automation(automation_id).status is AutomationStatus.COMPLETED

    run_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    # The Workbench form sends no status when only the time changes.
    rescheduled = mgr.update_automation(automation_id, UpdateAutomationRequest(run_at=run_at))
    assert rescheduled.status is AutomationStatus.ACTIVE
    assert rescheduled.next_run_at == run_at


@pytest.mark.asyncio
async def test_unschedulable_record_does_not_stall_the_tick(
    tmp_path: Path, fired_slots: list[str]
) -> None:
    mgr = AutomationManager.open(tmp_path / "auto")
    healthy_id = _daily_automation_due(mgr, seconds_ago=10)
    broken = mgr.get_automation(_daily_automation_due(mgr, seconds_ago=10))
    broken.timezone = "Mars/Olympus"  # e.g. a zone this host's tzdata lacks
    broken.updated_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    mgr.save_automation(broken)  # ticked before the healthy job

    await mgr.scheduler_tick(task_manager=None)  # type: ignore[arg-type]
    assert len(fired_slots) == 1
    assert mgr.list_runs(healthy_id)


@pytest.mark.asyncio
async def test_bad_delivery_config_does_not_stall_reconcile(tmp_path: Path) -> None:
    from unittest.mock import patch

    mgr = AutomationManager.open(tmp_path / "auto")
    healthy = mgr.create_automation(
        CreateAutomationRequest(
            name="ok",
            prompt="p",
            schedule="0 9 * * *",
            delivery={"mode": "feishu", "to": "oc_test"},
        )
    )
    broken = mgr.create_automation(
        CreateAutomationRequest(name="bad", prompt="p", schedule="0 9 * * *")
    )
    broken.delivery = {"mode": "slack"}  # hand-edited, never validated
    broken.updated_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    mgr.save_automation(broken)
    for automation_id in (broken.id, healthy.id):
        _terminal_run_with_pending_delivery(mgr, automation_id, attempts=0)

    deliver = AsyncMock()
    with patch("deepseek_tui.automation.pipeline._FeishuSink.deliver", deliver):
        await mgr.reconcile_run_statuses(_completed_task_manager())
    deliver.assert_awaited_once()
    assert mgr.list_runs(healthy.id)[0].delivery_done


def test_run_history_is_capped_but_keeps_in_flight_runs(tmp_path: Path) -> None:
    from deepseek_tui.tools.automation import MAX_RUNS_PER_AUTOMATION, AutomationRunRecord

    mgr = AutomationManager.open(tmp_path / "auto")
    job = mgr.create_automation(
        CreateAutomationRequest(name="n", prompt="p", schedule="0 9 * * *")
    )
    for i in range(MAX_RUNS_PER_AUTOMATION + 5):
        mgr.save_run(
            AutomationRunRecord(
                id=f"r{i:03}",
                automation_id=job.id,
                scheduled_for="2026-01-01T00:00:00+00:00",
                status=AutomationRunStatus.RUNNING if i == 0 else AutomationRunStatus.COMPLETED,
                created_at=f"2026-01-01T00:{i // 60:02}:{i % 60:02}+00:00",
            )
        )
    mgr.prune_runs(job.id)
    ids = {run.id for run in mgr.list_runs(job.id)}
    assert len(ids) == MAX_RUNS_PER_AUTOMATION + 1
    assert "r000" in ids  # oldest, but still running
    assert "r001" not in ids


@pytest.mark.parametrize(
    ("status", "delivery", "run_delivery", "delivery_done", "thread_id", "written", "keep"),
    [
        (
            AutomationRunStatus.COMPLETED,
            {"mode": "feishu", "to": "chat"},
            None,
            False,
            None,
            False,
            True,
        ),
        (
            AutomationRunStatus.FAILED,
            {"mode": "feishu", "to": "chat"},
            None,
            False,
            None,
            False,
            True,
        ),
        (
            AutomationRunStatus.COMPLETED,
            None,
            {"mode": "feishu", "to": "chat"},
            False,
            None,
            False,
            True,
        ),
        (AutomationRunStatus.COMPLETED, None, None, False, "thread", False, True),
        (AutomationRunStatus.CANCELED, None, None, False, "thread", False, True),
        (AutomationRunStatus.COMPLETED, None, {"mode": "slack"}, False, None, False, True),
        (
            AutomationRunStatus.COMPLETED,
            {"mode": "feishu", "to": "chat"},
            None,
            True,
            "thread",
            True,
            False,
        ),
        (AutomationRunStatus.COMPLETED, None, None, False, None, False, False),
        (
            AutomationRunStatus.COMPLETED,
            {"mode": "feishu", "to": "chat"},
            {"mode": "none"},
            False,
            None,
            False,
            False,
        ),
        (
            AutomationRunStatus.CANCELED,
            {"mode": "feishu", "to": "chat"},
            None,
            False,
            None,
            False,
            False,
        ),
    ],
)
def test_pruning_waits_for_required_postprocessing(
    tmp_path, monkeypatch, status, delivery, run_delivery, delivery_done, thread_id, written, keep
) -> None:
    from deepseek_tui.tools.automation import AutomationRunRecord

    monkeypatch.setattr("deepseek_tui.tools.automation.MAX_RUNS_PER_AUTOMATION", 1)
    mgr = AutomationManager.open(tmp_path / "auto")
    job = mgr.create_automation(
        CreateAutomationRequest(name="test", prompt="p", schedule="0 * * * *", delivery=delivery)
    )
    old = AutomationRunRecord(
        id="old",
        automation_id=job.id,
        scheduled_for="2026-01-01T00:00:00+00:00",
        created_at="2026-01-01T00:00:00+00:00",
        status=status,
        delivery=run_delivery,
        delivery_done=delivery_done,
        conversation_thread_id=thread_id,
        conversation_written=written,
    )
    mgr.save_run(old)
    mgr.save_run(
        AutomationRunRecord(
            id="new",
            automation_id=job.id,
            scheduled_for="2026-01-02T00:00:00+00:00",
            created_at="2026-01-02T00:00:00+00:00",
            status=AutomationRunStatus.RUNNING,
        )
    )
    mgr.prune_runs(job.id)
    assert ("old" in {r.id for r in mgr.list_runs(job.id)}) is keep
    if keep:
        old.delivery_done = True
        old.conversation_written = True
        mgr.save_run(old)
        mgr.prune_runs(job.id)
        assert [r.id for r in mgr.list_runs(job.id)] == ["new"]
