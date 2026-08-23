"""An empty round is a stall, not a finish.

A reasoning model routinely burns a round thinking ("let me also check the
other route files") and then emits neither text nor a tool call. The loop read
that as "exploration is over" and answered with the forced-summary nudge —
*You have gathered enough information. Stop exploring and do NOT call any
more tools* — and dropped the tool catalog for the next round. So a child that
had stalled halfway could not resume even in principle: it could only write up
whatever it had. That is the "summarises work it never finished" complaint.

Treat the stall as a stall. Keep the tools, ask for the next concrete action,
and only demand the report after the child keeps stalling — a genuinely stuck
child still has to hand something back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.config.models import Config
from deepseek_tui.engine.turn import MAX_EMPTY_RESPONSE_RESAMPLES
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamEvent,
    StreamTextDelta,
    StreamThinkingDelta,
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
from deepseek_tui.tools.subagent.loop import MAX_SUBAGENT_EMPTY_ROUNDS


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


async def _run_single_subagent(
    scripts: list[list[StreamEvent]],
    tmp_path: Path,
    *,
    client_out: list[_ScriptedClient] | None = None,
) -> object:
    mailbox = Mailbox()
    manager = SubAgentManager(
        workspace=tmp_path,
        mailbox=mailbox,
        executor=get_real_subagent_executor(),
        default_model="deepseek-chat",
    )
    client = _ScriptedClient(scripts)
    if client_out is not None:
        client_out.append(client)
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
                    objective="stall handling", role="qa"
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


# One stalled round costs 1 + MAX_EMPTY_RESPONSE_RESAMPLES client calls: the
# turn layer resamples an empty stream before handing it up as SUCCESS.
_CALLS_PER_STALLED_ROUND = 1 + MAX_EMPTY_RESPONSE_RESAMPLES
_STALL = [
    StreamThinkingDelta(thinking="Let me also look at the other route files."),
    StreamDone(usage=None),
]
_TOOL_CALL = [
    StreamToolCallComplete(
        tool_call=ToolCall(id="c1", name="file_search", arguments={"query": "*.py"})
    ),
    StreamDone(usage=None),
]
_REAL_SUMMARY = [
    StreamTextDelta(
        text=(
            "### SUMMARY\n共 115 个测试文件、649 个用例。\n\n"
            "### EVIDENCE\ntests/conftest.py:1-40"
        )
    ),
    StreamDone(usage=None),
]


@pytest.mark.asyncio
async def test_a_stall_keeps_the_tools_and_asks_for_the_next_action(
    tmp_path: Path,
) -> None:
    clients: list[_ScriptedClient] = []
    await _run_single_subagent(
        [*[_STALL] * _CALLS_PER_STALLED_ROUND, _TOOL_CALL, _REAL_SUMMARY],
        tmp_path,
        client_out=clients,
    )

    client = clients[0]
    # The round after the stall must still be able to act.
    after_stall = client.requests[_CALLS_PER_STALLED_ROUND]
    assert after_stall.tools, "the stall confiscated the tool catalog"
    text = _request_text(after_stall)
    assert "stall" in text
    assert "Stop exploring" not in text


@pytest.mark.asyncio
async def test_a_stalling_child_can_resume_and_finish_the_work(
    tmp_path: Path,
) -> None:
    """The point of keeping the tools: the run continues instead of wrapping up."""
    clients: list[_ScriptedClient] = []
    snapshot = await _run_single_subagent(
        [*[_STALL] * _CALLS_PER_STALLED_ROUND, _TOOL_CALL, _REAL_SUMMARY],
        tmp_path,
        client_out=clients,
    )

    assert snapshot.status.kind.value == "completed"
    assert "649" in (snapshot.result or "")
    # A tool actually ran after the stall: its call is back in the transcript.
    called = [
        getattr(block, "name", "")
        for request in clients[0].requests
        for message in request.messages
        for block in message.content
    ]
    assert "file_search" in called


@pytest.mark.asyncio
async def test_repeated_stalls_still_fall_back_to_demanding_the_report(
    tmp_path: Path,
) -> None:
    """A child that will not act must still hand something back."""
    clients: list[_ScriptedClient] = []
    snapshot = await _run_single_subagent(
        [
            *[_STALL] * (_CALLS_PER_STALLED_ROUND * (MAX_SUBAGENT_EMPTY_ROUNDS + 1)),
            _REAL_SUMMARY,
        ],
        tmp_path,
        client_out=clients,
    )

    assert snapshot.status.kind.value == "completed"
    assert "649" in (snapshot.result or "")

    client = clients[0]
    # Tools stay on for the tolerated stalls, then come off exactly once the
    # budget is spent.
    tools_off = [i for i, req in enumerate(client.requests) if not req.tools]
    assert tools_off, "the forced-summary fallback never fired"
    first_off = tools_off[0]
    assert first_off == _CALLS_PER_STALLED_ROUND * (MAX_SUBAGENT_EMPTY_ROUNDS + 1)
    assert "Stop exploring" in _request_text(client.requests[first_off])
