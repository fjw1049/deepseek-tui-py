"""AutomationManager + scheduler + tools wiring tests.

Covers:

* Rust ``parse_rrule`` parity (5 ``#[test]`` translations)
* ``next_after`` boundaries (HOURLY w/ BYDAY, WEEKLY day-roll, INTERVAL=0 reject)
* Persistence round-trip + schema-version guard
* CRUD: ``create_automation`` / ``update_automation`` / ``delete_automation``
  removes runs subdir / pause+resume re-arms ``next_run_at``
* ``scheduler_tick`` idempotency (same ``scheduled_for`` not re-fired)
* ``reconcile_run_statuses`` propagates Task → Run state and writes
  ``last_run_at``
* 8 tools dispatch + ``REQUIRES_APPROVAL`` capability
* End-to-end: ``create_tool_runtime(features.automations=True)`` wires
  manager into context and starts scheduler task
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.tools.automation_manager import (
    CURRENT_AUTOMATION_SCHEMA_VERSION,
    CURRENT_RUN_SCHEMA_VERSION,
    AutomationManager,
    AutomationRecord,
    AutomationRunRecord,
    AutomationRunStatus,
    AutomationSchedule,
    AutomationStatus,
    CreateAutomationRequest,
    UpdateAutomationRequest,
    default_automations_dir,
    validate_name_and_prompt,
)

# ── RRULE parser parity (Rust automation_manager.rs:857-896) ──────────


class TestParseRrule:
    """Mirror Rust ``#[test]`` cases ``parses_hourly_rrule`` /
    ``parses_weekly_rrule`` / ``rejects_invalid_rrule_fields``."""

    def test_parses_hourly_rrule(self) -> None:
        s = AutomationSchedule.parse_rrule("FREQ=HOURLY;INTERVAL=2;BYDAY=MO,TU")
        assert s.is_hourly
        assert s.payload.interval_hours == 2
        assert s.payload.byday is not None
        assert len(s.payload.byday) == 2

    def test_parses_weekly_rrule(self) -> None:
        s = AutomationSchedule.parse_rrule(
            "FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=9;BYMINUTE=30"
        )
        assert s.is_weekly
        assert len(s.payload.byday) == 2
        assert s.payload.byhour == 9
        assert s.payload.byminute == 30

    def test_rejects_invalid_rrule_fields(self) -> None:
        with pytest.raises(ValueError, match="Unsupported RRULE field"):
            AutomationSchedule.parse_rrule("FREQ=WEEKLY;BYSECOND=5")

    # ── Python boundary cases ──

    def test_rrule_case_insensitive(self) -> None:
        s = AutomationSchedule.parse_rrule(
            "freq=hourly;interval=3;byday=mo"
        )
        assert s.is_hourly
        assert s.payload.interval_hours == 3

    def test_hourly_default_interval_is_1(self) -> None:
        s = AutomationSchedule.parse_rrule("FREQ=HOURLY")
        assert s.payload.interval_hours == 1
        assert s.payload.byday is None

    def test_hourly_interval_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="INTERVAL must be >= 1"):
            AutomationSchedule.parse_rrule("FREQ=HOURLY;INTERVAL=0")

    def test_weekly_byhour_overflow_rejected(self) -> None:
        with pytest.raises(ValueError, match="BYHOUR must be between 0 and 23"):
            AutomationSchedule.parse_rrule(
                "FREQ=WEEKLY;BYDAY=MO;BYHOUR=24;BYMINUTE=0"
            )

    def test_weekly_byminute_overflow_rejected(self) -> None:
        with pytest.raises(ValueError, match="BYMINUTE must be between 0 and 59"):
            AutomationSchedule.parse_rrule(
                "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=60"
            )

    def test_weekly_missing_byday_rejected(self) -> None:
        with pytest.raises(ValueError, match="WEEKLY schedules require BYDAY"):
            AutomationSchedule.parse_rrule("FREQ=WEEKLY;BYHOUR=9;BYMINUTE=0")

    def test_weekly_empty_byday_rejected(self) -> None:
        # An empty BYDAY value should be rejected even if the field is
        # present — split on ',' yields a single empty token, which the
        # parser treats as "Invalid BYDAY value ''".
        with pytest.raises(ValueError):
            AutomationSchedule.parse_rrule(
                "FREQ=WEEKLY;BYDAY=;BYHOUR=9;BYMINUTE=0"
            )

    def test_invalid_byday_token_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid BYDAY value"):
            AutomationSchedule.parse_rrule("FREQ=HOURLY;BYDAY=XX")

    def test_unsupported_freq_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported RRULE FREQ"):
            AutomationSchedule.parse_rrule("FREQ=DAILY")

    def test_missing_freq_rejected(self) -> None:
        with pytest.raises(ValueError, match="RRULE must include FREQ"):
            AutomationSchedule.parse_rrule("INTERVAL=1")


# ── next_after boundaries ────────────────────────────────────────────


class TestNextAfter:
    def test_hourly_no_byday_advances_one_hour(self) -> None:
        s = AutomationSchedule.parse_rrule("FREQ=HOURLY;INTERVAL=1")
        now = datetime(2026, 5, 15, 12, 30, 45, tzinfo=timezone.utc)
        nxt = s.next_after(now)
        # The Rust impl strips seconds before adding INTERVAL hours.
        assert nxt > now
        assert (nxt - now) <= timedelta(hours=1, minutes=30)
        assert nxt.second == 0
        assert nxt.microsecond == 0

    def test_hourly_byday_filter_rolls_to_match(self) -> None:
        # Sunday → next BYDAY=MO match must land on Monday.
        sunday = datetime(2026, 5, 17, 23, 0, tzinfo=timezone.utc)
        s = AutomationSchedule.parse_rrule(
            "FREQ=HOURLY;INTERVAL=1;BYDAY=MO"
        )
        nxt = s.next_after(sunday)
        assert nxt.astimezone().weekday() == 0  # Monday

    def test_weekly_advances_to_next_byday_at_byhour(self) -> None:
        s = AutomationSchedule.parse_rrule(
            "FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=9;BYMINUTE=30"
        )
        # 2026-05-15 is a Friday in real life; we just need a stable
        # baseline that is *not* MO/WE for the first match check.
        baseline = datetime(2026, 5, 15, 8, 0, tzinfo=timezone.utc)
        nxt = s.next_after(baseline)
        assert nxt > baseline
        # Output must land on Monday or Wednesday in local time.
        assert nxt.astimezone().weekday() in (0, 2)
        assert nxt.astimezone().hour == 9
        assert nxt.astimezone().minute == 30

    def test_next_after_requires_aware_datetime(self) -> None:
        s = AutomationSchedule.parse_rrule("FREQ=HOURLY")
        with pytest.raises(ValueError, match="must be timezone-aware"):
            s.next_after(datetime(2026, 5, 15, 9, 0))


# ── Validation + helpers ─────────────────────────────────────────────


class TestValidation:
    def test_name_required(self) -> None:
        with pytest.raises(ValueError, match="name is required"):
            validate_name_and_prompt("   ", "do thing")

    def test_prompt_required(self) -> None:
        with pytest.raises(ValueError, match="prompt is required"):
            validate_name_and_prompt("name", "")


class TestDefaultLocation:
    def test_env_override_used(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_AUTOMATIONS_DIR", str(tmp_path / "custom"))
        assert default_automations_dir() == tmp_path / "custom"

    def test_default_location_falls_back_to_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEEPSEEK_AUTOMATIONS_DIR", raising=False)
        result = default_automations_dir()
        assert result.name == "automations"
        assert ".deepseek" in result.parts


# ── Manager CRUD + persistence ───────────────────────────────────────


@pytest.fixture
def manager(tmp_path: Path) -> AutomationManager:
    return AutomationManager.open(tmp_path)


class TestManagerCrud:
    def test_create_writes_json_and_arms_next_run(
        self, manager: AutomationManager, tmp_path: Path
    ) -> None:
        record = manager.create_automation(
            CreateAutomationRequest(
                name="weekly review",
                prompt="summarize changes",
                rrule="FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0",
            )
        )
        assert record.status is AutomationStatus.ACTIVE
        assert record.next_run_at is not None
        on_disk = tmp_path / "automations" / f"{record.id}.json"
        assert on_disk.is_file()
        payload = json.loads(on_disk.read_text())
        assert payload["schema_version"] == CURRENT_AUTOMATION_SCHEMA_VERSION
        assert payload["name"] == "weekly review"
        assert payload["rrule"] == "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0"

    def test_create_paused_skips_next_run(self, manager: AutomationManager) -> None:
        record = manager.create_automation(
            CreateAutomationRequest(
                name="pending",
                prompt="hi",
                rrule="FREQ=HOURLY",
                status=AutomationStatus.PAUSED,
            )
        )
        assert record.status is AutomationStatus.PAUSED
        assert record.next_run_at is None

    def test_create_validates_empty_name(self, manager: AutomationManager) -> None:
        with pytest.raises(ValueError):
            manager.create_automation(
                CreateAutomationRequest(name="  ", prompt="x", rrule="FREQ=HOURLY")
            )

    def test_get_unknown_raises(self, manager: AutomationManager) -> None:
        with pytest.raises(KeyError):
            manager.get_automation("nope")

    def test_list_sorts_by_updated_at_desc(
        self, manager: AutomationManager
    ) -> None:
        a = manager.create_automation(
            CreateAutomationRequest(name="a", prompt="x", rrule="FREQ=HOURLY")
        )
        # Force a > 0 second gap by mutating updated_at directly via update.
        manager.update_automation(a.id, UpdateAutomationRequest(name="a-updated"))
        b = manager.create_automation(
            CreateAutomationRequest(name="b", prompt="y", rrule="FREQ=HOURLY")
        )
        listed = manager.list_automations()
        # Most recently updated first.
        assert listed[0].id == b.id
        # The whole set is present.
        assert {r.id for r in listed} == {a.id, b.id}

    def test_update_rrule_recomputes_next_run(
        self, manager: AutomationManager
    ) -> None:
        record = manager.create_automation(
            CreateAutomationRequest(
                name="x", prompt="x", rrule="FREQ=HOURLY;INTERVAL=1"
            )
        )
        first_next = record.next_run_at
        # Switch to a far-future weekly schedule — the next_run_at should
        # change, proving the recompute path ran.
        updated = manager.update_automation(
            record.id,
            UpdateAutomationRequest(
                rrule="FREQ=WEEKLY;BYDAY=MO;BYHOUR=23;BYMINUTE=59"
            ),
        )
        assert updated.next_run_at != first_next
        assert updated.rrule == "FREQ=WEEKLY;BYDAY=MO;BYHOUR=23;BYMINUTE=59"

    def test_pause_clears_next_run_resume_arms_it(
        self, manager: AutomationManager
    ) -> None:
        record = manager.create_automation(
            CreateAutomationRequest(name="x", prompt="x", rrule="FREQ=HOURLY")
        )
        assert record.next_run_at is not None
        paused = manager.pause_automation(record.id)
        assert paused.status is AutomationStatus.PAUSED
        assert paused.next_run_at is None
        resumed = manager.resume_automation(record.id)
        assert resumed.status is AutomationStatus.ACTIVE
        assert resumed.next_run_at is not None

    def test_delete_also_wipes_runs_subdir(
        self, manager: AutomationManager
    ) -> None:
        """Mirror Rust ``deletes_automation_and_runs`` (898-933)."""
        record = manager.create_automation(
            CreateAutomationRequest(name="x", prompt="x", rrule="FREQ=HOURLY")
        )
        # Plant a run record so we can check the dir is wiped.
        run = AutomationRunRecord(
            id="run1",
            automation_id=record.id,
            scheduled_for="2026-05-15T00:00:00+00:00",
            status=AutomationRunStatus.QUEUED,
            created_at="2026-05-15T00:00:00+00:00",
        )
        manager.save_run(run)
        runs_dir = manager.runs_dir / record.id
        assert runs_dir.exists()
        manager.delete_automation(record.id)
        assert not (manager.automations_dir / f"{record.id}.json").exists()
        assert not runs_dir.exists()

    def test_load_rejects_future_schema_version(
        self, manager: AutomationManager, tmp_path: Path
    ) -> None:
        # Hand-write a record with an unknown future schema version.
        bad_path = manager.automations_dir / "bad.json"
        bad_path.write_text(
            json.dumps(
                {
                    "schema_version": CURRENT_AUTOMATION_SCHEMA_VERSION + 1,
                    "id": "bad",
                    "name": "x",
                    "prompt": "x",
                    "rrule": "FREQ=HOURLY",
                    "cwds": [],
                    "status": "active",
                    "created_at": "2026-05-15T00:00:00+00:00",
                    "updated_at": "2026-05-15T00:00:00+00:00",
                    "next_run_at": None,
                    "last_run_at": None,
                }
            )
        )
        with pytest.raises(ValueError, match="newer than supported"):
            manager.get_automation("bad")


# ── scheduler_tick + reconcile ───────────────────────────────────────


class _FakeTask:
    def __init__(
        self,
        task_id: str,
        status: Any,
        started_at: str | None = None,
        ended_at: str | None = None,
        error: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        self.id = task_id
        self.status = status
        self.started_at = started_at
        self.ended_at = ended_at
        self.error = error
        self.thread_id = thread_id
        self.turn_id = turn_id


class _FakeTaskManager:
    """Just enough TaskManager surface for the manager to call into."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.next_id = 0
        self.tasks: dict[str, _FakeTask] = {}

    async def add_task(self, req: Any) -> _FakeTask:
        self.added.append(req)
        self.next_id += 1
        from deepseek_tui.tools.task_manager import TaskStatus

        task = _FakeTask(
            task_id=f"t_{self.next_id}",
            status=TaskStatus.QUEUED,
            thread_id=f"thread_{self.next_id}",
        )
        self.tasks[task.id] = task
        return task

    async def get_task(self, task_id: str) -> _FakeTask:
        return self.tasks[task_id]


