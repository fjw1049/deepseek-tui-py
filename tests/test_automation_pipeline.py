"""Unit tests for automation pipeline (no scheduler / no live LLM)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from deepseek_tui.automation.inbox import (
    _format_email_block,
    _format_feishu_block,
    append_feishu_inbound,
    list_feishu_messages,
)
from deepseek_tui.automation.pipeline import build_final_prompt
from deepseek_tui.automation.types import DeliveryConfig, DigestConfig, cron_prompt_prefix
from deepseek_tui.tools.automation_manager import (
    AutomationManager,
    AutomationRecord,
    AutomationRunRecord,
    AutomationRunStatus,
    AutomationStatus,
    CreateAutomationRequest,
)


def _sample_automation(**overrides: object) -> AutomationRecord:
    base = {
        "id": "a1",
        "name": "daily-digest",
        "prompt": "Summarize inbox.",
        "rrule": "FREQ=DAILY;BYHOUR=8;BYMINUTE=0",
        "status": AutomationStatus.ACTIVE,
        "created_at": "2026-05-28T00:00:00+00:00",
        "updated_at": "2026-05-28T00:00:00+00:00",
    }
    base.update(overrides)
    return AutomationRecord(**base)  # type: ignore[arg-type]


def test_cron_prefix_matches_openhuman_style() -> None:
    assert cron_prompt_prefix("job-uuid", "morning") == "[cron:job-uuid morning] "


@pytest.mark.asyncio
async def test_build_final_prompt_includes_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_digest(_digest: DigestConfig | None) -> str:
        return "<automation_digest>stub</automation_digest>\n\n"

    monkeypatch.setattr(
        "deepseek_tui.automation.pipeline.build_digest_block",
        _fake_digest,
    )
    auto = _sample_automation()
    text = await build_final_prompt(auto)
    assert text.startswith("[cron:a1 daily-digest] ")
    assert "Summarize inbox." in text


def test_delivery_config_defaults_silent() -> None:
    assert DeliveryConfig.from_mapping(None).is_active() is False
    assert DeliveryConfig.from_mapping({"mode": "feishu", "chat_id": "ou_x"}).is_active()


def test_automation_record_round_trip_optional_fields(tmp_path: object) -> None:
    root = tmp_path / "automations"  # type: ignore[operator]
    mgr = AutomationManager.open(root)
    record = mgr.create_automation(
        CreateAutomationRequest(
            name="t",
            prompt="p",
            rrule="FREQ=HOURLY;INTERVAL=1",
        )
    )
    record.delivery = {"mode": "feishu", "chat_id": "ou_test", "best_effort": True}
    record.digest = {"sources": ["email:yesterday_local"]}
    mgr.save_automation(record)
    loaded = mgr.get_automation(record.id)
    assert loaded.delivery == record.delivery
    assert loaded.digest == record.digest


def test_feishu_inbox_round_trip(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    inbox = tmp_path / "feishu_inbox.jsonl"  # type: ignore[operator]
    monkeypatch.setattr("deepseek_tui.automation.inbox.feishu_inbox_path", lambda: inbox)
    append_feishu_inbound(
        text="hello",
        sender_id="u1",
        sender_name="Alice",
        chat_id="chat-1",
        received_at=datetime.now(timezone.utc),
    )
    rows = list_feishu_messages("today_local")
    assert len(rows) == 1
    assert rows[0].sender == "Alice"
    assert "hello" in rows[0].snippet


def test_format_blocks_empty() -> None:
    assert "none" in _format_email_block("yesterday_local", []).lower()
    assert "none" in _format_feishu_block("today_local", []).lower()


def test_triage_skip_runs_by_default() -> None:
    from deepseek_tui.automation.triage import TRIAGE_RUN, apply_triage

    decision = apply_triage(policy=None, prompt="hello")
    assert decision.action is TRIAGE_RUN


def test_triage_keyword_blocks() -> None:
    from deepseek_tui.automation.triage import TRIAGE_DEFER, apply_triage

    decision = apply_triage(
        policy="keyword",
        prompt="please spam me",
        metadata={"block_keywords": ["spam"]},
    )
    assert decision.action is TRIAGE_DEFER


@pytest.mark.asyncio
async def test_fire_http_trigger_enqueues_task() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.automation.pipeline import fire_http_trigger

    task = MagicMock()
    task.id = "task-99"
    task_manager = MagicMock()
    task_manager.add_task = AsyncMock(return_value=task)

    outcome = await fire_http_trigger(
        prompt="summarize inbox",
        task_manager=task_manager,
        triage_policy="skip",
    )
    assert outcome["status"] == "enqueued"
    assert outcome["task_id"] == "task-99"
    task_manager.add_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_try_deliver_skips_without_active_delivery() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.automation.pipeline import try_deliver_completed_run

    automation = _sample_automation()
    run = AutomationRunRecord(
        id="r1",
        automation_id="a1",
        scheduled_for="2026-05-28T08:00:00+00:00",
        status=AutomationRunStatus.COMPLETED,
        created_at="2026-05-28T08:00:00+00:00",
        task_id="task-1",
    )
    task_manager = MagicMock()
    task_manager.get_task = AsyncMock()
    assert await try_deliver_completed_run(automation, run, task_manager) is False
    assert run.delivery_done is False


@pytest.mark.asyncio
async def test_try_deliver_skips_stale_restart_failure() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from deepseek_tui.automation.pipeline import try_deliver_completed_run
    from deepseek_tui.tools.task_manager import STALE_RESTART_ERROR, TaskStatus

    automation = _sample_automation(
        delivery={"mode": "feishu", "to": "oc_test", "best_effort": True}
    )
    run = AutomationRunRecord(
        id="r-stale",
        automation_id="a1",
        scheduled_for="2026-05-28T08:00:00+00:00",
        status=AutomationRunStatus.FAILED,
        created_at="2026-05-28T08:00:00+00:00",
        task_id="task-stale",
        error=STALE_RESTART_ERROR,
    )
    task = MagicMock()
    task.status = TaskStatus.FAILED
    task.error = STALE_RESTART_ERROR
    task.result_summary = None
    task_manager = MagicMock()
    task_manager.get_task = AsyncMock(return_value=task)
    deliver = AsyncMock()
    with patch(
        "deepseek_tui.automation.pipeline._FeishuSink.deliver",
        deliver,
    ):
        ok = await try_deliver_completed_run(automation, run, task_manager)
    assert ok is True
    assert run.delivery_done is True
    deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_try_deliver_failed_run_notifies() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from deepseek_tui.automation.pipeline import try_deliver_completed_run
    from deepseek_tui.tools.task_manager import TaskStatus

    automation = _sample_automation(
        delivery={"mode": "feishu", "to": "oc_test", "best_effort": True}
    )
    run = AutomationRunRecord(
        id="r1",
        automation_id="a1",
        scheduled_for="2026-05-28T08:00:00+00:00",
        status=AutomationRunStatus.FAILED,
        created_at="2026-05-28T08:00:00+00:00",
        task_id="task-1",
        error="Tool round-trip limit exceeded",
    )
    task = MagicMock()
    task.status = TaskStatus.FAILED
    task.error = "Tool round-trip limit exceeded"
    task.result_summary = None
    task_manager = MagicMock()
    task_manager.get_task = AsyncMock(return_value=task)
    deliver = AsyncMock()
    with patch(
        "deepseek_tui.automation.pipeline._FeishuSink.deliver",
        deliver,
    ):
        ok = await try_deliver_completed_run(automation, run, task_manager)
    assert ok is True
    assert run.delivery_done is True
    deliver.assert_awaited_once()
    summary = deliver.await_args.kwargs["summary"]
    assert "Tool round-trip" not in summary
    assert "❌" in summary
