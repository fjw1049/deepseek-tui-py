"""A child that keeps getting errors back needs telling, not more rounds.

Tool errors reach the model as an ordinary tool result, so a child that picks a
wrong path or a wrong tool can spend its whole step budget re-issuing the same
failing call: nothing in the transcript says "this is the fifth time". The
run then ends on the step cap with no report, or on a report written from
nothing. Count the streak and say so once it is long enough to be a pattern.

Grok tracks consecutive failures per run for the same reason. The nudge is the
intervention; the step budget stays the hard bound.
"""

from __future__ import annotations

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
    SubAgentType,
    get_real_subagent_executor,
)
from deepseek_tui.tools.subagent.loop import MAX_CONSECUTIVE_TOOL_FAILURES


class _ScriptedClient(LLMClient):
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        self._scripts = scripts
        self.calls = 0
        self.requests: list[MessageRequest] = []

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        script = self._scripts[min(self.calls, len(self._scripts) - 1)]
        self.calls += 1
        for event in script:
            yield event


async def _run(
    scripts: list[list[StreamEvent]],
    tmp_path: Path,
    clients: list[_ScriptedClient],
) -> object:
    mailbox = Mailbox()
    manager = SubAgentManager(
        workspace=tmp_path,
        mailbox=mailbox,
        executor=get_real_subagent_executor(),
        default_model="deepseek-chat",
    )
    client = _ScriptedClient(scripts)
    clients.append(client)
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
    try:
        spawned = await manager.spawn(
            SpawnRequest(
                prompt="调研测试目录",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(
                    objective="tool failure streak", role="qa"
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        return await manager.get_result(spawned.agent_id)
    finally:
        await manager.shutdown()


def _request_text(request: MessageRequest) -> str:
    return "\n".join(
        str(getattr(block, "text", ""))
        for message in request.messages
        for block in message.content
    )


def _failing_call(n: int) -> list[StreamEvent]:
    return [
        StreamToolCallComplete(
            tool_call=ToolCall(
                id=f"bad{n}",
                name="read_file",
                arguments={"path": "does/not/exist.py"},
            )
        ),
        StreamDone(usage=None),
    ]


_WORKING_CALL = [
    StreamToolCallComplete(
        tool_call=ToolCall(
            id="ok1",
            name="file_search",
            arguments={"pattern": "", "path": "."},
        )
    ),
    StreamDone(usage=None),
]
_REPORT = [
    StreamTextDelta(text="### SUMMARY\n共 115 个测试文件、649 个用例。"),
    StreamDone(usage=None),
]

_MARKER = "came back as errors"


@pytest.mark.asyncio
async def test_a_failing_streak_is_named_once_it_is_a_pattern(
    tmp_path: Path,
) -> None:
    clients: list[_ScriptedClient] = []
    streak = [_failing_call(i) for i in range(MAX_CONSECUTIVE_TOOL_FAILURES)]
    await _run([*streak, _REPORT], tmp_path, clients)

    client = clients[0]
    # Nothing is said before the streak is long enough to be one.
    for request in client.requests[:MAX_CONSECUTIVE_TOOL_FAILURES]:
        assert _MARKER not in _request_text(request)
    after = _request_text(client.requests[MAX_CONSECUTIVE_TOOL_FAILURES])
    assert _MARKER in after


@pytest.mark.asyncio
async def test_the_child_keeps_its_tools_while_being_told(tmp_path: Path) -> None:
    """This is a course correction, not a demand for the report."""
    clients: list[_ScriptedClient] = []
    streak = [_failing_call(i) for i in range(MAX_CONSECUTIVE_TOOL_FAILURES)]
    await _run([*streak, _REPORT], tmp_path, clients)

    request = clients[0].requests[MAX_CONSECUTIVE_TOOL_FAILURES]
    assert request.tools, "the nudge confiscated the tool catalog"
    assert "Stop exploring" not in _request_text(request)


@pytest.mark.asyncio
async def test_one_working_call_clears_the_streak(tmp_path: Path) -> None:
    """The budget bounds a run of failures, not the run's total."""
    clients: list[_ScriptedClient] = []
    before = [_failing_call(i) for i in range(MAX_CONSECUTIVE_TOOL_FAILURES - 1)]
    after = [
        _failing_call(100 + i) for i in range(MAX_CONSECUTIVE_TOOL_FAILURES - 1)
    ]
    await _run([*before, _WORKING_CALL, *after, _REPORT], tmp_path, clients)

    for request in clients[0].requests:
        assert _MARKER not in _request_text(request)


@pytest.mark.asyncio
async def test_the_run_still_finishes_normally(tmp_path: Path) -> None:
    clients: list[_ScriptedClient] = []
    streak = [_failing_call(i) for i in range(MAX_CONSECUTIVE_TOOL_FAILURES)]
    snapshot = await _run([*streak, _REPORT], tmp_path, clients)

    assert snapshot.status.kind.value == "completed"
    assert "649" in (snapshot.result or "")