class TestScheduler:
    @pytest.mark.asyncio
    async def test_scheduler_tick_fires_due_automations(
        self, manager: AutomationManager
    ) -> None:
        record = manager.create_automation(
            CreateAutomationRequest(name="x", prompt="x", rrule="FREQ=HOURLY")
        )
        # Force next_run_at into the past so the tick fires it.
        record.next_run_at = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        manager.save_automation(record)

        fake = _FakeTaskManager()
        await manager.scheduler_tick(fake)  # type: ignore[arg-type]

        # add_task was called with our prompt.
        assert len(fake.added) == 1
        assert fake.added[0].prompt == "x"
        # A run was saved + linked to the task_id.
        runs = manager.list_runs(record.id)
        assert len(runs) == 1
        assert runs[0].task_id == "t_1"
        assert runs[0].status is AutomationRunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_scheduler_tick_idempotent_for_same_slot(
        self, manager: AutomationManager
    ) -> None:
        """Mirror Rust idempotency guard (automation_manager.rs:638-650)."""
        record = manager.create_automation(
            CreateAutomationRequest(name="x", prompt="x", rrule="FREQ=HOURLY")
        )
        slot = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        record.next_run_at = slot
        manager.save_automation(record)

        # Pre-populate a run for that slot — tick should NOT enqueue
        # another task.
        existing = AutomationRunRecord(
            id="r1",
            automation_id=record.id,
            scheduled_for=slot,
            status=AutomationRunStatus.QUEUED,
            created_at=slot,
        )
        manager.save_run(existing)

        fake = _FakeTaskManager()
        await manager.scheduler_tick(fake)  # type: ignore[arg-type]
        assert fake.added == []
        # And next_run_at must have advanced past the duplicate slot.
        latest = manager.get_automation(record.id)
        assert latest.next_run_at != slot

    @pytest.mark.asyncio
    async def test_scheduler_tick_skips_paused(
        self, manager: AutomationManager
    ) -> None:
        record = manager.create_automation(
            CreateAutomationRequest(
                name="x",
                prompt="x",
                rrule="FREQ=HOURLY",
                status=AutomationStatus.PAUSED,
            )
        )
        assert record.status is AutomationStatus.PAUSED
        fake = _FakeTaskManager()
        await manager.scheduler_tick(fake)  # type: ignore[arg-type]
        assert fake.added == []

    @pytest.mark.asyncio
    async def test_reconcile_completed_writes_last_run(
        self, manager: AutomationManager
    ) -> None:
        from deepseek_tui.tools.task_manager import TaskStatus

        record = manager.create_automation(
            CreateAutomationRequest(name="x", prompt="x", rrule="FREQ=HOURLY")
        )
        # Plant a Running run linked to a fake task we'll mark Completed.
        run = AutomationRunRecord(
            id="r1",
            automation_id=record.id,
            scheduled_for="2026-05-15T00:00:00+00:00",
            status=AutomationRunStatus.RUNNING,
            created_at="2026-05-15T00:00:00+00:00",
            task_id="t_42",
        )
        manager.save_run(run)

        fake = _FakeTaskManager()
        fake.tasks["t_42"] = _FakeTask(
            task_id="t_42",
            status=TaskStatus.COMPLETED,
            started_at="2026-05-15T00:01:00+00:00",
            ended_at="2026-05-15T00:02:00+00:00",
        )
        await manager.reconcile_run_statuses(fake)  # type: ignore[arg-type]

        runs = manager.list_runs(record.id)
        assert runs[0].status is AutomationRunStatus.COMPLETED
        assert runs[0].ended_at == "2026-05-15T00:02:00+00:00"

        latest = manager.get_automation(record.id)
        assert latest.last_run_at == "2026-05-15T00:02:00+00:00"

    @pytest.mark.asyncio
    async def test_reconcile_failed_propagates_error(
        self, manager: AutomationManager
    ) -> None:
        from deepseek_tui.tools.task_manager import TaskStatus

        record = manager.create_automation(
            CreateAutomationRequest(name="x", prompt="x", rrule="FREQ=HOURLY")
        )
        run = AutomationRunRecord(
            id="r1",
            automation_id=record.id,
            scheduled_for="2026-05-15T00:00:00+00:00",
            status=AutomationRunStatus.RUNNING,
            created_at="2026-05-15T00:00:00+00:00",
            task_id="t_1",
        )
        manager.save_run(run)

        fake = _FakeTaskManager()
        fake.tasks["t_1"] = _FakeTask(
            task_id="t_1",
            status=TaskStatus.FAILED,
            error="boom",
            ended_at="2026-05-15T00:03:00+00:00",
        )
        await manager.reconcile_run_statuses(fake)  # type: ignore[arg-type]

        runs = manager.list_runs(record.id)
        assert runs[0].status is AutomationRunStatus.FAILED
        assert runs[0].error == "boom"


