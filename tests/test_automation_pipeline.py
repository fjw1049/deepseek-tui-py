"""Unit tests for automation pipeline (no scheduler / no live LLM)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from deepseek_tui.automation.delivery import DeliveryNotSent

from deepseek_tui.automation.inbox import (
    _format_email_block,
    _format_feishu_block,
    append_feishu_inbound,
    list_feishu_messages,
)
from deepseek_tui.automation.pipeline import build_final_prompt
from deepseek_tui.automation.delivery import DeliveryConfig, DigestConfig, cron_prompt_prefix
from deepseek_tui.tools.automation import (
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
        "schedule": "0 8 * * *",
        "timezone": "Asia/Shanghai",
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
            schedule="0 * * * *",
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
    from deepseek_tui.automation.pipeline import TRIAGE_RUN, apply_triage

    decision = apply_triage(policy=None, prompt="hello")
    assert decision.action is TRIAGE_RUN


def test_triage_keyword_blocks() -> None:
    from deepseek_tui.automation.pipeline import TRIAGE_DROP, apply_triage

    decision = apply_triage(
        policy="keyword",
        prompt="please spam me",
        metadata={"block_keywords": ["spam"]},
    )
    # Blocked is dropped, not "deferred": nothing is stored to run later.
    assert decision.action == TRIAGE_DROP


def test_triage_unknown_policy_is_an_error_not_a_pass() -> None:
    from deepseek_tui.automation.pipeline import apply_triage

    with pytest.raises(ValueError, match="Unknown triage policy"):
        apply_triage(policy="keywrod", prompt="anything")


@pytest.mark.asyncio
async def test_dropped_trigger_reports_that_nothing_was_queued() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.automation.pipeline import fire_http_trigger

    task_manager = MagicMock()
    task_manager.add_task = AsyncMock()
    outcome = await fire_http_trigger(
        prompt="x", task_manager=task_manager, triage_policy="deny",
    )
    assert outcome["status"] == "dropped"
    assert outcome["queued"] is False
    task_manager.add_task.assert_not_called()


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
    from deepseek_tui.tools.task import STALE_RESTART_ERROR, TaskStatus

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
    from deepseek_tui.tools.task import TaskStatus

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


def _completed_task():  # type: ignore[no-untyped-def]
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.tools.task import TaskStatus

    task = MagicMock()
    task.status = TaskStatus.COMPLETED
    task.result_summary = "# Report\n\nAll good."
    task_manager = MagicMock()
    task_manager.get_task = AsyncMock(return_value=task)
    return task_manager


@pytest.mark.asyncio
async def test_delivery_retries_when_not_best_effort() -> None:
    """A failed send with best_effort=false must retry, not clobber the run."""
    from unittest.mock import AsyncMock, patch

    from deepseek_tui.automation.pipeline import try_deliver_completed_run

    automation = _sample_automation(
        delivery={"mode": "feishu", "to": "oc_test", "best_effort": False}
    )
    run = AutomationRunRecord(
        id="r1",
        automation_id="a1",
        scheduled_for="2026-05-28T08:00:00+00:00",
        status=AutomationRunStatus.COMPLETED,
        created_at="2026-05-28T08:00:00+00:00",
        task_id="task-1",
    )
    task_manager = _completed_task()
    with patch(
        "deepseek_tui.automation.pipeline._FeishuSink.deliver",
        AsyncMock(side_effect=DeliveryNotSent("feishu down")),
    ):
        ok = await try_deliver_completed_run(automation, run, task_manager)

    assert ok is True  # run mutated (attempt counted) → caller persists it
    assert run.delivery_done is False  # will retry next tick
    assert run.delivery_attempts == 1
    assert run.error is None  # task result NOT clobbered while still retrying


@pytest.mark.asyncio
async def test_delivery_gives_up_after_max_attempts() -> None:
    """A permanently-broken channel stops re-hammering after the cap."""
    from unittest.mock import AsyncMock, patch

    from deepseek_tui.automation.pipeline import (
        _MAX_DELIVERY_ATTEMPTS,
        try_deliver_completed_run,
    )

    automation = _sample_automation(
        delivery={"mode": "feishu", "to": "oc_test", "best_effort": False}
    )
    run = AutomationRunRecord(
        id="r1",
        automation_id="a1",
        scheduled_for="2026-05-28T08:00:00+00:00",
        status=AutomationRunStatus.COMPLETED,
        created_at="2026-05-28T08:00:00+00:00",
        task_id="task-1",
        delivery_attempts=_MAX_DELIVERY_ATTEMPTS - 1,
    )
    task_manager = _completed_task()
    with patch(
        "deepseek_tui.automation.pipeline._FeishuSink.deliver",
        AsyncMock(side_effect=DeliveryNotSent("feishu down")),
    ):
        ok = await try_deliver_completed_run(automation, run, task_manager)

    assert ok is True
    assert run.delivery_done is True  # gave up → no more retries
    assert run.delivery_attempts == _MAX_DELIVERY_ATTEMPTS
    assert "delivery failed after" in (run.error or "")


@pytest.mark.asyncio
async def test_exhausted_delivery_keeps_failed_run_execution_error() -> None:
    """Giving up on delivery must not mask why the run itself failed."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from deepseek_tui.automation.pipeline import (
        _MAX_DELIVERY_ATTEMPTS,
        try_deliver_completed_run,
    )

    automation = _sample_automation(
        delivery={"mode": "feishu", "to": "oc_test", "best_effort": False}
    )
    run = AutomationRunRecord(
        id="r1",
        automation_id="a1",
        scheduled_for="2026-05-28T08:00:00+00:00",
        status=AutomationRunStatus.FAILED,
        created_at="2026-05-28T08:00:00+00:00",
        error="Tool crashed while writing the report",
        delivery_attempts=_MAX_DELIVERY_ATTEMPTS - 1,
    )
    with patch(
        "deepseek_tui.automation.pipeline._FeishuSink.deliver",
        AsyncMock(side_effect=DeliveryNotSent("feishu down")),
    ):
        ok = await try_deliver_completed_run(automation, run, MagicMock())

    assert ok is True
    assert run.delivery_done is True
    assert run.delivery_error == "feishu down"
    assert run.error == "Tool crashed while writing the report"


