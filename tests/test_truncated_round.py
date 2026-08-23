"""``finish_reason: "length"`` is a fragment, not an answer.

The stream parser handled ``tool_calls`` and ``stop`` and let everything else
fall through, so a response cut off at the output cap arrived as a perfectly
ordinary ``StreamDone``. Nothing downstream could tell the difference: the
sub-agent loop saw prose with no tool calls, decided the child had written
its report, and handed the parent half a sentence as the deliverable.

Truncation is deterministic — the same request hits the same cap at the same
place — so the fragment is dropped and the round is re-run asking for less,
on the same bounded budget as a failed round.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.client.streaming import OpenAIStreamParser
from deepseek_tui.config.models import Config
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamEvent,
    StreamTextDelta,
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
from deepseek_tui.tools.subagent.loop import MAX_SUBAGENT_ROUND_FAILURES


def _parse(parser: OpenAIStreamParser, finish_reason: str) -> list[StreamEvent]:
    events = parser.parse_chunk(
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "半句话"},
                    "finish_reason": finish_reason,
                }
            ]
        }
    )
    return events + parser.finalize()


def test_length_finish_reason_marks_the_stream_truncated() -> None:
    done = [e for e in _parse(OpenAIStreamParser(), "length") if isinstance(e, StreamDone)]
    assert len(done) == 1
    assert done[0].truncated is True


def test_stop_finish_reason_is_not_truncated() -> None:
    done = [e for e in _parse(OpenAIStreamParser(), "stop") if isinstance(e, StreamDone)]
    assert len(done) == 1
    assert done[0].truncated is False


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
                    objective="truncation handling", role="qa"
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        return await manager.get_result(spawned.agent_id)
    finally:
        await manager.shutdown()


_FRAGMENT = "### SUMMARY\n这份报告写到一半就被上限截"
_TRUNCATED_ROUND = [
    StreamTextDelta(text=_FRAGMENT),
    StreamDone(usage=None, truncated=True),
]
_SHORTER_SUMMARY = [
    StreamTextDelta(text="### SUMMARY\n共 115 个测试文件、649 个用例。"),
    StreamDone(usage=None),
]


@pytest.mark.asyncio
async def test_truncated_report_is_never_the_deliverable(tmp_path: Path) -> None:
    clients: list[_ScriptedClient] = []
    snapshot = await _run_single_subagent(
        [_TRUNCATED_ROUND], tmp_path, client_out=clients
    )

    assert snapshot.status.kind.value == "failed"
    assert "truncat" in (snapshot.status.message or "").lower()
    assert _FRAGMENT not in (snapshot.result or "")
    assert clients[0].calls == 1 + MAX_SUBAGENT_ROUND_FAILURES


@pytest.mark.asyncio
async def test_truncated_round_is_retried_asking_for_less(tmp_path: Path) -> None:
    clients: list[_ScriptedClient] = []
    snapshot = await _run_single_subagent(
        [_TRUNCATED_ROUND, _SHORTER_SUMMARY], tmp_path, client_out=clients
    )

    assert snapshot.status.kind.value == "completed"
    assert "649" in (snapshot.result or "")
    assert _FRAGMENT not in (snapshot.result or "")

    # The retry carries a "cut off at the cap" reminder and not the fragment.
    retry = clients[0].requests[1]
    serialised = "\n".join(
        str(getattr(block, "text", ""))
        for message in retry.messages
        for block in message.content
    )
    assert "cut off" in serialised
    assert _FRAGMENT not in serialised