# ── run_now ─────────────────────────────────────────────────────────


class TestRunNow:
    @pytest.mark.asyncio
    async def test_run_now_enqueues_task_immediately(
        self, manager: AutomationManager
    ) -> None:
        record = manager.create_automation(
            CreateAutomationRequest(name="x", prompt="hello", rrule="FREQ=HOURLY")
        )
        fake = _FakeTaskManager()
        run = await manager.run_now(record.id, fake)  # type: ignore[arg-type]
        assert run.task_id == "t_1"
        assert run.status is AutomationRunStatus.RUNNING
        assert fake.added[0].prompt == "hello"


# ── Tools layer ─────────────────────────────────────────────────────


class TestAutomationToolsLayer:
    """8 tool dispatchers + capability/schema sanity."""

    @pytest.mark.asyncio
    async def test_tools_without_manager_attached_error_clearly(
        self, tmp_path: Path
    ) -> None:
        from deepseek_tui.tools.automation_tools import AutomationListTool
        from deepseek_tui.tools.base import ToolError
        from deepseek_tui.tools.context import ToolContext

        ctx = ToolContext(working_directory=tmp_path)
        with pytest.raises(ToolError, match="AutomationManager is not attached"):
            await AutomationListTool().execute({}, ctx)

    @pytest.mark.asyncio
    async def test_create_then_list_then_read_then_delete(
        self, manager: AutomationManager, tmp_path: Path
    ) -> None:
        from deepseek_tui.tools.automation_tools import (
            AUTOMATION_MANAGER_KEY,
            AutomationCreateTool,
            AutomationDeleteTool,
            AutomationListTool,
            AutomationReadTool,
        )
        from deepseek_tui.tools.context import ToolContext

        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={AUTOMATION_MANAGER_KEY: manager},
        )

        created = await AutomationCreateTool().execute(
            {"name": "x", "prompt": "hello", "rrule": "FREQ=HOURLY"}, ctx
        )
        assert created.success
        automation_id = created.metadata["automation"]["id"]

        listed = await AutomationListTool().execute({}, ctx)
        assert listed.success
        assert listed.metadata["count"] == 1

        read = await AutomationReadTool().execute(
            {"automation_id": automation_id}, ctx
        )
        assert read.success
        assert read.metadata["automation"]["name"] == "x"

        deleted = await AutomationDeleteTool().execute(
            {"automation_id": automation_id}, ctx
        )
        assert deleted.success
        assert deleted.metadata["automation_id"] == automation_id

    def test_create_tool_demands_approval(self) -> None:
        from deepseek_tui.tools.automation_tools import AutomationCreateTool
        from deepseek_tui.tools.base import (
            ApprovalRequirement,
            ToolCapability,
        )

        tool = AutomationCreateTool()
        assert tool.approval_requirement() is ApprovalRequirement.REQUIRED
        assert ToolCapability.REQUIRES_APPROVAL in tool.capabilities()

    @pytest.mark.asyncio
    async def test_run_tool_requires_task_manager(
        self, manager: AutomationManager, tmp_path: Path
    ) -> None:
        """``automation_run`` needs a TaskManager on context — without
        one, fail loud rather than silently dropping the call."""
        from deepseek_tui.tools.automation_tools import (
            AUTOMATION_MANAGER_KEY,
            AutomationRunTool,
        )
        from deepseek_tui.tools.base import ToolError
        from deepseek_tui.tools.context import ToolContext

        record = manager.create_automation(
            CreateAutomationRequest(
                name="x", prompt="x", rrule="FREQ=HOURLY"
            )
        )
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={AUTOMATION_MANAGER_KEY: manager},
        )
        with pytest.raises(ToolError, match="TaskManager is not attached"):
            await AutomationRunTool().execute(
                {"automation_id": record.id}, ctx
            )

    @pytest.mark.asyncio
    async def test_update_tool_dispatches(
        self, manager: AutomationManager, tmp_path: Path
    ) -> None:
        from deepseek_tui.tools.automation_tools import (
            AUTOMATION_MANAGER_KEY,
            AutomationUpdateTool,
        )
        from deepseek_tui.tools.context import ToolContext

        record = manager.create_automation(
            CreateAutomationRequest(name="x", prompt="x", rrule="FREQ=HOURLY")
        )
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={AUTOMATION_MANAGER_KEY: manager},
        )
        result = await AutomationUpdateTool().execute(
            {"automation_id": record.id, "name": "renamed"}, ctx
        )
        assert result.success
        assert result.metadata["automation"]["name"] == "renamed"

    @pytest.mark.asyncio
    async def test_pause_resume_tools_flip_status(
        self, manager: AutomationManager, tmp_path: Path
    ) -> None:
        from deepseek_tui.tools.automation_tools import (
            AUTOMATION_MANAGER_KEY,
            AutomationPauseTool,
            AutomationResumeTool,
        )
        from deepseek_tui.tools.context import ToolContext

        record = manager.create_automation(
            CreateAutomationRequest(name="x", prompt="x", rrule="FREQ=HOURLY")
        )
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={AUTOMATION_MANAGER_KEY: manager},
        )

        paused = await AutomationPauseTool().execute(
            {"automation_id": record.id}, ctx
        )
        assert paused.success
        assert paused.metadata["automation"]["status"] == "paused"

        resumed = await AutomationResumeTool().execute(
            {"automation_id": record.id}, ctx
        )
        assert resumed.success
        assert resumed.metadata["automation"]["status"] == "active"


