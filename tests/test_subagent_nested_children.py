"""A sub-agent's own children are reported to it, and never left running.

Only the main engine receives completion callbacks. A sub-agent that spawned
a child and then wrote its report used to finish with the child still running
and its result unread by anyone.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.config.models import Config
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamEvent,
    StreamTextDelta,
    StreamToolCallComplete,
    ToolCall,
)
from deepseek_tui.tools.subagent import (
    Mailbox,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentStatusKind,
    SubAgentType,
    get_real_subagent_executor,
)

_CHILD_PROMPT = "CHILD-TASK count files"


def _text(text: str) -> list[StreamEvent]:
    return [StreamTextDelta(text=text), StreamDone(usage=None)]


_SPAWN = [
    StreamToolCallComplete(tool_call=ToolCall(
        id="spawn1", name="agent",
        arguments={"action": "spawn", "prompt": _CHILD_PROMPT, "agent_type": "explore"},
    )),
    StreamDone(usage=None),
]


class _Client(LLMClient):
    """Parent and child share one client; route by whose conversation it is."""

    def __init__(self, parent: list[list[StreamEvent]], child_gate: asyncio.Event | None) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        self.parent = parent
        self.parent_requests: list[MessageRequest] = []
        self.child_gate = child_gate

    async def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[StreamEvent]:
        if _CHILD_PROMPT in str(request.messages[0].content):
            if self.child_gate is not None:
                await self.child_gate.wait()
            for event in _text("### SUMMARY\n子任务找到 42 个文件。"):
                yield event
            return
        script = self.parent[min(len(self.parent_requests), len(self.parent) - 1)]
        self.parent_requests.append(request)
        for event in script:
            yield event


async def _run_parent(tmp_path: Path, client: _Client, handoff_secs: float = 10.0):
    mailbox = Mailbox()
    manager = SubAgentManager(
        workspace=tmp_path, mailbox=mailbox,
        executor=get_real_subagent_executor(), default_model="deepseek-chat",
        handoff_timeout_secs=handoff_secs,
    )
    manager.attach_loop_runtime(SubAgentRuntime(
        manager=manager, client=client, model="deepseek-chat", config=Config(),
        workspace=tmp_path, mailbox=mailbox, auto_approve=True,
    ))
    try:
        parent = await manager.spawn(SpawnRequest(
            prompt="parent task", agent_type=SubAgentType.GENERAL,
            assignment=SubAgentAssignment(objective="parent task"),
        ))
        await manager.wait([parent.agent_id], mode="all", timeout_ms=10_000)
        children = manager.child_ids(parent.agent_id)
        return (
            await manager.get_result(parent.agent_id),
            [await manager.get_result(cid) for cid in children],
        )
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_unwaited_child_result_reaches_the_parent_subagent(tmp_path: Path) -> None:
    client = _Client([
        _SPAWN,
        _text("### SUMMARY\n已派出 1 个子代理。"),
        _text("### SUMMARY\n汇总：子代理统计到 42 个文件。"),
    ], child_gate=None)

    parent, children = await _run_parent(tmp_path, client)

    assert len(children) == 1
    assert children[0].status.kind is SubAgentStatusKind.COMPLETED
    # The parent was not allowed to stop until it had read the child's report.
    assert len(client.parent_requests) == 3
    last_round = "".join(str(m.content) for m in client.parent_requests[-1].messages)
    assert "subagent.done" in last_round
    assert "42" in last_round
    assert "汇总" in (parent.result or "")


@pytest.mark.asyncio
async def test_child_still_running_at_the_end_is_stopped(tmp_path: Path) -> None:
    client = _Client([
        _SPAWN,
        _text("### SUMMARY\n已派出 1 个子代理。"),
        _text("### SUMMARY\n子代理超时，已停止。"),
    ], child_gate=asyncio.Event())  # the child never answers

    parent, children = await _run_parent(tmp_path, client, handoff_secs=0.2)

    assert parent.status.kind is SubAgentStatusKind.COMPLETED
    assert [c.status.kind for c in children] == [SubAgentStatusKind.CANCELLED]
    last_round = "".join(str(m.content) for m in client.parent_requests[-1].messages)
    assert "cancelled" in last_round
