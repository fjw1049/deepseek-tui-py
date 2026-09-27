"""Behavioral regressions for audit 05 (offline, isolated state)."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from deepseek_tui.config.models import Config
from deepseek_tui.engine.turn import TurnResult
from deepseek_tui.protocol.responses import ToolCall, Usage
from deepseek_tui.tools.durable_transcript import (
    DurableTranscript,
    load_transcript,
    save_transcript,
    subagent_transcript_path,
)
from deepseek_tui.tools.subagent import (
    AgentRunOutput,
    Mailbox,
    MailboxMessage,
    MailboxMessageKind,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentType,
    run_subagent_loop,
)
from deepseek_tui.tools.subagent.tools import _result_to_json


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))


def request():
    return SpawnRequest(
        prompt="probe",
        agent_type=SubAgentType.GENERAL,
        assignment=SubAgentAssignment(objective="probe"),
    )


async def complete(agent, cancel):
    return AgentRunOutput(text="### SUMMARY\n1 result", structured={"result": 1})


async def block(agent, cancel):
    await asyncio.Event().wait()


def manager(root, **kwargs):
    return SubAgentManager(root, state_path=root / "registry.json", **kwargs)


async def finished(m):
    result = await m.spawn(request())
    await m._agents[result.agent_id].task
    return result.agent_id


async def test_cancel_joins_old_driver_before_resuming(tmp_path):
    entered, cleanup, release = (asyncio.Event() for _ in range(3))

    async def executor(agent, cancel):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup.set()
            await release.wait()
            raise

    m = manager(tmp_path, max_agents=1, executor=executor)
    try:
        child = await m.spawn(request())
        await entered.wait()
        stopping = asyncio.create_task(m.cancel(child.agent_id))
        await cleanup.wait()
        assert not stopping.done()
        with pytest.raises(RuntimeError, match="already running"):
            await m.resume(child.agent_id)
        with pytest.raises(RuntimeError, match="Too many"):
            await m.spawn(request())
        release.set()
        await stopping
        m._executor = block
        resumed = await m.resume(child.agent_id)
        await asyncio.sleep(0)
        assert resumed.status.kind.value == "running"
        assert (await m.get_result(child.agent_id)).status.kind.value == "running"
    finally:
        release.set()
        await m.shutdown()


async def test_cancel_before_first_instruction_releases_claim(tmp_path):
    mailbox, completions = Mailbox(), []
    m = manager(tmp_path, executor=block, mailbox=mailbox)
    m.attach_parent_completion_sink(completions.append)
    try:
        child = await m.spawn(request())
        assert (await m.cancel(child.agent_id)).status.kind.value == "cancelled"
        assert len(completions) == 1
        assert (
            sum(
                event.message.kind is MailboxMessageKind.CANCELLED
                for event in await mailbox.drain_available()
            )
            == 1
        )
        assert not m._claims
        await m.resume(child.agent_id)
    finally:
        await m.shutdown()


@pytest.mark.parametrize("operation", ["resume", "send_input"])
async def test_all_restart_paths_obey_capacity(tmp_path, operation):
    m = manager(tmp_path, max_agents=1, executor=complete)
    try:
        old = await finished(m)
        m._executor = block
        await m.spawn(request())
        with pytest.raises(RuntimeError, match="Too many"):
            if operation == "resume":
                await m.resume(old)
            else:
                await m.send_input(old, "continue")
        assert m.running_count() == 1
    finally:
        await m.shutdown()


async def test_same_workspace_managers_keep_both_records_and_reject_duplicate_execution(tmp_path):
    first, second = manager(tmp_path, executor=block), manager(tmp_path, executor=block)
    observer = None
    try:
        a, b = await first.spawn(request()), await second.spawn(request())
        assert len(list((tmp_path / "registry.agents").glob("*.json"))) == 2
        observer = manager(tmp_path, executor=block)
        assert {a.agent_id, b.agent_id} <= observer.known_agent_ids()
        with pytest.raises(RuntimeError, match="active executor"):
            await observer.resume(a.agent_id)
        with pytest.raises(RuntimeError, match="active executor"):
            await observer.close(a.agent_id)
    finally:
        await first.shutdown()
        await second.shutdown()
        if observer:
            await observer.shutdown()


async def test_evicted_history_still_resolves_and_duration_is_frozen(tmp_path, monkeypatch):
    m = manager(tmp_path, executor=complete)
    try:
        ids = [await finished(m) for _ in range(31)]
        assert len(m._agents) <= 30
        before = await m.get_result(ids[0])
        assert before.structured == {"result": 1}
        assert _result_to_json(before)["structured"] == {"result": 1}
        assert len(m.list_agents()) == 31
        assert m.known_agent_ids() == set(ids)
        assert len(m._agents) <= 30
        monkeypatch.setattr("deepseek_tui.tools.subagent.agent._epoch_ms", lambda: 10**15)
        assert (await m.get_result(ids[0])).duration_ms == before.duration_ms
    finally:
        await m.shutdown()
    restored = manager(tmp_path)
    try:
        assert len(restored.list_filtered(include_archived=True)) == 31
        assert (await restored.get_result(ids[0])).structured == {"result": 1}
    finally:
        await restored.shutdown()


async def test_bad_record_is_isolated_and_future_version_rejected(tmp_path):
    m = manager(tmp_path, executor=complete)
    good = await finished(m)
    await m.shutdown()
    (tmp_path / "registry.agents" / "agent_bad.json").write_text(
        json.dumps({"id": "agent_bad", "assignment": []})
    )
    restored = manager(tmp_path)
    assert (await restored.get_result(good)).result
    assert restored.storage_error
    await restored.shutdown()
    (tmp_path / "registry.json").write_text('{"schema_version": 999, "agents": []}')
    with pytest.raises(RuntimeError, match="Unsupported"):
        manager(tmp_path)


async def test_mailbox_progress_cannot_displace_completion_and_overflow_resyncs(tmp_path):
    box = Mailbox()
    box.send(MailboxMessage.completed("old", "done"))
    for _ in range(600):
        box.send(MailboxMessage.progress("new", "working"))
    drained = await box.drain_available()
    assert len(drained) == 512
    assert any(e.message.kind is MailboxMessageKind.COMPLETED for e in drained)
    assert box.dropped_events == 89
    m = manager(tmp_path, executor=complete, mailbox=box)
    try:
        child = await finished(m)
        for i in range(600):
            box.send(MailboxMessage.completed(f"synthetic-{i}", "done"))
        assert box.needs_resync()
        drained = await box.drain_available()
        assert any(
            e.message.agent_id == child and e.message.kind is MailboxMessageKind.COMPLETED
            for e in drained
        )
        assert not box.needs_resync()
    finally:
        await m.shutdown()


async def loop_fixture(tmp_path):
    m = manager(tmp_path, executor=complete)
    aid = await finished(m)
    agent = m._agents[aid]
    runtime = SubAgentRuntime(
        manager=m,
        client=Mock(),
        model="deepseek-chat",
        config=Config(),
        workspace=tmp_path,
        mailbox=Mailbox(),
    )
    return m, agent, runtime


async def test_exhausted_checkpoint_gets_new_attempt_budget(tmp_path, monkeypatch):
    from deepseek_tui.protocol.messages import Message

    m, agent, runtime = await loop_fixture(tmp_path)
    save_transcript(
        subagent_transcript_path(tmp_path, agent.id),
        DurableTranscript(
            owner_kind="subagent",
            owner_id=agent.id,
            steps_taken=200,
            force_summary=True,
            messages=[{"role": "user", "content": [{"type": "text", "text": "old"}]}],
        ),
    )
    agent.max_steps_reached = True
    run = AsyncMock(
        return_value=TurnResult(
            assistant_message=Message.assistant("### SUMMARY\n1 verified result"),
            usage=None,
            tool_calls=[],
        )
    )
    monkeypatch.setattr("deepseek_tui.engine.turn.TurnLoop.run", run)
    try:
        out = await run_subagent_loop(agent, runtime, asyncio.Event())
        assert out.text and run.await_count == 1
        assert agent.steps_taken == 201 and not agent.max_steps_reached
        assert run.call_args.args[0].tools
    finally:
        await m.shutdown()


@pytest.mark.parametrize(
    "value,schema",
    [
        (None, {"type": "null"}),
        ({"answer": 1}, {"type": "object", "properties": {"answer": {"type": "integer"}}}),
    ],
)
async def test_structured_output_preserves_null_and_completes_sibling_results(
    tmp_path, monkeypatch, value, schema
):
    m, agent, runtime = await loop_fixture(tmp_path)
    agent.output_schema = schema
    arguments = value if isinstance(value, dict) else {"output": value}
    run = AsyncMock(
        return_value=TurnResult(
            assistant_message=None,
            usage=None,
            tool_calls=[
                ToolCall(id="final", name="structured_output", arguments=arguments),
                ToolCall(id="sibling", name="read_file", arguments={"path": "unused"}),
            ],
        )
    )
    monkeypatch.setattr("deepseek_tui.engine.turn.TurnLoop.run", run)
    try:
        out = await run_subagent_loop(agent, runtime, asyncio.Event())
        assert out.structured_received and out.structured == value
        transcript = load_transcript(subagent_transcript_path(tmp_path, agent.id))
        blocks = [block for message in transcript.messages for block in message["content"]]
        uses = {block["id"] for block in blocks if block["type"] == "tool_use"}
        replies = {block["tool_use_id"] for block in blocks if block["type"] == "tool_result"}
        assert uses == replies == {"final", "sibling"}
    finally:
        await m.shutdown()


async def test_usage_sums_rounds_even_on_failure(tmp_path, monkeypatch):
    m, agent, runtime = await loop_fixture(tmp_path)
    rounds = [
        TurnResult(
            assistant_message=None, usage=Usage(input_tokens=3, output_tokens=2), tool_calls=[]
        ),
        TurnResult(
            assistant_message=None, usage=Usage(input_tokens=5, output_tokens=4), tool_calls=[]
        ),
        RuntimeError("simulated connection failure"),
    ]
    monkeypatch.setattr("deepseek_tui.engine.turn.TurnLoop.run", AsyncMock(side_effect=rounds))
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            await run_subagent_loop(agent, runtime, asyncio.Event())
        usage = [
            e.message.usage
            for e in await runtime.mailbox.drain_available()
            if e.message.kind is MailboxMessageKind.TOKEN_USAGE
        ]
        assert usage == [{"input_tokens": 8, "output_tokens": 6, "reasoning_tokens": 0}]
    finally:
        await m.shutdown()


def test_session_storage_is_stable_and_distinct(tmp_path):
    from deepseek_tui.config.paths import user_subagents_state_path

    assert user_subagents_state_path(tmp_path, "a") == user_subagents_state_path(tmp_path, "a")
    assert user_subagents_state_path(tmp_path, "a") != user_subagents_state_path(tmp_path, "b")


async def test_waiters_cannot_clear_each_others_completion_notification(tmp_path):
    gate, entered, finish = (asyncio.Event() for _ in range(3))

    class DelayedWait(asyncio.Event):
        async def wait(self):
            entered.set()
            await gate.wait()
            return await super().wait()

    async def executor(agent, cancel):
        await finish.wait()
        return AgentRunOutput(text="done")

    m = manager(tmp_path, executor=executor)
    m._changed = DelayedWait()
    waiter = None
    try:
        child = await m.spawn(request())
        waiter = asyncio.create_task(m.wait([child.agent_id], "all", 1000))
        await entered.wait()
        finish.set()
        await m._agents[child.agent_id].task
        assert (await m.wait([child.agent_id], "all", 1000))[0].status.kind.value == "completed"
        gate.set()
        assert (await asyncio.wait_for(waiter, 0.1))[0].status.kind.value == "completed"
    finally:
        gate.set()
        if waiter is not None:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        await m.shutdown()