@pytest.mark.asyncio
async def test_best_effort_delivery_failure_is_not_reported_as_sent() -> None:
    from unittest.mock import AsyncMock, patch

    from deepseek_tui.automation.pipeline import try_deliver_completed_run

    automation = _sample_automation(
        delivery={"mode": "feishu", "to": "oc_test", "best_effort": True}
    )
    run = AutomationRunRecord(
        id="r1",
        automation_id="a1",
        scheduled_for="2026-05-28T08:00:00+00:00",
        status=AutomationRunStatus.COMPLETED,
        created_at="2026-05-28T08:00:00+00:00",
        task_id="task-1",
    )
    with patch(
        "deepseek_tui.automation.pipeline._FeishuSink.deliver",
        AsyncMock(side_effect=DeliveryNotSent("bot not in chat")),
    ):
        ok = await try_deliver_completed_run(automation, run, _completed_task())
    assert ok is True
    assert run.delivery_done is True  # one shot, no retry
    assert run.delivery_error == "bot not in chat"
    assert AutomationRunRecord.from_dict(run.to_dict()).delivery_error == "bot not in chat"


@pytest.mark.asyncio
async def test_result_write_to_deleted_chat_stops_retrying() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.automation.pipeline import try_write_run_result

    run = AutomationRunRecord(
        id="r1",
        automation_id="a1",
        scheduled_for="2026-05-28T08:00:00+00:00",
        status=AutomationRunStatus.FAILED,
        created_at="2026-05-28T08:00:00+00:00",
        error="boom",
        conversation_thread_id="thr_gone",
    )
    threads = MagicMock()
    threads.append_automation_result = AsyncMock(side_effect=FileNotFoundError("thr_gone"))
    automation = _sample_automation()

    assert await try_write_run_result(automation, run, MagicMock(), thread_manager=threads)
    assert run.conversation_thread_id is None
    # Nothing left to write, so later reconcile ticks return immediately.
    assert not await try_write_run_result(automation, run, MagicMock(), thread_manager=threads)
    threads.append_automation_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_fire_http_trigger_rejects_bad_delivery_before_enqueue() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.automation.pipeline import fire_http_trigger

    task_manager = MagicMock()
    task_manager.add_task = AsyncMock()
    with pytest.raises(ValueError, match="Unknown delivery mode"):
        await fire_http_trigger(
            prompt="summarize inbox",
            task_manager=task_manager,
            delivery={"mode": "slack"},
        )
    task_manager.add_task.assert_not_awaited()


def test_imap_digest_is_read_only_and_covers_the_local_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deepseek_tui.automation.inbox as inbox

    calls: dict[str, object] = {}
    raw = b"From: a@x.test\r\nSubject: hi\r\nDate: Sun, 18 Oct 2026 09:00:00 +0800\r\n\r\nbody"

    class FakeImap:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def login(self, *_args: object) -> None:
            pass

        def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
            calls["readonly"] = readonly
            return "OK", [b"1"]

        def search(self, _charset: object, criteria: str) -> tuple[str, list[bytes]]:
            calls["search"] = criteria
            return "OK", [b"1"]

        def fetch(self, _num: bytes, spec: str) -> tuple[str, list[object]]:
            calls["fetch"] = spec
            return "OK", [(b"1 (BODY[] {10}", raw)]

        def logout(self) -> None:
            pass

    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", FakeImap)
    # Asia/Shanghai "today" (2026-10-18) is [10-17 16:00, 10-18 16:00) UTC.
    start = datetime(2026, 10, 17, 16, tzinfo=timezone.utc)
    end = datetime(2026, 10, 18, 16, tzinfo=timezone.utc)
    section = {"imap_host": "imap.test", "username": "u", "password": "p"}
    messages = inbox._imap_fetch_sync(section, None, start, end)

    assert calls["readonly"] is True  # must not mark mail as read
    assert calls["fetch"] == "(BODY.PEEK[])"
    assert calls["search"] == '(SINCE "16-Oct-2026" BEFORE "19-Oct-2026")'
    assert [m.subject for m in messages] == ["hi"]


