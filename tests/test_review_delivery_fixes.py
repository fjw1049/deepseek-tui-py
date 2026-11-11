"""Real HTTP and persistence regressions for delivery retry and redaction."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.automation import inbox, pipeline
from deepseek_tui.server.runtime import _automation_run_to_dict
from tests.test_delivery_journal import setup_run


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")


@pytest.mark.asyncio
async def test_n1_real_http_retry_uses_repaired_target_and_original_body(tmp_path, monkeypatch):
    manager, automation, run, tasks = setup_run(tmp_path)
    old = "11111111-1111-1111-1111-111111111111"
    automation.delivery["to"] = old
    paths = []
    bodies = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            paths.append(self.path)
            bodies.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(400 if old in self.path else 200)
            self.end_headers()
            self.wfile.write(b'{"errcode":0}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(inbox, "WECOM_WEBHOOK_BASE", f"http://127.0.0.1:{server.server_port}/send")
    try:
        await pipeline.try_deliver_completed_run(automation, run, tasks, save_run=manager.save_run)
        assert run.delivery_state == "pending"
        tasks.get_task.return_value.result_summary = (
            "Later changed result must not replace original delivery"
        )
        automation.delivery["to"] = "22222222-2222-2222-2222-222222222222"
        manager.save_automation(automation)
        manager.save_run(run)
        run = manager.list_runs(automation.id)[0]  # Retry after reloading the journal.
        await pipeline.try_deliver_completed_run(
            manager.get_automation(automation.id), run, tasks, save_run=manager.save_run
        )
        assert len(paths) == 2 and old in paths[0] and "22222222" in paths[1]
        assert run.delivery_state == "sent"
        assert bodies[0] == bodies[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.asyncio
async def test_n2_default_key_absent_from_disk_and_public_serializers(tmp_path, monkeypatch):
    manager, automation, run, tasks = setup_run(tmp_path)
    automation.delivery.pop("to")
    secret = "11111111-FIXTURE-NOT-A-REAL-SECRET"
    monkeypatch.setattr(inbox, "default_wecom_webhook_key_from_config", lambda: secret)
    monkeypatch.setattr(
        pipeline,
        "_sink_for_mode",
        lambda *a, **k: SimpleNamespace(
            deliver=AsyncMock(side_effect=ValueError("invalid response"))
        ),
    )
    await pipeline.try_deliver_completed_run(automation, run, tasks, save_run=manager.save_run)
    manager.save_run(run)
    assert secret not in manager._run_path(automation.id, run.id).read_text()
    assert secret not in json.dumps(_automation_run_to_dict(run))
    assert secret not in json.dumps(manager.pending_delivery_confirmations())
