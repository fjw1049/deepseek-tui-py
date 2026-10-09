"""Offline behavioral regressions for audit 06."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from deepseek_tui.client.base import LLMClient, MeteredLLMClient
from deepseek_tui.config.models import Config
from deepseek_tui.engine import Engine
from deepseek_tui.engine.cycle import SessionActivityCoordinator
from deepseek_tui.engine.events import StatusEvent, SubAgentMailboxEvent, ToolResultEvent
from deepseek_tui.engine.handle import CancelRequestOp, EngineHandle
from deepseek_tui.engine.tool_dedup import ToolCallDeduplicator
from deepseek_tui.engine.turn import TurnOutcomeStatus, TurnResult
from deepseek_tui.protocol.messages import Message, MessageRequest
from deepseek_tui.protocol.responses import StreamDone, ToolCall, Usage
from deepseek_tui.tools.registry import ToolResult
from deepseek_tui.tools.runtime import ToolRuntime, create_tool_runtime
from deepseek_tui.tools.subagent import Mailbox, MailboxMessage


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_PLUGINS_DIR", str(tmp_path / "plugins"))


def config():
    cfg = Config()
    for name in ("tasks", "subagents", "mcp", "automations", "plugins", "exec_policy"):
        setattr(cfg.features, name, False)
    return cfg


@pytest.fixture
async def engine(tmp_path):
    engine = await Engine.create(
        handle=EngineHandle(),
        client=AsyncMock(),
        config=config(),
        working_directory=tmp_path,
        max_tool_round_trips=0,
    )
    try:
        yield engine
    finally:
        engine.handle.drain_events()
        await engine.shutdown_session()


async def eventually(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("expected scheduling point not reached")


async def test_queued_messages_do_not_block_cancel_and_keep_order():
    engine = Engine.__new__(Engine)
    engine.handle = EngineHandle()
    engine.default_model = engine._cycle_session_id = "probe"
    engine._activity_coordinator = SimpleNamespace(start=Mock(), stop=AsyncMock())
    started, stopped = [], asyncio.Event()

    async def turn(op):
        started.append(op.content)
        if op.content == "first":
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    engine._handle_send_message = turn
    before = set(asyncio.all_tasks())
    runner = asyncio.create_task(engine.run())
    try:
        await engine.handle.send_message("first")
        await eventually(lambda: started == ["first"])
        await engine.handle.send_message("second")
        await engine.handle.send_message("third")
        await eventually(lambda: engine.handle._op_queue.empty())
        await engine.handle.send_op(CancelRequestOp())
        await asyncio.wait_for(stopped.wait(), 0.5)
        await eventually(lambda: len(started) == 3)
        assert started == ["first", "second", "third"]
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
    assert not [t for t in asyncio.all_tasks() - before if t.get_name() == "engine-next-op"]


async def test_runner_shutdown_reaps_op_waiter(engine):
    entered = asyncio.Event()

    async def turn(op):
        entered.set()
        await asyncio.Event().wait()

    engine._handle_send_message = turn
    before = set(asyncio.all_tasks())
    runner = asyncio.create_task(engine.run())
    try:
        await engine.handle.send_message("first")
        await entered.wait()
        await eventually(
            lambda: any(t.get_name() == "engine-next-op" for t in asyncio.all_tasks() - before)
        )
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
    assert not [t for t in asyncio.all_tasks() - before if t.get_name() == "engine-next-op"]
    await engine.handle.send_message("retained")
    await asyncio.sleep(0)
    assert (await engine.handle.next_op()).content == "retained"


async def test_mailbox_transfer_retries_and_activity_returns_to_idle(monkeypatch):
    handle, mailbox = EngineHandle(), Mailbox()
    for _ in range(4096):
        assert handle.try_emit(StatusEvent(message="full"))
    mailbox.send(MailboxMessage.completed("agent_probe", "done"))
    count = [1]
    manager = SimpleNamespace(mailbox=mailbox, running_count=lambda: count[0])
    stub = SimpleNamespace(
        tool_context=SimpleNamespace(subagent_manager=manager, task_manager=None), tool_runtime=None
    )
    coordinator = SessionActivityCoordinator(stub, handle.try_emit)
    monkeypatch.setattr("deepseek_tui.engine.cycle.PollIntervalSecs", 0.001)
    coordinator.start()
    try:
        await eventually(lambda: bool(coordinator._pending_mailbox))
        handle.drain_events()
        await asyncio.sleep(0.02)
        events = handle.drain_events()
        assert sum(isinstance(e, SubAgentMailboxEvent) for e in events) == 1
        assert coordinator._last_subagents == 1
        count[0] = 0
        coordinator._emit_activity_snapshot()
        assert handle.drain_events()[0].running_subagents == 0
    finally:
        await coordinator.stop()


async def test_write_and_dynamic_tools_are_not_reused(engine):
    state = {"content": "old", "writes": 0}

    async def execute(call, *args):
        if call.name == "exec_shell":
            state["writes"] += 1
            state["content"] = "new"
        return ToolResult(content=state["content"], success=True)

    engine._execute_single_tool = execute
    calls = [
        ToolCall(id=str(i), name=name, arguments={"path": "x"})
        for i, name in enumerate(("read_file", "exec_shell", "exec_shell", "read_file"))
    ]
    results = await engine._execute_tool_calls(calls)
    assert state["writes"] == 2
    assert "new" in results[-1].content[0].content
    dedup = ToolCallDeduplicator()
    first = dedup.classify("task_output", {"id": "x"})
    dedup.record(first.key, "running", is_error=False)
    assert dedup.classify("task_output", {"id": "x"}).kind == "execute"


def test_failed_reads_and_hooked_reads_are_not_cached():
    dedup = ToolCallDeduplicator()
    first = dedup.classify("read_file", {"path": "x"})
    dedup.record(first.key, "failed", is_error=True)
    assert dedup.classify("read_file", {"path": "x"}).kind == "execute"
    dedup.record(first.key, "ok", is_error=False)
    assert dedup.classify("read_file", {"path": "x"}).kind == "reuse"
    assert dedup.classify("read_file", {"path": "x"}, allow_reuse=False).kind == "execute"


async def test_late_usage_stays_with_origin_and_session_is_counted_once(engine):
    ledger = engine.turn_usage_ledger
    ledger.reset("old")
    old = ledger.capture()
    entered, release = asyncio.Event(), asyncio.Event()

    class Client(LLMClient):
        async def stream_chat_completion(self, request):
            entered.set()
            await release.wait()
            yield StreamDone(usage=Usage(input_tokens=7, output_tokens=3))

    client = MeteredLLMClient(Client(), ledger)

    async def child():
        for _ in range(2):
            async for event in client.stream_chat_completion(
                MessageRequest(model="deepseek-chat", messages=[])
            ):
                pass

    task = asyncio.create_task(child())
    await entered.wait()
    ledger.reset("new")
    release.set()
    await task
    assert ledger.totals()["output_tokens"] == 0
    assert old.totals()["output_tokens"] == 6
    assert {item.turn_id for item in old.items} == {"old"}
    assert engine.session_cost_usd == old.totals()["cost_usd"]


async def test_runtime_factory_rolls_back_on_later_failure(tmp_path):
    cfg = config()
    cfg.features.tasks = True
    manager = SimpleNamespace(start=AsyncMock(), shutdown=AsyncMock())
    with (
        patch("deepseek_tui.tools.runtime.TaskManager", return_value=manager),
        patch(
            "deepseek_tui.tools.runtime.build_subagent_manager", side_effect=ValueError("startup")
        ),
    ):
        with pytest.raises(ValueError, match="startup"):
            await create_tool_runtime(config=cfg, working_directory=tmp_path)
    manager.shutdown.assert_awaited_once()


async def test_runtime_shutdown_continues_after_failure():
    child = SimpleNamespace(shutdown=AsyncMock(side_effect=RuntimeError("close")))
    task = SimpleNamespace(shutdown=AsyncMock())
    borrowed = SimpleNamespace(stop_all=AsyncMock())
    runtime = ToolRuntime(
        context=None,
        registry=None,
        task_manager=task,
        subagent_manager=child,
        mailbox=None,
        mcp_manager=borrowed,
        lsp_manager=None,
        _owns_mcp_manager=False,
    )
    with pytest.raises(RuntimeError, match="close"):
        await runtime.shutdown()
    task.shutdown.assert_awaited_once()
    borrowed.stop_all.assert_not_awaited()


async def test_engine_factory_rolls_back_runtime_on_skill_failure(tmp_path):
    runtime = Mock(shutdown=AsyncMock())
    with (
        patch("deepseek_tui.tools.runtime.create_tool_runtime", AsyncMock(return_value=runtime)),
        patch(
            "deepseek_tui.integrations.skills.discover_in_workspace",
            side_effect=ValueError("skills"),
        ),
    ):
        with pytest.raises(ValueError, match="skills"):
            await Engine.create(
                handle=EngineHandle(),
                client=AsyncMock(),
                config=config(),
                working_directory=tmp_path,
            )
    runtime.shutdown.assert_awaited_once()


async def test_round_limit_is_failed_and_retains_partial_result(engine):
    engine.turn_loop = SimpleNamespace(
        run=AsyncMock(
            return_value=TurnResult(
                assistant_message=Message.assistant("partial"),
                tool_calls=[ToolCall(id="probe", name="read_file", arguments={"path": "x"})],
            )
        )
    )
    engine._execute_tool_calls = AsyncMock(return_value=[Message.tool_result("probe", "ok")])
    result = await engine._run_conversation([Message.user("probe")], "deepseek-chat", "probe", 64)
    assert result.outcome is TurnOutcomeStatus.FAILED
    assert result.error_message == "Tool round-trip limit exceeded"
    assert result.tool_round_count == 1
    assert result.assistant_message.text_content() == "partial"


async def test_parallel_completion_is_visible_before_slow_peer_and_context_stays_ordered(engine):
    release, fast = asyncio.Event(), asyncio.Event()

    async def execute(call, *args):
        if call.id == "slow":
            await release.wait()
        else:
            fast.set()
        return ToolResult(content=call.id, success=True)

    engine._execute_single_tool = execute
    calls = [
        ToolCall(id=name, name="read_file", arguments={"path": name}) for name in ("slow", "fast")
    ]
    pending = asyncio.create_task(engine._execute_tools_parallel(calls, [], "deepseek-chat"))
    try:
        await fast.wait()
        await eventually(lambda: not engine.handle._event_queue.empty())
        events = engine.handle.drain_events()
        assert [e.tool_call_id for e in events if isinstance(e, ToolResultEvent)] == ["fast"]
        assert not pending.done()
        release.set()
        results = await pending
        assert [m.content[0].tool_use_id for m in results] == ["slow", "fast"]
        assert [
            e.tool_call_id for e in engine.handle.drain_events() if isinstance(e, ToolResultEvent)
        ] == ["slow"]
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


async def test_owned_runtime_is_closed_but_borrowed_runtime_is_not(engine, tmp_path):
    owned = engine.tool_runtime
    with patch.object(type(owned), "shutdown", AsyncMock()) as shutdown:
        await engine.shutdown_session()
        shutdown.assert_awaited_once()
        borrowed_engine = await Engine.create(
            handle=EngineHandle(),
            client=AsyncMock(),
            config=config(),
            working_directory=tmp_path,
            tool_runtime=owned,
        )
        await borrowed_engine.shutdown_session()
        shutdown.assert_awaited_once()


async def test_factory_cancellation_still_closes_started_manager(tmp_path):
    entered = asyncio.Event()

    async def start():
        entered.set()
        await asyncio.Event().wait()

    manager = SimpleNamespace(start=start, shutdown=AsyncMock())
    cfg = config()
    cfg.features.tasks = True
    with patch("deepseek_tui.tools.runtime.TaskManager", return_value=manager):
        task = asyncio.create_task(create_tool_runtime(config=cfg, working_directory=tmp_path))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    manager.shutdown.assert_awaited_once()


async def test_cancel_during_startup_event_stops_activity_coordinator(engine):
    for _ in range(4096):
        engine.handle.try_emit(StatusEvent(message="full"))
    runner = asyncio.create_task(engine.run())
    await asyncio.sleep(0)
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert engine._activity_coordinator._task is None


async def test_browser_input_is_not_written_to_tool_start_logs(engine, caplog):
    import logging

    engine._execute_single_tool = AsyncMock(return_value=ToolResult(True, "filled"))
    with caplog.at_level(logging.INFO, logger="deepseek_tui.engine.orchestrator.tooling"):
        await engine._execute_tool_calls([
            ToolCall(id="browser-secret", name="browser_use", arguments={
                "action": "fill", "selector": "#password", "text": "private-password-123"
            })
        ])
    assert "browser arguments redacted" in caplog.text
    assert "private-password-123" not in caplog.text
    engine._execute_single_tool.assert_awaited_once()
