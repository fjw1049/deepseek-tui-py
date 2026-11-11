"""Isolated, credential-free HTTP runtime for the Electron delivery audit."""

import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import uvicorn

from deepseek_tui.config import Config
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.tools.automation import (
    HTTP_TRIGGER_RUNS_KEY,
    AutomationManager,
    AutomationRunRecord,
    AutomationRunStatus,
)

root = Path(sys.argv[1])
manager = AutomationManager.open(root / "automations")
for name in ("received", "retry"):
    manager.save_run(
        AutomationRunRecord(
            id=name,
            automation_id=HTTP_TRIGGER_RUNS_KEY,
            scheduled_for="2026-11-11T00:00:00Z",
            created_at="2026-11-11T00:00:00Z",
            status=AutomationRunStatus.COMPLETED,
            delivery_state="uncertain",
            delivery_snapshot={
                "summary": f"真实界面测试报告 {name}",
                "automation_name": "HTTP trigger",
                "config": {"mode": "notify"},
            },
        )
    )
runtime = AppRuntime(config=Config(), working_directory=root)
# No executors, scheduler or external providers: real API + real journal only.
runtime._tool_runtime = SimpleNamespace(automation_manager=manager)
app = build_fastapi_app(runtime, http_mode=True, insecure_no_auth=True)
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
uvicorn.Server(uvicorn.Config(app, log_level="error")).run(sockets=[listener])