@pytest.mark.asyncio
async def test_trigger_poller_delivers_timed_out_task_as_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.automation import pipeline
    from deepseek_tui.tools.task import TaskStatus

    task = MagicMock(
        status=TaskStatus.TIMED_OUT,
        error="Task timed out after 7200s",
        result_summary=None,
    )
    task_manager = MagicMock()
    task_manager.get_task = AsyncMock(return_value=task)
    sink = MagicMock()
    sink.deliver = AsyncMock()
    monkeypatch.setattr(pipeline, "_sink_for_mode", lambda mode, **_: sink)

    await pipeline.deliver_when_task_completes(
        task_id="task-1",
        task_manager=task_manager,
        delivery={"mode": "notify"},
        label="trigger",
        label_id="t1",
        poll_s=0.01,
        timeout_s=1.0,
    )

    sink.deliver.assert_awaited_once()


def test_cron_prefix_survives_a_bracket_in_the_name() -> None:
    from deepseek_tui.automation.delivery import sanitize_delivery_text

    prefix = cron_prompt_prefix("job1", "日报 [v2]")
    assert sanitize_delivery_text(prefix + "正文") == "正文"


@pytest.mark.asyncio
async def test_delivery_rules_only_when_a_run_is_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_digest(_digest):  # noqa: ANN001
        return ""

    monkeypatch.setattr("deepseek_tui.automation.pipeline.build_digest_block", _no_digest)
    silent = await build_final_prompt(_sample_automation(delivery=None))
    sent = await build_final_prompt(_sample_automation(delivery={"mode": "feishu", "to": "oc_x"}))

    for text in (silent, sent):
        assert "[Unattended run]" in text and "Do not ask questions" in text
        # The real tool list is in the request; the prompt no longer restates it.
        assert "Available tools:" not in text
    assert "sends that final message" not in silent
    assert "sends that final message" in sent


def test_strip_unattended_preamble_restores_the_instruction() -> None:
    from deepseek_tui.automation.delivery import (
        _LEGACY_CRON_PLAYBOOK,
        strip_unattended_preamble,
        unattended_preamble,
    )

    assert strip_unattended_preamble(unattended_preamble(delivery_active=True) + "整理桌面") == "整理桌面"
    assert strip_unattended_preamble(_LEGACY_CRON_PLAYBOOK + "\n\n整理桌面").strip() == "整理桌面"


@pytest.mark.asyncio
async def test_trigger_runs_get_the_unattended_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.automation.pipeline import fire_http_trigger
    from deepseek_tui.tools.task import TaskKind

    task_manager = MagicMock()
    task_manager.add_task = AsyncMock(return_value=MagicMock(id="t1"))
    await fire_http_trigger(prompt="summarize inbox", task_manager=task_manager)
    request = task_manager.add_task.await_args.args[0]
    assert request.kind is TaskKind.TRIGGER
    assert "[Unattended run]" in request.prompt
    assert request.prompt.endswith("summarize inbox")


@pytest.mark.asyncio
async def test_unsettled_inbound_turn_is_not_sent_as_an_answer() -> None:
    from types import SimpleNamespace

    from deepseek_tui.automation.pipeline import wait_thread_turn_text
    from deepseek_tui.utils.user_text import user_text
    from deepseek_tui.server.threads import RuntimeTurnStatus

    store = SimpleNamespace(
        load_turn=lambda _id: SimpleNamespace(status=RuntimeTurnStatus.IN_PROGRESS, error=None),
        list_items_for_turn=lambda _id: [SimpleNamespace(kind=None, detail="我先看看")],
    )
    text = await wait_thread_turn_text(
        SimpleNamespace(store=store), thread_id="th", turn_id="tu", timeout_s=0.05, poll_s=0.01
    )
    assert text == user_text("turn_still_running")


def test_user_facing_copy_follows_the_session_language() -> None:
    from deepseek_tui.automation.delivery import classify_task_error_for_user

    assert classify_task_error_for_user("Task timed out after 900s", "en") == (
        "The task timed out. Narrow its scope or try again later."
    )
    assert classify_task_error_for_user("Task timed out after 900s", "zh") == (
        "任务执行超时。请缩小任务范围或稍后重试。"
    )
    # Every message exists in both languages.
    from deepseek_tui.utils.user_text import _TEXT

    assert _TEXT["zh"].keys() == _TEXT["en"].keys()
