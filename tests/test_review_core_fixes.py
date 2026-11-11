"""Real IO regressions for the independent review findings."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.automation import pipeline
from deepseek_tui.engine.handle import SendMessageOp
from deepseek_tui.integrations.skills import Skill, SkillRegistry
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.automation import AutomationRunStatus
from deepseek_tui.tools.file import ReadFileTool
from deepseek_tui.tools.knowledge import SkillLoadTool
from deepseek_tui.tools.registry import ToolContext, ToolResult
from deepseek_tui.tools.task import (
    NewTaskRequest,
    TaskExecutionResult,
    TaskManager,
    TaskManagerConfig,
    TaskStatus,
)
from deepseek_tui.tools.task.tools import TaskOutputTool
from tests.test_audit_tool_pipeline import _engine
from tests.test_delivery_journal import setup_run


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")


@pytest.mark.asyncio
async def test_n3_single_worker_rejects_nested_wait_and_runs_queue(tmp_path):
    entered = asyncio.Event()
    proceed = asyncio.Event()
    done = asyncio.Event()
    observed = []
    queued_id = None

    async def execute(task, cancel):
        if task.prompt == "parent":
            entered.set()
            await proceed.wait()
            context = ToolContext(
                working_directory=tmp_path, task_manager=manager, active_task_id=task.id
            )
            from deepseek_tui.tools.registry import ToolError

            with pytest.raises(ToolError, match="running durable task"):
                await TaskOutputTool().execute(
                    {"task_id": queued_id, "block": True, "timeout_ms": 40}, context
                )
            observed.append(("blocked", (await manager.get_task(queued_id)).status))
        else:
            (tmp_path / "child.txt").write_text("done")
            done.set()
        return TaskExecutionResult(summary="done")

    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path), executor=execute
    )
    await manager.start()
    try:
        await manager.add_task(NewTaskRequest(prompt="parent"))
        await asyncio.wait_for(entered.wait(), 2)
        queued_id = (await manager.add_task(NewTaskRequest(prompt="child"))).id
        proceed.set()
        await asyncio.wait_for(done.wait(), 2)
        assert observed == [("blocked", TaskStatus.QUEUED)]
        assert (tmp_path / "child.txt").read_text() == "done"
    finally:
        proceed.set()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_n5_completed_run_read_once(tmp_path, monkeypatch):
    manager, automation, run, tasks = setup_run(tmp_path)
    run.delivery_done = True
    run.delivery_state = "sent"
    manager.save_run(run)
    path = manager._run_path(automation.id, run.id)
    original = Path.read_text
    reads = []

    def traced(self, *args, **kwargs):
        if self == path:
            reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", traced)
    await manager.reconcile_run_statuses(tasks)
    assert len(reads) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["retry", "received"])
async def test_resumed_failed_run_keeps_old_delivery(tmp_path, monkeypatch, action):
    manager, automation, run, tasks = setup_run(tmp_path)
    run.status = AutomationRunStatus.FAILED
    run.delivery_state = "uncertain"
    run.delivery_snapshot = {
        "summary": "OLD FAILED RESULT",
        "automation_name": automation.name,
        "config": automation.delivery.copy(),
    }
    tasks.get_task.return_value.result_summary = "NEW SUCCESS RESULT"
    await manager._reconcile_run(automation, run, tasks, deliver=False)
    assert run.status == AutomationRunStatus.COMPLETED
    archived = next(r for r in manager.list_runs(automation.id) if r.id != run.id)
    assert archived.task_id is None and archived.delivery_state == "uncertain"
    confirmed = await manager.resolve_delivery(automation.id, archived.id, action=action)
    sink = SimpleNamespace(deliver=AsyncMock())
    monkeypatch.setattr(pipeline, "_sink_for_mode", lambda *a, **k: sink)
    await pipeline.try_deliver_completed_run(
        automation, confirmed, tasks, save_run=manager.save_run
    )
    if action == "retry":
        assert sink.deliver.await_args.kwargs["summary"] == "OLD FAILED RESULT"
    else:
        sink.deliver.assert_not_awaited()
        assert confirmed.delivery_done
    await pipeline.try_deliver_completed_run(automation, run, tasks, save_run=manager.save_run)
    assert sink.deliver.await_args.kwargs["summary"] == "NEW SUCCESS RESULT"


@pytest.mark.asyncio
async def test_d2_completed_write_retained_after_failed_turn(tmp_path):
    engine, client = await _engine(
        tmp_path,
        [
            ToolCall(
                id="write", name="write_file", arguments={"path": "done.txt", "content": "done"}
            )
        ],
    )
    engine.max_tool_round_trips = 1
    engine._handle_approval_flow = AsyncMock(return_value=False)
    try:
        await engine._handle_send_message(
            SendMessageOp(content="Write this file and then inspect it")
        )
        assert (tmp_path / "done.txt").read_text() == "done"
        assert "Write this file" in engine.session_messages[0].text_content()
        assert any(
            getattr(b, "tool_use_id", None) == "write"
            for m in engine.session_messages
            for b in m.content
        )
    finally:
        await engine.shutdown_session()


@pytest.mark.asyncio
async def test_d5_loaded_external_skill_grants_only_companion_reads(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    directory = tmp_path / "user-skills" / "example"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("Read companion.txt and references/detail.txt")
    (directory / "companion.txt").write_text("real companion")
    (directory / "references").mkdir()
    (directory / "references" / "detail.txt").write_text("detail")
    skill = Skill(
        name="example",
        description="example",
        body=(directory / "SKILL.md").read_text(),
        path=directory / "SKILL.md",
    )
    context = ToolContext(working_directory=workspace)
    context.metadata["skill_registry"] = SkillRegistry(skills=[skill])
    result = await SkillLoadTool().execute({"name": "example"}, context)
    assert result.success
    assert str(directory / "references") in result.metadata["companion_files"]
    read = await ReadFileTool().execute({"path": str(directory / "companion.txt")}, context)
    assert "real companion" in read.content
    assert not context.check_path(str(directory / "companion.txt"), write=True).allowed


@pytest.mark.asyncio
async def test_d6_mode_change_updates_tools_and_system_prompt(tmp_path):
    engine, client = await _engine(
        tmp_path, [ToolCall(id="exit", name="exit_plan_mode", arguments={}), "Done"]
    )
    engine.configure_interaction_mode("plan")
    modes_prepared = []
    prepare = engine._prepare_cua

    async def track_prepare():
        modes_prepared.append(engine.mode)
        await prepare()

    engine._prepare_cua = track_prepare

    async def accept(call_id):
        await engine.apply_interaction_mode("agent", reason="exit_plan_mode")
        return ToolResult(True, "Plan accepted; implement now")

    engine._handle_exit_plan_mode = accept
    try:
        await engine._handle_send_message(SendMessageOp(content="Plan then do"))
        assert engine.mode == "agent"
        assert modes_prepared == ["plan", "agent"]
        assert client.requests[0].system_prompt != client.requests[1].system_prompt
        assert "write_file" not in {
            (t.get("function") or t)["name"] for t in client.requests[0].tools
        }
        assert "write_file" in {(t.get("function") or t)["name"] for t in client.requests[1].tools}
    finally:
        await engine.shutdown_session()


@pytest.mark.asyncio
async def test_yolo_command_changes_mode(tmp_path):
    from deepseek_tui.tui.commands import cmd_yolo

    engine, client = await _engine(tmp_path, ["ok"])
    engine.configure_interaction_mode("ask")
    app = SimpleNamespace(
        _engine=engine, _interaction_mode="ask", run_worker=lambda coro, **kw: coro.close()
    )
    try:
        result = cmd_yolo("", app)
        assert "yolo" in result.output
        assert engine.mode == "yolo" and app._interaction_mode == "yolo"
    finally:
        await engine.shutdown_session()


@pytest.mark.asyncio
async def test_n4_trusted_mcp_does_not_bypass_agent_never_policy(tmp_path):
    import sys

    from deepseek_tui.config import Config
    from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.mcp.config import McpServerConfig
    from deepseek_tui.mcp.manager import McpManager
    from deepseek_tui.tools.approval import ExecPolicyEngine
    from deepseek_tui.tools.mcp import MCP_MANAGER_KEY
    from tests.test_mcp_e2e_real import FIXTURE_SERVER

    manager = McpManager(
        [McpServerConfig(name="fixture", command=sys.executable, args=[str(FIXTURE_SERVER)])]
    )
    context = ToolContext(working_directory=tmp_path, metadata={MCP_MANAGER_KEY: manager})
    engine = Engine(
        handle=EngineHandle(),
        client=AsyncMock(),
        tool_context=context,
        exec_policy=ExecPolicyEngine(approval_policy="never"),
        approval_handler=AutoApprovalHandler(),
    )
    engine._app_config = Config(mcp_read_only_tools=["mcp_fixture_echo"])
    try:
        engine._mcp_tools_cache = await manager.discover_tools()
        catalog = await engine._get_tools_with_mcp()
        result = await engine._execute_single_tool(
            ToolCall(id="read", name="mcp_fixture_echo", arguments={"message": "audit"}),
            catalog,
            "test",
        )
        assert engine.mode == "agent"
        assert result is None
        engine._app_config.mcp_read_only_tools = []
        result = await engine._execute_single_tool(
            ToolCall(id="read2", name="mcp_fixture_echo", arguments={"message": "audit"}),
            catalog,
            "test",
        )
        assert result is None
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_d11_resampled_tool_event_closed_without_execution(tmp_path):
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.engine.events import ToolCallEvent, ToolResultEvent
    from deepseek_tui.protocol.responses import (
        StreamDone,
        StreamError,
        StreamTextDelta,
        StreamToolCallComplete,
    )

    class BrokenThenGood(LLMClient):
        attempts = 0

        async def stream_chat_completion(self, request):
            self.attempts += 1
            if self.attempts == 1:
                yield StreamToolCallComplete(
                    tool_call=ToolCall(
                        id="discarded",
                        name="write_file",
                        arguments={"path": "discarded.txt", "content": "no"},
                    )
                )
                yield StreamError(message="test disconnect", retryable=True)
            else:
                yield StreamTextDelta(text="Recovered without tool")
                yield StreamDone()

    engine, _ = await _engine(tmp_path, [])
    engine.client = BrokenThenGood()
    engine.turn_loop.client = engine.client
    try:
        await engine._handle_send_message(SendMessageOp(content="Inspect this case"))
        events = engine.handle.drain_events()
        assert any(isinstance(e, ToolCallEvent) and e.tool_call.id == "discarded" for e in events)
        assert any(
            isinstance(e, ToolResultEvent)
            and e.tool_call_id == "discarded"
            and e.metadata["not_executed"]
            for e in events
        )
        assert not (tmp_path / "discarded.txt").exists()
    finally:
        await engine.shutdown_session()
