"""Offline characterization probes; assertions confirm observed defects, not correctness.

Run: PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/automation_probe.py
No network, real credentials, background workers, or user data are used.
"""
import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from deepseek_tui.automation import inbox
from deepseek_tui.automation.delivery import sanitize_delivery_text
from deepseek_tui.automation.pipeline import try_deliver_completed_run
from deepseek_tui.tools.automation import (
    AutomationManager, AutomationRunRecord, AutomationRunStatus,
    AutomationSchedule, CreateAutomationRequest,
)
from deepseek_tui.tools.task import TaskStatus


def task_manager(status=TaskStatus.COMPLETED):
    task = SimpleNamespace(status=status, result_summary="Report", error="Task timed out",
                           thread_id=None, turn_id=None, started_at=None, ended_at=None)
    return SimpleNamespace(get_task=AsyncMock(return_value=task))


def make_run(auto, run_id="r", **kw):
    values = dict(id=run_id, automation_id=auto.id,
                  scheduled_for="2026-09-27T00:00:00+00:00",
                  created_at="2026-09-27T00:00:00+00:00",
                  status=AutomationRunStatus.RUNNING, task_id="task")
    values.update(kw)
    return AutomationRunRecord(**values)


async def main():
    observed = {}
    with tempfile.TemporaryDirectory(prefix="automation-review-") as tmp:
        root = Path(tmp)
        mgr = AutomationManager(root / "main")
        auto = mgr.create_automation(CreateAutomationRequest(
            name="probe", prompt="probe", schedule="0 9 * * *", timezone="UTC",
            delivery={"mode": "feishu", "to": "oc_fake", "best_effort": False}))

        # Model the on-disk state after terminal status was saved but before delivery.
        run = make_run(auto, status=AutomationRunStatus.COMPLETED)
        mgr.save_run(run)
        send = AsyncMock()
        with patch("deepseek_tui.automation.pipeline._FeishuSink.deliver", send):
            await AutomationManager(root / "main").reconcile_run_statuses(task_manager())
        observed["restart_pending_zero_attempts_send_count"] = send.await_count
        assert send.await_count == 0

        run = make_run(auto, "timeout")
        mgr.save_run(run)
        send = AsyncMock()
        with patch("deepseek_tui.automation.pipeline._FeishuSink.deliver", send):
            await mgr.reconcile_run_statuses(task_manager(TaskStatus.TIMED_OUT))
        saved = next(r for r in mgr.list_runs(auto.id) if r.id == "timeout")
        observed["timeout"] = dict(status=saved.status.value, sent=send.await_count,
                                   delivery_done=saved.delivery_done)
        assert saved.status == AutomationRunStatus.FAILED and send.await_count == 0

        for i in range(100):
            mgr.save_run(make_run(auto, f"new-{i}", created_at=f"2026-09-28T00:{i//60:02}:{i%60:02}+00:00",
                                 status=AutomationRunStatus.COMPLETED, delivery_done=True))
        mgr.save_run(make_run(auto, "old-active"))
        tm = task_manager()
        await mgr.reconcile_run_statuses(tm)
        old = next(r for r in mgr.list_runs(auto.id) if r.id == "old-active")
        observed["old_run_after_100_newer"] = old.status.value
        assert old.status == AutomationRunStatus.RUNNING

        async def race_case(locked):
            manager = AutomationManager(root / ("locked" if locked else "unlocked"))
            job = manager.create_automation(CreateAutomationRequest(
                name="race", prompt="p", timezone="UTC",
                run_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()))
            calls = []
            async def enqueue(automation, run, tasks):
                calls.append(run.id)
                await asyncio.sleep(0)  # real digest / task APIs can yield here
                run.task_id = run.id
                run.status = AutomationRunStatus.RUNNING
            manager._enqueue_run_task = enqueue
            lock = asyncio.Lock()
            async def tick():
                if locked:
                    async with lock:
                        await manager.scheduler_tick(None)
                else:
                    await manager.scheduler_tick(None)
            await asyncio.gather(tick(), tick())
            return len(calls), len(manager.list_runs(job.id))
        observed["concurrent_ticks_unlocked"] = await race_case(False)
        observed["concurrent_ticks_shared_lock"] = await race_case(True)
        assert observed["concurrent_ticks_unlocked"] == (2, 2)
        assert observed["concurrent_ticks_shared_lock"] == (1, 1)

        crash_mgr = AutomationManager(root / "enqueue-crash")
        crash_mgr.create_automation(CreateAutomationRequest(
            name="crash", prompt="p", timezone="UTC",
            run_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()))
        tm = SimpleNamespace(add_task=AsyncMock(return_value=SimpleNamespace(id="durable-task")))
        with patch("deepseek_tui.automation.pipeline.build_final_prompt", AsyncMock(return_value="p")):
            with patch.object(crash_mgr, "save_run", side_effect=OSError("simulated disk failure")):
                try:
                    await crash_mgr.scheduler_tick(tm)
                except OSError:
                    pass
            await crash_mgr.scheduler_tick(tm)
        observed["enqueue_then_save_failure_task_count"] = tm.add_task.await_count
        assert tm.add_task.await_count == 2

        # Only a mocked HTTP client; demonstrate cross-app cache reuse.
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"code": 0, "tenant_access_token": "app-A-token", "expire": 7200}
        client = SimpleNamespace(post=AsyncMock(return_value=Response()))
        with patch.dict(inbox._FEISHU_TOKEN_CACHE, {}, clear=True):
            a = await inbox._feishu_tenant_token(client, "https://fake.invalid", "A", "secret-A")
            b = await inbox._feishu_tenant_token(client, "https://fake.invalid", "B", "secret-B")
        observed["token_cache"] = dict(same_token=a == b, requests=client.post.await_count)
        assert a == b and client.post.await_count == 1

        # Unknown delivery mode is treated as successful by the silent sink.
        auto.delivery = {"mode": "feihsu"}
        run = make_run(auto, status=AutomationRunStatus.COMPLETED)
        await try_deliver_completed_run(auto, run, task_manager())
        observed["unknown_mode_delivery_done"] = run.delivery_done
        assert run.delivery_done

        raw = "# 第一部分\n收入增长。\n\n---\n\n# 第二部分\n成本下降。"
        cleaned = sanitize_delivery_text(raw)
        observed["formatter_dropped_first_section"] = "收入增长" not in cleaned
        assert "收入增长" not in cleaned

        accepted = AutomationSchedule.parse("* * * * * *", "UTC")
        observed["six_field_cron_accepted"] = accepted.expr
        assert len(accepted.expr.split()) == 6
    print(json.dumps(observed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
