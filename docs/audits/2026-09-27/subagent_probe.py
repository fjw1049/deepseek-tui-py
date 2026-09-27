"""Offline characterization of audit 05 defects, not desired-behavior tests."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from deepseek_tui.config.models import Config
from deepseek_tui.tools.durable_transcript import DurableTranscript, save_transcript, subagent_transcript_path
from deepseek_tui.tools.subagent import (
    AgentRunOutput, Mailbox, MailboxMessage, SpawnRequest, SubAgentAssignment,
    SubAgentManager, SubAgentRuntime, SubAgentType, run_subagent_loop,
)
from deepseek_tui.tools.subagent.tools import _result_to_json


def request():
    return SpawnRequest(prompt="audit probe", agent_type=SubAgentType.GENERAL,
                        assignment=SubAgentAssignment(objective="audit probe"))


async def blocked(agent, cancel):
    await asyncio.Event().wait()


async def done(agent, cancel):
    return AgentRunOutput(text="### SUMMARY\n1 finding", structured={"finding": 1})


async def main(root):
    results = {}
    # Resume bypasses the spawn admission limit.
    m = SubAgentManager(root, max_agents=1, executor=done)
    a = await m.spawn(request())
    await m._agents[a.agent_id].task
    m._executor = blocked
    b = await m.spawn(request())
    await m.resume(a.agent_id)
    results["resume_running_vs_cap"] = [m.running_count(), m.max_agents]
    assert m.running_count() == 2
    await m.shutdown()

    # A cancelled old driver can overwrite the state of its new generation.
    entered, cleanup, release, new_started = (asyncio.Event() for _ in range(4))
    calls = 0
    async def delayed_cancel(agent, cancel):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup.set()
                await release.wait()
                raise
        new_started.set()
        await asyncio.Event().wait()
    m = SubAgentManager(root, executor=delayed_cancel)
    a = await m.spawn(request())
    old = m._agents[a.agent_id].task
    await entered.wait()
    await m.cancel(a.agent_id)
    await cleanup.wait()
    await m.resume(a.agent_id)
    new = m._agents[a.agent_id].task
    await new_started.wait()
    release.set()
    await old
    results["cancel_resume_race"] = {
        "status": (await m.get_result(a.agent_id)).status.kind.value,
        "new_driver_alive": not new.done(),
    }
    assert not new.done() and results["cancel_resume_race"]["status"] == "cancelled"
    await m.shutdown()

    # Stored lifetime steps consume the entire resumed attempt's budget.
    m = SubAgentManager(root, executor=done)
    a = await m.spawn(request())
    await m._agents[a.agent_id].task
    agent = m._agents[a.agent_id]
    from deepseek_tui.tools.subagent.loop import DEFAULT_MAX_STEPS
    save_transcript(subagent_transcript_path(root, agent.id), DurableTranscript(
        owner_kind="subagent", owner_id=agent.id,
        messages=[{"role": "user", "content": [{"type": "text", "text": "continue"}]}],
        steps_taken=DEFAULT_MAX_STEPS, round_complete=True,
    ))
    runtime = SubAgentRuntime(manager=m, client=Mock(), model="deepseek-chat",
                              config=Config(), workspace=root)
    output = await run_subagent_loop(agent, runtime, asyncio.Event())
    results["resume_exhausted_budget"] = {
        "new_llm_calls": runtime.client.stream_chat_completion.call_count,
        "text": output.text, "max_steps_reached": agent.max_steps_reached,
    }
    assert not output.text and agent.max_steps_reached
    await m.shutdown()

    # Independent managers sharing a registry silently replace each other's records.
    state = root / "shared.json"
    first = SubAgentManager(root, state_path=state, executor=blocked)
    second = SubAgentManager(root, state_path=state, executor=blocked)
    a = await first.spawn(request())
    b = await second.spawn(request())
    stored = [entry["id"] for entry in json.loads(state.read_text())["agents"]]
    results["shared_registry_lost_record"] = a.agent_id not in stored
    assert stored == [b.agent_id]
    await first.shutdown()
    await second.shutdown()

    # Memory eviction also deletes the only registry entry.
    state = root / "eviction.json"
    m = SubAgentManager(root, state_path=state, executor=done)
    ids = []
    for _ in range(31):
        snap = await m.spawn(request())
        ids.append(snap.agent_id)
        await m._agents[snap.agent_id].task
    stored = [entry["id"] for entry in json.loads(state.read_text())["agents"]]
    results["eviction"] = {"retained": len(stored), "first_lost": ids[0] not in stored}
    assert len(stored) == 30 and ids[0] not in stored
    snap = await m.get_result(ids[-1])
    listed = m.list_agents()[-1]
    results["structured_delivery"] = {
        "get_result": snap.structured,
        "list_result": listed.structured,
        "tool_json_has_structured": "structured" in _result_to_json(snap),
    }
    assert snap.structured and listed.structured is None
    assert "structured" not in _result_to_json(snap)
    await m.shutdown()

    # JSON null is valid schema output but doubles as the "not returned" sentinel.
    from deepseek_tui.engine.turn import TurnResult
    from deepseek_tui.protocol.responses import ToolCall
    from deepseek_tui.tools.durable_transcript import load_transcript
    m = SubAgentManager(root, executor=done)
    a = await m.spawn(request())
    await m._agents[a.agent_id].task
    agent = m._agents[a.agent_id]
    agent.output_schema = {"type": "null"}
    runtime = SubAgentRuntime(manager=m, client=Mock(), model="deepseek-chat",
                              config=Config(), workspace=root)
    result = TurnResult(assistant_message=None, usage=None, tool_calls=[
        ToolCall(id="null", name="structured_output", arguments={"output": None}),
    ])
    with patch("deepseek_tui.engine.turn.TurnLoop.run", AsyncMock(return_value=result)), \
         patch("deepseek_tui.tools.subagent.loop.DEFAULT_MAX_STEPS", 2):
        try:
            await run_subagent_loop(agent, runtime, asyncio.Event())
        except RuntimeError as exc:
            results["valid_json_null_rejected"] = "did not return structured_output" in str(exc)
        else:
            raise AssertionError("null unexpectedly accepted")
    assert results["valid_json_null_rejected"]

    # A terminating tool before siblings leaves unmatched tool_use blocks.
    a = await m.spawn(request())
    await m._agents[a.agent_id].task
    agent = m._agents[a.agent_id]
    agent.output_schema = {"type": "object", "properties": {"answer": {"type": "integer"}}}
    result = TurnResult(assistant_message=None, usage=None, tool_calls=[
        ToolCall(id="final", name="structured_output", arguments={"answer": 1}),
        ToolCall(id="skipped", name="read_file", arguments={"path": "unused"}),
    ])
    with patch("deepseek_tui.engine.turn.TurnLoop.run", AsyncMock(return_value=result)):
        await run_subagent_loop(agent, runtime, asyncio.Event())
    transcript = load_transcript(subagent_transcript_path(root, agent.id))
    uses, replies = set(), set()
    for message in transcript.messages:
        for block in message.get("content", []):
            if block.get("type") == "tool_use":
                uses.add(block["id"])
            if block.get("type") == "tool_result":
                replies.add(block["tool_use_id"])
    results["structured_output_unmatched_calls"] = sorted(uses - replies)
    assert results["structured_output_unmatched_calls"] == ["skipped"]
    await m.shutdown()

    mailbox = Mailbox()
    mailbox.send(MailboxMessage.completed("old", "done"))
    for _ in range(512):
        mailbox.send(MailboxMessage.progress("new", "working"))
    envelopes = await mailbox.drain_available()
    results["mailbox_terminal_lost"] = not any(e.message.agent_id == "old" for e in envelopes)
    assert results["mailbox_terminal_lost"]

    state = root / "corrupt.json"
    state.write_text(json.dumps({"schema_version": 2, "agents": [{"id": "bad"}]}))
    try:
        SubAgentManager(root, state_path=state)
    except KeyError:
        results["malformed_record_breaks_manager"] = True
    else:
        raise AssertionError("malformed registry was unexpectedly accepted")
    return results


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="subagent-audit-") as directory:
        root = Path(directory)
        os.environ["DEEPSEEK_HOME"] = str(root / "home")
        os.environ["CLAUDE_PLUGINS_DIR"] = str(root / "plugins")
        print(json.dumps(asyncio.run(main(root)), ensure_ascii=False, indent=2))
