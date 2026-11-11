"""Wire-level MCP concurrency and model-context round trips."""

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from deepseek_tui.engine.events import ToolContextEvent
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.protocol.messages import Message, Role
from deepseek_tui.protocol.responses import ToolCall
from tests.contract.test_transcript import dumps, live_engine


@pytest.mark.parametrize("limit", [1, 2])
async def test_real_http_mcp_server_concurrency(limit, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    active = peak = 0
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            nonlocal active, peak
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = request.get("method")
            result = {}
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "local-concurrency", "version": "1"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {"name": "peek", "description": "read", "inputSchema": {"type": "object"}}
                    ]
                }
            elif method == "tools/call":
                with lock:
                    active += 1
                    peak = max(peak, active)
                try:
                    time.sleep(0.1)
                    result = {"content": [{"type": "text", "text": "local result"}]}
                finally:
                    with lock:
                        active -= 1
            elif "id" not in request:
                self.send_response(202)
                self.end_headers()
                return
            body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    manager = McpManager(
        [
            McpServerConfig(
                name="local",
                url=f"http://127.0.0.1:{server.server_port}",
                transport="streamablehttp",
                max_concurrency=limit,
            )
        ]
    )
    try:
        await manager.discover_tools()
        results = await asyncio.gather(*(manager.call_tool("mcp_local_peek", {}) for _ in range(4)))
        assert all(result["content"][0]["text"] == "local result" for result in results)
        assert peak == limit
    finally:
        await manager.stop_all()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        worker.join()


async def test_model_context_event_matches_actual_next_request(tmp_path):
    (tmp_path / "report.txt").write_text("real file contents\n" * 300)
    engine, client = await live_engine(
        tmp_path,
        [
            ToolCall(id="read", name="read_file", arguments={"path": "report.txt", "limit": 2}),
            "done",
        ],
    )
    try:
        await engine._run_conversation([Message.user("read report")], "test", "sys", None)
        contexts = [
            event for event in engine.handle.drain_events() if isinstance(event, ToolContextEvent)
        ]
        shown = [message for message in client.requests[1].messages if message.role is Role.TOOL]
        assert dumps([event.message for event in contexts]) == dumps(shown)
        assert len(contexts) == 1 and contexts[0].tool_call_id == "read"
    finally:
        await engine.shutdown_session()


@pytest.mark.parametrize("content", ["", "  exact\n" + "正文" * 30000])
def test_fallback_reconstruction_uses_recorded_context_verbatim(tmp_path, content):
    from deepseek_tui.server.threads import (
        RuntimeThreadStore,
        RuntimeTurnStatus,
        TurnItemKind,
        TurnItemLifecycleStatus,
        TurnItemRecord,
        TurnRecord,
    )
    from deepseek_tui.server.threads.items import reconstruct_messages_from_turn

    store = RuntimeThreadStore(tmp_path / "threads")
    now = datetime.now(timezone.utc)
    message = Message.tool_result("call", content, is_error=True)
    item = TurnItemRecord(
        id="item",
        turn_id="turn",
        kind=TurnItemKind.TOOL_CALL,
        status=TurnItemLifecycleStatus.FAILED,
        summary="read_file",
        detail="different UI detail",
        metadata={
            "tool_call_id": "call",
            "tool_name": "read_file",
            "model_context": message.model_dump(mode="json"),
        },
    )
    store.save_item(item)
    turn = TurnRecord(
        id="turn",
        thread_id="thread",
        status=RuntimeTurnStatus.FAILED,
        input_summary="read",
        created_at=now,
        item_ids=[item.id],
    )
    restored = reconstruct_messages_from_turn(store, turn)
    assert restored[-1].model_dump(mode="json") == message.model_dump(mode="json")
