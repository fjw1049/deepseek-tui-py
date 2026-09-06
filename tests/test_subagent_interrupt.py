import asyncio
from unittest.mock import AsyncMock

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.config.models import Config
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    StreamToolCallComplete,
    ToolCall,
)
from deepseek_tui.tools.file import ReadFileTool
from deepseek_tui.tools.registry import ToolRegistry, ToolResult
from deepseek_tui.tools.subagent import (
    Mailbox,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentType,
    get_real_subagent_executor,
)


class Client(LLMClient):
    def __init__(self, tools=False, tool_name="read_file"):
        super().__init__(RetryConfig(base_delay=0, max_delay=0))
        self.started = asyncio.Event()
        self.closed = asyncio.Event()
        self.requests = []
        self.tools = tools
        self.tool_name = tool_name

    async def stream_chat_completion(self, request):
        self.requests.append(request.model_copy(deep=True))
        if len(self.requests) == 1:
            self.started.set()
            if self.tools:
                for name in ("first", "second"):
                    yield StreamToolCallComplete(
                        tool_call=ToolCall(
                            id=name,
                            name=self.tool_name,
                            arguments={"path": name, "command": "echo test"},
                        )
                    )
            else:
                try:
                    yield StreamTextDelta(text="INCOMPLETE OLD ANSWER")
                    await asyncio.Event().wait()
                finally:
                    self.closed.set()
        else:
            yield StreamTextDelta(text="### SUMMARY\nFollowed the updated requirement.")
        yield StreamDone()


def manager_for(tmp_path, client):
    mailbox = Mailbox()
    manager = SubAgentManager(
        workspace=tmp_path,
        mailbox=mailbox,
        executor=get_real_subagent_executor(),
        default_model="deepseek-chat",
    )
    manager.attach_loop_runtime(
        SubAgentRuntime(
            manager=manager,
            client=client,
            model="deepseek-chat",
            config=Config(),
            workspace=tmp_path,
            mailbox=mailbox,
            auto_approve=True,
        )
    )
    return manager


async def spawn(manager):
    return await manager.spawn(
        SpawnRequest(
            prompt="Inspect files",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="Inspect files"),
        )
    )


async def test_interrupt_closes_generation_and_continues_without_canceling_agent(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    client = Client()
    manager = manager_for(tmp_path, client)
    try:
        agent = await spawn(manager)
        await asyncio.wait_for(client.started.wait(), 1)
        await manager.send_input(agent.agent_id, "NEW REQUIREMENT", interrupt=True)
        await asyncio.wait_for(client.closed.wait(), 1)
        await manager.wait([agent.agent_id], mode="all", timeout_ms=1000)
        assert len(client.requests) == 2
        next_request = client.requests[1].model_dump_json()
        assert next_request.count("NEW REQUIREMENT") == 1
        assert "INCOMPLETE OLD ANSWER" not in next_request
        assert (await manager.get_result(agent.agent_id)).status.kind.value == "completed"
    finally:
        await manager.shutdown()


async def test_interrupt_during_tool_keeps_result_and_skips_remaining_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    started, finish_tool = asyncio.Event(), asyncio.Event()
    calls = []

    async def execute(name, args, context):
        calls.append(args["path"])
        started.set()
        await finish_tool.wait()
        return ToolResult(success=True, content="RESULT ALREADY PRODUCED")

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.execute = execute
    monkeypatch.setattr(
        "deepseek_tui.tools.registry.build_subagent_registry", lambda *a, **kw: registry
    )
    client = Client(tools=True)
    manager = manager_for(tmp_path, client)
    try:
        agent = await spawn(manager)
        await asyncio.wait_for(started.wait(), 1)
        await manager.send_input(agent.agent_id, "NEW REQUIREMENT", interrupt=True)
        await asyncio.sleep(0)
        assert len(client.requests) == 1
        finish_tool.set()
        await manager.wait([agent.agent_id], mode="all", timeout_ms=1000)
        assert calls == ["first"]
        messages = client.requests[1].model_dump_json()
        assert messages.count("RESULT ALREADY PRODUCED") == 1
        assert "NEW REQUIREMENT" in messages
        assert "Not executed" in messages
        results = [m for m in client.requests[1].messages if m.role.value == "tool"]
        assert len(results) == 2
    finally:
        finish_tool.set()
        await manager.shutdown()


async def test_interrupt_while_awaiting_approval_discards_request_and_never_executes(
    tmp_path, monkeypatch
):
    from deepseek_tui.server.approval import ApprovalBridge, HttpApprovalHandler
    from deepseek_tui.tools.shell import ExecShellTool

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    pending = asyncio.Event()
    registry = ToolRegistry()
    registry.register(ExecShellTool())
    registry.execute = AsyncMock()
    monkeypatch.setattr(
        "deepseek_tui.tools.registry.build_subagent_registry", lambda *a, **kw: registry
    )
    client = Client(tools=True, tool_name="exec_shell")
    manager = manager_for(tmp_path, client)
    bridge = ApprovalBridge()
    runtime = manager._loop_runtime
    runtime.auto_approve = False
    runtime.approval_handler = HttpApprovalHandler(bridge)
    runtime.emit_event = lambda event: pending.set()
    try:
        agent = await spawn(manager)
        await asyncio.wait_for(pending.wait(), 1)
        assert bridge.list_pending()
        await manager.send_input(agent.agent_id, "NEW REQUIREMENT", interrupt=True)
        await manager.wait([agent.agent_id], mode="all", timeout_ms=1000)
        assert not bridge.list_pending()
        registry.execute.assert_not_called()
        assert "NEW REQUIREMENT" in client.requests[1].model_dump_json()
        assert len([m for m in client.requests[1].messages if m.role.value == "tool"]) == 2
    finally:
        await manager.shutdown()
