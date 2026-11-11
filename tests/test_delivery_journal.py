"""Delivery outcome recovery with real disk records and a real HTTP receiver."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.automation import inbox, pipeline
from deepseek_tui.tools.automation import AutomationManager, AutomationRunRecord, AutomationRunStatus, CreateAutomationRequest
from deepseek_tui.tools.task import TaskStatus


def setup_run(tmp_path):
    manager = AutomationManager.open(tmp_path / "automations")
    automation = manager.create_automation(CreateAutomationRequest(name="delivery example", prompt="report", schedule="0 * * * *"))
    automation.delivery = {"mode": "wecom", "to": "12345678-1234-1234-1234-123456789abc", "best_effort": False}
    manager.save_automation(automation)
    run = AutomationRunRecord(id="example", automation_id=automation.id, scheduled_for="2026-11-11T00:00:00Z",
                              status=AutomationRunStatus.COMPLETED, created_at="2026-11-11T00:00:00Z", task_id="task_example")
    manager.save_run(run)
    tasks = SimpleNamespace(get_task=AsyncMock(return_value=SimpleNamespace(status=TaskStatus.COMPLETED, result_summary="Actual report", error=None)))
    return manager, automation, run, tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_response", [True, False])
async def test_real_receiver_is_not_sent_twice_after_uncertain_response(tmp_path, monkeypatch, valid_response):
    manager, automation, run, tasks = setup_run(tmp_path)
    received = []
    states_at_send = []
    paths = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            paths.append(self.path)
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            states_at_send.append(manager.list_runs(automation.id)[0].delivery_state)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"errcode":0}' if valid_response else b"response lost after acceptance")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setattr(inbox, "WECOM_WEBHOOK_BASE", f"http://127.0.0.1:{server.server_port}/send")
    try:
        assert await pipeline.try_deliver_completed_run(automation, run, tasks, save_run=manager.save_run)
        manager.save_run(run)
        restarted = AutomationManager.open(tmp_path / "automations")
        recovered = restarted.list_runs(automation.id)[0]
        assert recovered.delivery_state == ("sent" if valid_response else "uncertain")
        assert recovered.delivery_done is valid_response
        assert not await pipeline.try_deliver_completed_run(automation, recovered, tasks, save_run=restarted.save_run)
        assert states_at_send == ["sending"]
        assert len(received) == 1
        assert "Actual report" in received[0]["text"]["content"]
        if not valid_response:
            # Editing a job or removing its task cannot change a retry's envelope.
            automation.delivery = {"mode": "wecom", "to": "87654321-1234-1234-1234-123456789abc"}
            tasks.get_task.reset_mock()
            tasks.get_task.side_effect = KeyError("task removed after delivery")
            retry = await restarted.resolve_delivery(automation.id, run.id, action="retry")
            await pipeline.try_deliver_completed_run(automation, retry, tasks, save_run=restarted.save_run)
            restarted.save_run(retry)
            assert len(received) == 1
            assert retry.delivery_state == "uncertain"
            assert "target changed" in retry.delivery_error
            automation.delivery["to"] = "12345678-1234-1234-1234-123456789abc"
            retry = await restarted.resolve_delivery(automation.id, run.id, action="retry")
            await pipeline.try_deliver_completed_run(automation, retry, tasks, save_run=restarted.save_run)
            restarted.save_run(retry)
            assert len(received) == 2 and received[1] == received[0]
            assert paths[1] == paths[0]
            tasks.get_task.assert_not_called()
            confirmed = await restarted.resolve_delivery(automation.id, run.id, action="received")
            assert confirmed.delivery_done and confirmed.delivery_state == "sent"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.asyncio
async def test_crash_after_sending_marker_requires_confirmation(tmp_path, monkeypatch):
    manager, automation, run, tasks = setup_run(tmp_path)
    run.delivery_state = "sending"
    manager.save_run(run)
    restarted = AutomationManager.open(tmp_path / "automations")
    sink = AsyncMock()
    monkeypatch.setattr(pipeline, "_sink_for_mode", lambda *args, **kwargs: sink)
    recovered = restarted.list_runs(automation.id)[0]
    assert await pipeline.try_deliver_completed_run(automation, recovered, tasks, save_run=restarted.save_run)
    restarted.save_run(recovered)
    assert recovered.delivery_state == "uncertain"
    sink.deliver.assert_not_called()
    retry = await restarted.resolve_delivery(automation.id, run.id, action="retry")
    assert await pipeline.try_deliver_completed_run(automation, retry, tasks, save_run=restarted.save_run)
    sink.deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_journal_write_failure_prevents_send(tmp_path, monkeypatch):
    manager, automation, run, tasks = setup_run(tmp_path)
    sink = AsyncMock()
    monkeypatch.setattr(pipeline, "_sink_for_mode", lambda *args, **kwargs: sink)

    def disk_full(record):
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        await pipeline.try_deliver_completed_run(automation, run, tasks, save_run=disk_full)
    sink.deliver.assert_not_called()
    assert manager.list_runs(automation.id)[0].delivery_state == "pending"


@pytest.mark.asyncio
async def test_cancel_during_delivery_persists_uncertainty(tmp_path, monkeypatch):
    manager, automation, run, tasks = setup_run(tmp_path)
    sending = asyncio.Event()

    async def deliver(**kwargs):
        sending.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(pipeline, "_sink_for_mode", lambda *args, **kwargs: SimpleNamespace(deliver=deliver))
    job = asyncio.create_task(pipeline.try_deliver_completed_run(automation, run, tasks, save_run=manager.save_run))
    await asyncio.wait_for(sending.wait(), timeout=2)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    recovered = AutomationManager.open(tmp_path / "automations").list_runs(automation.id)[0]
    assert recovered.delivery_state == "uncertain"
    assert not recovered.delivery_done


@pytest.mark.asyncio
async def test_real_explicit_rejection_retries_then_succeeds(tmp_path, monkeypatch):
    manager, automation, run, tasks = setup_run(tmp_path)
    requests = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"errcode":40001,"errmsg":"rejected"}' if len(requests) == 1 else b'{"errcode":0}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setattr(inbox, "WECOM_WEBHOOK_BASE", f"http://127.0.0.1:{server.server_port}/send")
    try:
        await pipeline.try_deliver_completed_run(automation, run, tasks, save_run=manager.save_run)
        manager.save_run(run)
        assert run.delivery_state == "pending" and run.delivery_attempts == 1
        recovered = manager.list_runs(automation.id)[0]
        await pipeline.try_deliver_completed_run(automation, recovered, tasks, save_run=manager.save_run)
        assert recovered.delivery_state == "sent" and recovered.delivery_attempts == 2
        assert len(requests) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.asyncio
async def test_slow_receiver_does_not_block_other_automations(tmp_path, monkeypatch):
    manager, automation, run, tasks = setup_run(tmp_path)
    other = manager.create_automation(CreateAutomationRequest(name="fast report", prompt="report", schedule="0 * * * *"))
    other.delivery = automation.delivery
    manager.save_automation(other)
    async def get_task(task_id):
        return SimpleNamespace(status=TaskStatus.COMPLETED, result_summary=task_id, error=None)

    tasks.get_task = get_task
    manager.save_run(AutomationRunRecord(id="fast", automation_id=other.id, scheduled_for="", created_at="",
                                        status=AutomationRunStatus.RUNNING, task_id="task_fast"))
    manager.save_run(AutomationRunRecord(id="needs_review", automation_id=automation.id, scheduled_for="", created_at="",
                                        status=AutomationRunStatus.COMPLETED, delivery_state="uncertain"))
    # Pin order so the slow channel is always considered first.
    monkeypatch.setattr(manager, "_reconcile_targets", lambda: [automation, other])
    received_fast = threading.Event()
    release_slow = threading.Event()
    states_seen = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            states_seen.append(manager.list_runs(other.id)[0].status)
            if "task_fast" in payload["text"]["content"]:
                received_fast.set()
            else:
                release_slow.wait(5)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"errcode":0}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setattr(inbox, "WECOM_WEBHOOK_BASE", f"http://127.0.0.1:{server.server_port}/send")
    job = asyncio.create_task(manager.reconcile_run_statuses(tasks))
    try:
        assert await asyncio.to_thread(received_fast.wait, 2), "slow receiver blocked the next automation"
        confirmed = await asyncio.wait_for(manager.resolve_delivery(automation.id, "needs_review", action="received"), 1)
        assert confirmed.delivery_done
        assert states_seen and all(state == AutomationRunStatus.COMPLETED for state in states_seen)
    finally:
        release_slow.set()
        await asyncio.wait_for(job, timeout=5)
        server.shutdown()
        server.server_close()
        thread.join()
    assert manager.list_runs(automation.id)[0].delivery_state == "sent"
    assert manager.list_runs(other.id)[0].delivery_state == "sent"
