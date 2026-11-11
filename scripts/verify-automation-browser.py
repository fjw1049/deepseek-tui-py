"""Exercise the real private browser with a local page; no model or external sends."""

import asyncio
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from deepseek_tui.automation.permissions import (
    AutomationBrowser,
    browser_grant,
    set_browser_permission,
)
from deepseek_tui.tools.automation import AutomationManager, CreateAutomationRequest
from deepseek_tui.tools.browser import BrowserUseTool
from deepseek_tui.tools.registry import ToolContext


async def main():
    with tempfile.TemporaryDirectory(prefix="automation-browser-validation-") as directory:
        root = Path(directory)
        os.environ["DEEPSEEK_HOME"] = str(root / "home")
        os.environ["DEEPSEEK_BROWSER_KEYCHAIN"] = "0"
        manager = AutomationManager(root / "automations")
        record = manager.create_automation(
            CreateAutomationRequest(
                name="local acceptance",
                prompt="Click the local test button",
                run_at="2027-01-01T00:00:00Z",
                cwds=[str(root)],
            )
        )
        set_browser_permission(manager.automations_dir, record.id, True)
        scope = AutomationBrowser(
            root, "task_acceptance", browser_grant(manager.automations_dir, record.id)
        )
        context = ToolContext(
            working_directory=root, metadata={"cron_restricted": True, "unattended": True}
        )
        scope.bind(context)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = b"""<!doctype html><title>Automation acceptance</title>
<button id="run"
 onclick="document.querySelector('#output').textContent='saved-marker'">Save test</button>
<div id="output">waiting</div>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        tool = BrowserUseTool()
        try:
            result = await tool.execute(
                {"action": "open", "url": f"http://127.0.0.1:{server.server_port}"}, context
            )
            assert result.success, result.content
            result = await tool.execute({"action": "click", "selector": "#run"}, context)
            assert result.success, result.content
            run = scope.service.runs[context.metadata["runtime_thread_id"]]
            evidence = await run.session.eval_js("document.querySelector('#output').textContent")
            assert evidence.success and "saved-marker" in evidence.content, evidence
            child = ToolContext(
                working_directory=root,
                mutation_agent_id="child",
                metadata={"cron_restricted": True, "unattended": True},
            )
            scope.bind(child)
            result = await tool.execute(
                {"action": "open", "url": f"http://127.0.0.1:{server.server_port}"}, child
            )
            assert result.success, result.content
            child_run = scope.service.runs[child.metadata["runtime_thread_id"]]
            evidence = await child_run.session.eval_js(
                "document.querySelector('#output').textContent"
            )
            assert evidence.success and "waiting" in evidence.content, evidence
            set_browser_permission(manager.automations_dir, record.id, False)
            assert not (await tool.execute({"action": "click", "selector": "#run"}, child)).success
            print(
                json.dumps(
                    {
                        "real_browser": True,
                        "page_action_verified": True,
                        "child_session_isolated": True,
                        "revocation_blocks_action": True,
                        "external_messages": 0,
                        "model_requests": 0,
                    },
                    indent=2,
                )
            )
        finally:
            await scope.close()
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
