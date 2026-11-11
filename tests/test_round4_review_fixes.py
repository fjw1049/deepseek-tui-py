"""Regression scenarios for the fourth review, using real stores and transports."""

import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config import Config
from deepseek_tui.engine.events import StatusEvent
from deepseek_tui.engine.handle import ApprovalHandler, EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.policy.network import Decision, NetworkPolicy, NetworkPolicyDecider
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.approval import ApprovalDecision, ExecPolicyEngine
from deepseek_tui.tools.registry import ToolContext, ToolError, build_default_registry
from tests.test_audit_tool_pipeline import _engine
from tests.test_delivery_journal import setup_run
from tests.test_mcp_e2e_real import FIXTURE_SERVER


class RecordingApproval(ApprovalHandler):
    def __init__(self, decision=ApprovalDecision.DENIED):
        self.requests = []
        self.decision = decision

    async def request_approval(self, call_id, request):
        self.requests.append((call_id, request))
        return self.decision


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DEEPSEEK_NOTES_PATH", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")


@pytest.mark.parametrize("policy", ["on-request", "never"])
@pytest.mark.parametrize("mode", ["agent", "ask", "plan"])
async def test_note_read_skips_approval_even_in_shared_agent_registry(tmp_path, policy, mode):
    notes = tmp_path / "notes.txt"
    notes.write_text("Persisted decision", encoding="utf-8")
    handler = RecordingApproval()
    engine = Engine(
        handle=EngineHandle(),
        client=AsyncMock(),
        tool_registry=build_default_registry(Config(), mode="agent"),
        tool_context=ToolContext(working_directory=tmp_path, metadata={"notes_path": notes}),
        exec_policy=ExecPolicyEngine(approval_policy=policy),
        approval_handler=handler,
    )
    engine.mode = mode
    try:
        catalog = await engine._get_tools_with_mcp()
        result = await engine._execute_single_tool(
            ToolCall(id="read", name="note", arguments={"action": "read"}),
            catalog,
            "test",
        )
        assert result is not None and "Persisted decision" in result.content
        assert not handler.requests
        append = ToolCall(id="append", name="note", arguments={"content": "Must not write"})
        if mode == "agent":
            assert await engine._execute_single_tool(append, catalog, "test") is None
            assert len(handler.requests) == (1 if policy == "on-request" else 0)
        else:
            with pytest.raises(ToolError, match="Only reading"):
                await engine._execute_single_tool(append, catalog, "test")
        assert notes.read_text() == "Persisted decision"
    finally:
        await engine.shutdown_session()


@pytest.mark.parametrize("state", ["uncertain", "sending"])
@pytest.mark.parametrize("disable_delivery", [False, True])
async def test_unresolved_delivery_survives_retention_until_confirmed(
    tmp_path, state, disable_delivery
):
    manager, automation, run, _ = setup_run(tmp_path)
    run.created_at = "2026-01-01T00:00:00+00:00"
    run.delivery_state = state
    run.delivery_snapshot = {
        "config": automation.delivery.copy(),
        "summary": "Original send",
        "automation_name": automation.name,
    }
    manager.save_run(run)
    for index in range(100):
        manager.save_run(
            replace(
                run,
                id=f"new_{index}",
                created_at="2026-02-01T00:00:00+00:00",
                delivery_state="sent",
                delivery_done=True,
            )
        )
    if disable_delivery:
        automation.delivery = {"mode": "none"}
        manager.save_automation(automation)
    manager.prune_runs(automation.id)
    assert manager._run_path(automation.id, run.id).exists()
    if state == "uncertain":
        assert any(item["id"] == run.id for item in manager.pending_delivery_confirmations())
    await manager.resolve_delivery(automation.id, run.id, action="received")
    manager.prune_runs(automation.id)
    assert not manager._run_path(automation.id, run.id).exists()


async def test_injected_network_policy_keeps_timeout_escalation(tmp_path, monkeypatch):
    from deepseek_tui.tools import web
    from deepseek_tui.utils.network_escalation import host_timeout_count

    release = threading.Event()
    requests = []

    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            release.wait(3)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setattr(web, "_reject_private_fetch_url", lambda url: None)
    engine, _ = await _engine(tmp_path, [])
    assert engine.tool_context.network_policy is None  # Default runtime stays unchanged.
    handler = RecordingApproval(ApprovalDecision.APPROVED)
    engine.approval_handler = handler
    engine.exec_policy.approval_policy = "on-request"
    monkeypatch.setattr(web, "_DEFAULT_FETCH_TIMEOUT_S", 0.15)
    engine.tool_context.network_policy = NetworkPolicyDecider(
        NetworkPolicy(default=Decision.PROMPT),
        audit_path=tmp_path / "network.jsonl",
    )
    url = f"http://127.0.0.1:{server.server_port}/slow.txt"
    errors = []
    try:
        catalog = await engine._get_tools_with_mcp()
        for index in range(2):
            with pytest.raises(ToolError, match="timed out") as exc:
                await engine._execute_single_tool(
                    ToolCall(id=f"fetch_{index}", name="fetch_url", arguments={"url": url}),
                    catalog,
                    "test",
                )
            errors.append(str(exc.value))
        assert requests == ["/slow.txt", "/slow.txt"]
        assert len(handler.requests) == 1
        assert host_timeout_count(engine.tool_context, url) == 2
        assert "repeatedly" not in errors[0] and "repeatedly" in errors[1]
        assert not engine.tool_context.metadata.get("network_approval")
    finally:
        release.set()
        await engine.shutdown_session()
        server.shutdown()
        server.server_close()
        worker.join()


