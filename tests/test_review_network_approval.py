"""Actual localhost HTTP runs through the engine's network approval bridge."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from deepseek_tui.engine.handle import ApprovalHandler
from deepseek_tui.policy.network import Decision, NetworkPolicy, NetworkPolicyDecider
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools import web
from deepseek_tui.tools.approval import ApprovalDecision
from deepseek_tui.tools.registry import ToolError
from tests.test_audit_tool_pipeline import _engine


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [False, True])
async def test_network_prompt_uses_real_approval_before_http(tmp_path, monkeypatch, approved):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"actual response")

        def log_message(self, *args):
            pass

    class Handler(ApprovalHandler):
        requests = []

        async def request_approval(self, call_id, request):
            self.requests.append(request)
            return ApprovalDecision.APPROVED if approved else ApprovalDecision.DENIED

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    # Only the test receiver bypasses the independent SSRF guard.
    monkeypatch.setattr(web, "_reject_private_fetch_url", lambda url: None)
    engine, _ = await _engine(tmp_path, [])
    handler = Handler()
    engine.approval_handler = handler
    engine.exec_policy.approval_policy = "on-request"
    policy = NetworkPolicyDecider(
        NetworkPolicy(default=Decision.PROMPT), audit_path=tmp_path / "network.jsonl"
    )
    engine.tool_context.network_policy = policy
    url = f"http://127.0.0.1:{server.server_port}/doc.txt"
    try:
        catalog = await engine._get_tools_with_mcp()
        call = ToolCall(id="fetch", name="fetch_url", arguments={"url": url})
        if approved:
            result = await engine._execute_single_tool(call, catalog, "test")
            assert "actual response" in result.content
            await engine._execute_single_tool(call, catalog, "test")
            assert len(received) == 2
            assert len(handler.requests) == 1
        else:
            with pytest.raises(ToolError, match="not authorized"):
                await engine._execute_single_tool(call, catalog, "test")
            assert received == []
        assert handler.requests[0].force_prompt
        assert "127.0.0.1" in handler.requests[0].reason
    finally:
        await engine.shutdown_session()
        server.shutdown()
        server.server_close()
        worker.join()
