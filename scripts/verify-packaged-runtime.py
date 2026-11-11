"""Exercise an installed Python bundle through HTTP and a deterministic local model.

No provider credentials or external messages are used. The actual engine executes
a file tool in a temporary workspace, and its next model request must contain the
tool result. Pass the application's Resources/python-runtime directory.
"""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    manifest = json.loads((runtime / "manifest.json").read_text())
    calls = []

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(request)
            returned = any(m.get("role") == "tool" for m in request["messages"])
            delta = (
                {"content": "PACKAGED_RUNTIME_OK"}
                if returned
                else {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "acceptance-write",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps(
                                    {"path": "acceptance.txt", "content": "真实安装包工具验收\n"}
                                ),
                            },
                        }
                    ]
                }
            )
            chunk = {
                "id": "local-acceptance",
                "object": "chat.completion.chunk",
                "model": "deepseek-chat",
                "created": 0,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": "stop" if returned else "tool_calls",
                    }
                ],
            }
            data = ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="packaged-backend-acceptance-") as temporary:
            root = Path(temporary)
            home, workspace = root / "home", root / "workspace"
            home.mkdir()
            workspace.mkdir()
            (home / "config.toml").write_text(
                'provider = "deepseek"\nmodel = "deepseek-chat"\napi_key = "local-fixture"\n'
                f'base_url = "http://127.0.0.1:{model.server_port}/v1"\n'
                "[features]\nmcp = false\nplugins = false\nautomations = true\n"
                "[cua]\nenabled = false\n"
            )
            (home / "mcp.json").write_text('{"mcpServers": {}}')
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("DEEPSEEK_", "OPENAI_", "ANTHROPIC_", "PYTHON"))
            }
            env.update(
                DEEPSEEK_HOME=str(home),
                DEEPSEEK_CONFIG_PATH=str(home / "config.toml"),
                DEEPSEEK_MCP_CONFIG=str(home / "mcp.json"),
                PYTHONPATH=str(runtime / "site-packages"),
                PYTHONNOUSERSITE="1",
            )

            def request(path, body=None, method=None):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/v1" + path,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={
                        "Authorization": "Bearer acceptance-only",
                        "Content-Type": "application/json",
                    },
                    method=method,
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    return json.load(response)

            with (root / "runtime.log").open("w+") as log:
                child = subprocess.Popen(
                    [
                        str(runtime / manifest["python"]),
                        "-m",
                        "deepseek_tui",
                        "serve",
                        "--http",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--auth-token",
                        "acceptance-only",
                    ],
                    cwd=workspace,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                try:
                    deadline = time.monotonic() + 45
                    while True:
                        try:
                            request("/threads")
                            break
                        except (OSError, ValueError):
                            if child.poll() is not None or time.monotonic() > deadline:
                                log.seek(0)
                                raise RuntimeError(log.read()[-6000:]) from None
                            time.sleep(0.2)
                    automation = request(
                        "/automations",
                        {
                            "name": "local permission acceptance",
                            "prompt": "Read local page",
                            "cwds": [str(workspace)],
                            "status": "paused",
                            "run_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                        },
                    )
                    permission_path = f"/automations/{automation['id']}/permissions"
                    assert not request(permission_path)["allow_browser"]
                    assert request(permission_path, {"allow_browser": True}, "PUT")["allow_browser"]
                    assert request(permission_path)["allow_browser"]
                    request(f"/automations/{automation['id']}", {"prompt": "Changed task"}, "PATCH")
                    assert not request(permission_path)["allow_browser"]
                    request(permission_path, {"allow_browser": True}, "PUT")
                    assert not request(permission_path, {"allow_browser": False}, "PUT")[
                        "allow_browser"
                    ]
                    thread = request(
                        "/threads",
                        {
                            "workspace": str(workspace),
                            "provider": "deepseek",
                            "model": "deepseek-chat",
                            "mode": "agent",
                            "auto_approve": True,
                        },
                    )
                    thread_id = thread["id"]
                    request(
                        f"/threads/{thread_id}/turns",
                        {"prompt": "Write acceptance.txt using write_file.", "auto_approve": True},
                    )
                    deadline = time.monotonic() + 45
                    while True:
                        detail = request(f"/threads/{thread_id}")
                        turn = detail["turns"][-1]
                        if turn["status"] not in ("in_progress", "queued"):
                            break
                        if time.monotonic() > deadline:
                            raise RuntimeError("Turn did not finish")
                        time.sleep(0.2)
                    assert not turn.get("error"), turn
                    assert (workspace / "acceptance.txt").read_text() == "真实安装包工具验收\n", (
                        detail
                    )
                    assert any(m.get("role") == "tool" for c in calls for m in c["messages"]), calls
                    child.terminate()
                    child.wait(timeout=10)
                    child = subprocess.Popen(
                        child.args, cwd=workspace, env=env, stdout=log, stderr=log
                    )
                    deadline = time.monotonic() + 45
                    while True:
                        try:
                            restored = request(f"/threads/{thread_id}")
                            break
                        except OSError:
                            if child.poll() is not None or time.monotonic() > deadline:
                                raise RuntimeError("Bundled runtime failed to restart") from None
                            time.sleep(0.2)
                    assert restored["turns"][-1]["id"] == turn["id"]
                    assert restored["turns"][-1]["status"] == "completed"
                    print(
                        json.dumps(
                            {
                                "platform": manifest["platform"],
                                "arch": manifest["arch"],
                                "outside_checkout": True,
                                "real_http": True,
                                "real_file_tool": True,
                                "model_received_tool_result": True,
                                "automation_permissions_http": True,
                                "history_survives_restart": True,
                                "local_model_requests": len(calls),
                                "paid_model_requests": 0,
                                "turn_status": turn["status"],
                            }
                        )
                    )
                finally:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
    finally:
        model.shutdown()
        model.server_close()


if __name__ == "__main__":
    main()