async def test_file_search_returns_real_matches_after_traversal_deadline(tmp_path, monkeypatch):
    from deepseek_tui.tools import search

    (tmp_path / "first.txt").write_text("first")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "later.txt").write_text("later")
    ticks = iter([0, 0, 10])
    # Override this module's clock, not asyncio's process-wide monotonic clock.
    monkeypatch.setattr(search, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    result = await search.FileSearchTool().execute(
        {"path": ".", "pattern": ".txt"},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success and "first.txt" in result.content
    assert "later.txt" not in result.content
    assert "Search incomplete" in result.content
    assert result.metadata["incomplete"] and result.metadata["truncated"]
    assert not result.metadata["count_is_exact"]


@pytest.mark.parametrize("composite", [False, True])
async def test_mcp_trust_diagnostic_waits_for_real_focus_discovery(tmp_path, composite):
    from deepseek_tui.plugins.runtime import CompositeMcpManager
    from deepseek_tui.tools.mcp import MCP_MANAGER_KEY

    manager = McpManager(
        [
            McpServerConfig(
                name="fixture",
                command=sys.executable,
                args=[str(FIXTURE_SERVER)],
                load_policy="on_focus",
            )
        ]
    )
    view = CompositeMcpManager(manager) if composite else manager
    engine = Engine(
        handle=EngineHandle(),
        client=AsyncMock(),
        tool_context=ToolContext(
            working_directory=tmp_path,
            metadata={MCP_MANAGER_KEY: view},
        ),
    )
    engine._app_config = Config(mcp_read_only_tools=["mcp_fixture_typo"])

    def warnings():
        return [
            event.message
            for event in engine.handle.drain_events()
            if isinstance(event, StatusEvent) and "not discovered" in event.message
        ]

    try:
        await engine._get_tools_with_mcp()
        assert warnings() == []
        await manager.ensure_focus_server_discovered("fixture")
        await engine._get_tools_with_mcp()
        assert len(warnings()) == 1
        await engine._get_tools_with_mcp()
        assert warnings() == []
    finally:
        await manager.stop_all()


async def test_failed_discovery_is_unverified_but_successful_empty_catalog_is_verified(monkeypatch):
    from deepseek_tui.mcp.client import McpError

    manager = McpManager([McpServerConfig(name="fixture", command="unused")])
    client = SimpleNamespace(list_tools=AsyncMock(side_effect=McpError("disconnected")))
    monkeypatch.setattr(manager, "_ensure_client", AsyncMock(return_value=client))
    assert not manager.can_validate_tool_name("mcp_fixture_typo")
    await manager.discover_tools()
    assert not manager.can_validate_tool_name("mcp_fixture_typo")
    assert not manager.can_validate_tool_name("mcp_unknown_typo")
    client.list_tools = AsyncMock(return_value=[])
    await manager._discover_tools_fresh()
    assert manager.can_validate_tool_name("mcp_fixture_typo")
    assert manager.can_validate_tool_name("mcp_unknown_typo")


@pytest.mark.parametrize("adapter", ["anthropic", "chat", "responses"])
def test_cancel_before_first_answer_preserves_users_without_fake_assistant(adapter):
    from deepseek_tui.client.anthropic import _build_anthropic_messages
    from deepseek_tui.client.chat_messages import build_chat_messages
    from deepseek_tui.client.openai_responses import build_responses_input
    from deepseek_tui.engine.history import interrupted_turn_messages
    from deepseek_tui.protocol.messages import Message

    messages = interrupted_turn_messages([Message.user("Earlier interrupted request")], {})
    messages.append(Message.user("Current request"))
    if adapter == "anthropic":
        _, output = _build_anthropic_messages(messages, system_prompt=None)
        assert len(output) == 1
    elif adapter == "chat":
        output = build_chat_messages(messages, model="deepseek-chat")
        assert len(output) == 2
    else:
        output = build_responses_input(messages, model="test-model")
        assert len(output) == 2
    assert {item["role"] for item in output} == {"user"}
    assert "Earlier interrupted request" in str(output) and "Current request" in str(output)
