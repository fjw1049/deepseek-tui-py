"""AutomationManager unit tests (parity subset; no live LLM)."""

from __future__ import annotations

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.tools.automation_manager import (
    AutomationManager,
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
