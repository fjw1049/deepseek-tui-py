"""AutomationManager unit tests (parity subset; no live LLM)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

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


@pytest.mark.asyncio
async def test_parse_rrule_weekly_and_next_after() -> None:
    sched = AutomationSchedule.parse_rrule(
        "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=30"
    )
    assert sched.is_weekly
    from datetime import datetime, timezone

    after = datetime(2026, 5, 25, 0, 0, tzinfo=timezone.utc)
    nxt = sched.next_after(after)
    assert nxt > after


def test_create_list_update_automation(tmp_path: object) -> None:
    root = tmp_path / "auto"  # type: ignore[operator]
    mgr = AutomationManager.open(root)
    created = mgr.create_automation(
        CreateAutomationRequest(
            name="morning",
            prompt="digest",
            rrule="FREQ=HOURLY;INTERVAL=1",
            delivery={"mode": "feishu", "chat_id": "ou_x"},
            digest={"sources": ["feishu:today_local"]},
        )
    )
    assert created.delivery is not None
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
            rrule="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;BYHOUR=9;BYMINUTE=0",
        )
    )
    due = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    record.next_run_at = due.isoformat()
    mgr.save_automation(record)
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


def _parse(value: str | None) -> datetime:
    assert value is not None
    return datetime.fromisoformat(value)
