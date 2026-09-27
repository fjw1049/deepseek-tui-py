"""Offline audit-06 baseline probes; assertions describe current defects, not desired behavior."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from deepseek_tui.client.base import LLMClient, MeteredLLMClient
from deepseek_tui.config.models import Config
from deepseek_tui.engine import Engine
from deepseek_tui.engine.cycle import SessionActivityCoordinator
from deepseek_tui.engine.events import StatusEvent, SubAgentMailboxEvent
from deepseek_tui.engine.handle import CancelRequestOp, EngineHandle
from deepseek_tui.engine.tool_dedup import ToolCallDeduplicator
from deepseek_tui.engine.usage_ledger import TurnUsageLedger, usage_source
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, Usage
from deepseek_tui.tools.runtime import ToolRuntime, create_tool_runtime
from deepseek_tui.tools.subagent import Mailbox, MailboxMessage


def bare_engine():
    engine = Engine.__new__(Engine)
    engine.handle = EngineHandle()
    engine.default_model = "probe"
    engine._cycle_session_id = "probe"
    engine._activity_coordinator = SimpleNamespace(start=Mock(), stop=AsyncMock())
    return engine


async def spin_until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("probe did not reach expected scheduling point")


async def op_loop_probe():
    engine = bare_engine()
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def turn(op):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    engine._handle_send_message = turn
    runner = asyncio.create_task(engine.run())
    await engine.handle.send_message("first")
    await entered.wait()
    await engine.handle.send_message("second")
    await spin_until(lambda: engine.handle._op_queue.empty())
    await engine.handle.send_op(CancelRequestOp())
    for _ in range(10):
        await asyncio.sleep(0)
    blocked_cancel = not stopped.is_set() and engine.handle._op_queue.qsize() == 1
    runner.cancel()
    await asyncio.gather(runner, return_exceptions=True)
    assert blocked_cancel

    engine = bare_engine()
    entered.clear()
    engine._handle_send_message = turn
    before = set(asyncio.all_tasks())
    runner = asyncio.create_task(engine.run())
    await engine.handle.send_message("first")
    await entered.wait()
    await spin_until(
        lambda: any(t.get_name() == "engine-next-op" for t in asyncio.all_tasks() - before)
    )
    runner.cancel()
    await asyncio.gather(runner, return_exceptions=True)
    leaked = [t for t in asyncio.all_tasks() - before if t.get_name() == "engine-next-op"]
    await engine.handle.send_message("after restart")
    await asyncio.sleep(0)
    stolen = engine.handle._op_queue.empty()
    for task in leaked:
        task.cancel()
    await asyncio.gather(*leaked, return_exceptions=True)
    assert len(leaked) == 1 and stolen
    return {
        "queued_cancel_blocked_by_second_send": blocked_cancel,
        "orphan_op_waiters": len(leaked),
        "orphan_consumed_next_message": stolen,
    }


async def downstream_events_probe():
    handle, mailbox = EngineHandle(), Mailbox()
    for _ in range(4096):
        assert handle.try_emit(StatusEvent(message="fill"))
    mailbox.send(MailboxMessage.completed("agent_probe", "done"))
    manager = SimpleNamespace(mailbox=mailbox, running_count=lambda: 0)
    engine = SimpleNamespace(
        tool_context=SimpleNamespace(subagent_manager=manager, task_manager=None), tool_runtime=None
    )
    coordinator = SessionActivityCoordinator(engine, handle.try_emit)
    coordinator.start()
    await asyncio.sleep(0)
    await coordinator.stop()
    lost = not any(isinstance(e, SubAgentMailboxEvent) for e in handle.drain_events())
    drained = await mailbox.drain_available()
    assert lost and not drained
    count = [1]
    emitted = []
    manager.running_count = lambda: count[0]
    coordinator = SessionActivityCoordinator(engine, lambda event: emitted.append(event) or True)
    coordinator._emit_activity_snapshot()
    count[0] = 0
    coordinator._emit_activity_snapshot()
    assert [e.running_subagents for e in emitted] == [1]
    return {
        "completed_lost_after_mailbox_drain": lost,
        "activity_counts_after_1_to_0": [e.running_subagents for e in emitted],
    }


async def ledger_probe():
    release, entered = asyncio.Event(), asyncio.Event()

    class DelayedClient(LLMClient):
        async def stream_chat_completion(self, request):
            entered.set()
            await release.wait()
            yield StreamDone(usage=Usage(input_tokens=7, output_tokens=3))

    ledger = TurnUsageLedger()
    client = MeteredLLMClient(DelayedClient(), ledger)

    async def consume():
        with usage_source("subagent"):
            async for _ in client.stream_chat_completion(
                MessageRequest(model="probe", messages=[], max_tokens=8)
            ):
                pass

    task = asyncio.create_task(consume())
    await entered.wait()
    closed_turn_output = ledger.totals()["output_tokens"]
    ledger.reset()  # Same operation as Engine's next TurnStarted.
    release.set()
    await task
    next_turn_output = ledger.totals()["output_tokens"]
    assert closed_turn_output == 0 and next_turn_output == 3
    return {
        "origin_turn_output": closed_turn_output,
        "next_turn_receives_old_child_output": next_turn_output,
    }


async def runtime_probe():
    cfg = Config()
    cfg.features.tasks = True
    cfg.features.subagents = False
    cfg.features.mcp = False
    cfg.features.automations = False
    task_manager = SimpleNamespace(start=AsyncMock(), shutdown=AsyncMock())
    with tempfile.TemporaryDirectory() as root:
        with (
            patch("deepseek_tui.tools.runtime.TaskManager", return_value=task_manager),
            patch(
                "deepseek_tui.tools.runtime.build_subagent_manager",
                side_effect=ValueError("injected startup error"),
            ),
        ):
            try:
                await create_tool_runtime(
                    config=cfg, working_directory=Path(root), task_data_dir=Path(root)
                )
            except ValueError:
                pass
    assert task_manager.start.await_count == 1 and task_manager.shutdown.await_count == 0
    child = SimpleNamespace(shutdown=AsyncMock(side_effect=RuntimeError("injected close error")))
    tasks = SimpleNamespace(shutdown=AsyncMock())
    runtime = ToolRuntime(
        context=None,
        registry=None,
        task_manager=tasks,
        subagent_manager=child,
        mailbox=None,
        mcp_manager=None,
        lsp_manager=None,
    )
    try:
        await runtime.shutdown()
    except RuntimeError:
        pass
    assert tasks.shutdown.await_count == 0
    return {
        "started_manager_cleanup_on_factory_failure": task_manager.shutdown.await_count,
        "later_manager_cleanup_after_shutdown_failure": tasks.shutdown.await_count,
    }


def dedup_probe():
    dedup = ToolCallDeduplicator()
    first = dedup.classify("exec_shell", {"command": "counter increment"})
    dedup.record(first.key, "counter=1", is_error=False)
    repeated_write = dedup.classify("exec_shell", {"command": "counter increment"}).kind
    dedup.begin_batch()
    read = dedup.classify("read_file", {"path": "x"})
    dedup.record(read.key, "old", is_error=False)
    write = dedup.classify("write_file", {"path": "x", "content": "new"})
    dedup.record(write.key, "written", is_error=False)
    stale = dedup.classify("read_file", {"path": "x"})
    assert repeated_write == "reuse" and stale.reuse_content == "old"
    return {
        "second_write_decision": repeated_write,
        "read_after_write_content": stale.reuse_content,
    }


async def exhausted_rounds_probe():
    from deepseek_tui.engine.turn import TurnResult
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import ToolCall

    cfg = Config()
    for name in ("tasks", "subagents", "mcp", "automations", "plugins", "exec_policy"):
        setattr(cfg.features, name, False)
    with tempfile.TemporaryDirectory() as root:
        engine = await Engine.create(
            handle=EngineHandle(),
            client=AsyncMock(),
            config=cfg,
            working_directory=Path(root),
            max_tool_round_trips=0,
        )
        engine.turn_loop = SimpleNamespace(
            run=AsyncMock(
                return_value=TurnResult(
                    assistant_message=Message.assistant("working"),
                    tool_calls=[ToolCall(id="probe", name="read_file", arguments={"path": "x"})],
                )
            )
        )
        engine._execute_tool_calls = AsyncMock(return_value=[Message.tool_result("probe", "ok")])
        try:
            result = await engine._run_conversation(
                [Message.user("probe")], "deepseek-chat", "probe", 64
            )
            events = engine.handle.drain_events()
            errors = [event.message for event in events if type(event).__name__ == "ErrorEvent"]
            assert "Tool round-trip limit exceeded" in errors and result.outcome.value == "success"
            return {
                "error_events": errors,
                "returned_outcome": result.outcome.value,
                "returned_tool_round_count": result.tool_round_count,
            }
        finally:
            await engine.shutdown_session()


async def main():
    result = {
        "op_loop": await op_loop_probe(),
        "event_delivery": await downstream_events_probe(),
        "usage_ledger": await ledger_probe(),
        "runtime_lifecycle": await runtime_probe(),
        "dedup": dedup_probe(),
        "round_budget": await exhausted_rounds_probe(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