# ── End-to-end: create_tool_runtime wires everything ────────────────


class TestRuntimeIntegration:
    @pytest.mark.asyncio
    async def test_runtime_attaches_manager_when_flag_on(
        self, tmp_path: Path
    ) -> None:
        from deepseek_tui.config.models import Config
        from deepseek_tui.tools.automation_tools import AUTOMATION_MANAGER_KEY
        from deepseek_tui.tools.runtime import create_tool_runtime

        cfg = Config()
        cfg.features.automations = True
        rt = await create_tool_runtime(
            config=cfg,
            working_directory=tmp_path,
            automation_data_dir=tmp_path / "auto",
            automation_tick_interval_secs=5.0,
        )
        try:
            assert rt.automation_manager is not None
            assert (
                rt.context.metadata.get(AUTOMATION_MANAGER_KEY)
                is rt.automation_manager
            )
            # Scheduler task is alive only when TaskManager is also present
            # (features.tasks defaults to True).
            assert rt._automation_scheduler_task is not None
            assert not rt._automation_scheduler_task.done()
        finally:
            await rt.shutdown()
        # After shutdown, the scheduler task is finished.
        assert rt._automation_scheduler_task is not None
        assert rt._automation_scheduler_task.done()

    @pytest.mark.asyncio
    async def test_runtime_skips_manager_when_flag_off(
        self, tmp_path: Path
    ) -> None:
        from deepseek_tui.config.models import Config
        from deepseek_tui.tools.runtime import create_tool_runtime

        cfg = Config()
        # Default: features.automations is False
        assert cfg.features.automations is False
        rt = await create_tool_runtime(
            config=cfg, working_directory=tmp_path
        )
        try:
            assert rt.automation_manager is None
            assert rt._automation_scheduler_task is None
            # No automation_* tools should be in the registry either.
            registered = [
                s.name()
                for s in rt.registry._tools.values()  # noqa: SLF001
                if s.name().startswith("automation_")
            ]
            assert registered == []
        finally:
            await rt.shutdown()

    @pytest.mark.asyncio
    async def test_automations_requires_tasks_fail_fast(
        self, tmp_path: Path
    ) -> None:
        """``features.automations=True`` without ``features.tasks=True``
        must fail at construction.

        Automations have no executor of their own — every fire ends up
        calling ``TaskManager.add_task``. Mirrors Rust
        ``registry.rs::with_runtime_task_tools`` which registers task +
        automation tools in the same builder method, so the dependency
        is structural rather than runtime-checked.
        """
        from deepseek_tui.config.models import Config
        from deepseek_tui.tools.runtime import create_tool_runtime

        cfg = Config()
        cfg.features.automations = True
        cfg.features.tasks = False  # invalid combo
        with pytest.raises(
            ValueError,
            match="features.automations requires features.tasks=True",
        ):
            await create_tool_runtime(
                config=cfg,
                working_directory=tmp_path,
                automation_data_dir=tmp_path / "auto",
            )

    @pytest.mark.asyncio
    async def test_scheduler_loop_cancels_on_event(
        self, tmp_path: Path
    ) -> None:
        """The scheduler loop must exit promptly when the cancel event
        is set — otherwise shutdown blocks the whole runtime."""
        from deepseek_tui.tools.automation_scheduler import (
            AutomationSchedulerConfig,
            run_scheduler_loop,
        )

        manager = AutomationManager.open(tmp_path / "auto")
        fake_tm = MagicMock()
        fake_tm.get_task = AsyncMock()
        cancel = asyncio.Event()
        task = asyncio.create_task(
            run_scheduler_loop(
                manager,
                fake_tm,
                cancel,
                AutomationSchedulerConfig(tick_interval_secs=5.0),
            )
        )
        # Let the loop reach the wait-for-cancel sleep, then signal.
        await asyncio.sleep(0.05)
        cancel.set()
        await asyncio.wait_for(task, timeout=2.0)
        assert task.done()


