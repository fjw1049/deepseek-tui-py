"""A failed LLM round must not read as a finished sub-agent.

``run_subagent_loop`` used to inspect only ``cancelled`` / ``tool_calls`` /
message text, never ``TurnResult.outcome``. A round that failed after the
model had emitted a few tokens therefore looked exactly like a normal
"prose, no tool calls" finish, so the loop broke out and the manager marked
the agent ``completed`` — handing the parent a truncated fragment as the
whole deliverable, with no error anywhere.

The transport layer already retries what it can; by the time ``FAILED``
reaches the loop its budget is spent. The loop owns the next decision:
re-run the round on its own bounded budget, then fail loudly.
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
    StreamError,
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
                    objective="failed round handling",
                    role="qa",
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        return await manager.get_result(spawned.agent_id)
    finally:
        await manager.shutdown()


_TRUNCATED = "### SUMMARY\n调研到一半就断了，这句话没写完"
_BROKEN_ROUND = [
    StreamTextDelta(text=_TRUNCATED),
    StreamError(message="HTTP 500 from upstream provider", retryable=False),
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
async def test_failed_round_never_completes_the_subagent(tmp_path: Path) -> None:
    """Every round fails: the agent must end FAILED, carrying the real error."""
    clients: list[_ScriptedClient] = []
    snapshot = await _run_single_subagent(
        [_BROKEN_ROUND], tmp_path, client_out=clients
    )

    assert snapshot.status.kind.value == "failed"
    assert "500" in (snapshot.status.message or "")
    # The truncated fragment must not be surfaced as the deliverable.
    assert _TRUNCATED not in (snapshot.result or "")
    # One initial attempt plus the loop's own bounded re-runs.
    assert clients[0].calls == 1 + MAX_SUBAGENT_ROUND_FAILURES


@pytest.mark.asyncio
async def test_transient_failed_round_is_retried_then_succeeds(
    tmp_path: Path,
) -> None:
    """A single bad round must not cost the run — re-run it and carry on."""
    clients: list[_ScriptedClient] = []
    snapshot = await _run_single_subagent(
        [_BROKEN_ROUND, _REAL_SUMMARY], tmp_path, client_out=clients
    )

    assert snapshot.status.kind.value == "completed"
    assert "649" in (snapshot.result or "")
    assert _TRUNCATED not in (snapshot.result or "")
    assert clients[0].calls == 2


@pytest.mark.asyncio
async def test_failed_round_is_not_appended_to_the_transcript(
    tmp_path: Path,
) -> None:
    """The retry must not see the truncated half-sample as prior context."""
    clients: list[_ScriptedClient] = []
    await _run_single_subagent(
        [_BROKEN_ROUND, _REAL_SUMMARY], tmp_path, client_out=clients
    )

    retry_request = clients[0].requests[1]
    serialised = "".join(
        str(block)
        for message in retry_request.messages
        for block in message.content
    )
    assert _TRUNCATED not in serialised