# ── AutomationRecord serialization round-trip ───────────────────────


def test_record_round_trip() -> None:
    rec = AutomationRecord(
        id="abc",
        name="weekly",
        prompt="do thing",
        rrule="FREQ=HOURLY",
        cwds=["/tmp"],
        status=AutomationStatus.ACTIVE,
        created_at="2026-05-15T00:00:00+00:00",
        updated_at="2026-05-15T00:00:00+00:00",
        next_run_at="2026-05-15T01:00:00+00:00",
    )
    again = AutomationRecord.from_dict(rec.to_dict())
    assert again == rec


def test_run_record_round_trip() -> None:
    run = AutomationRunRecord(
        id="r1",
        automation_id="a1",
        scheduled_for="2026-05-15T00:00:00+00:00",
        status=AutomationRunStatus.COMPLETED,
        created_at="2026-05-15T00:00:00+00:00",
        ended_at="2026-05-15T00:01:00+00:00",
        task_id="t_1",
    )
    again = AutomationRunRecord.from_dict(run.to_dict())
    assert again == run


def test_run_record_rejects_future_schema() -> None:
    raw = {
        "schema_version": CURRENT_RUN_SCHEMA_VERSION + 1,
        "id": "r",
        "automation_id": "a",
        "scheduled_for": "2026-05-15T00:00:00+00:00",
        "status": "queued",
        "created_at": "2026-05-15T00:00:00+00:00",
    }
    with pytest.raises(ValueError, match="newer than supported"):
        AutomationRunRecord.from_dict(raw)
