"""Offline regression: a sub-agent whose terminal round answers only in the
reasoning channel must still finish with a non-empty result.

Reasoning models (DeepSeek V4/R1) frequently emit the final answer as thinking
with an empty text block. Harvesting only text blocks previously left the
sub-agent ``completed`` but with an empty result, which cascaded into empty
"view result" cards and a parent agent that could not read anything back.
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
    StreamThinkingDelta,
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


class _ScriptedClient(LLMClient):
    """Yields a per-call script of stream events.

    Accepts either one event list (reused for every request) or a list of
    scripts (one consumed per request, last one repeating). Records each
    request so tests can assert on tool availability per round.
    """

    def __init__(self, scripts: list[StreamEvent] | list[list[StreamEvent]]) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        if scripts and isinstance(scripts[0], list):
            self._scripts: list[list[StreamEvent]] = scripts  # type: ignore[assignment]
        else:
            self._scripts = [scripts]  # type: ignore[list-item]
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
    events: list[StreamEvent] | list[list[StreamEvent]],
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
    client = _ScriptedClient(events)
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
                    objective="reasoning-only terminal round",
                    role="qa",
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        return await manager.get_result(spawned.agent_id)
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_reasoning_only_terminal_round_yields_nonempty_result(
    tmp_path: Path,
) -> None:
    snapshot = await _run_single_subagent(
        [
            StreamThinkingDelta(thinking="测试套件共 115 个文件、649 个用例。"),
            StreamDone(usage=None),
        ],
        tmp_path,
    )

    assert snapshot.status.kind.value == "completed"
    assert snapshot.result
    assert "649" in snapshot.result


@pytest.mark.asyncio
async def test_visible_text_still_preferred_over_reasoning(
    tmp_path: Path,
) -> None:
    snapshot = await _run_single_subagent(
        [
            StreamThinkingDelta(thinking="internal scratchpad, not the answer"),
            StreamTextDelta(text="最终结论：架构清晰。"),
            StreamDone(usage=None),
        ],
        tmp_path,
    )

    assert snapshot.status.kind.value == "completed"
    assert snapshot.result == "最终结论：架构清晰。"


@pytest.mark.asyncio
async def test_stalled_round_triggers_forced_summary(tmp_path: Path) -> None:
    """A reasoning-only stall round must trigger one tools-off summary nudge
    that yields a real report, rather than surfacing the stall fragment."""
    clients: list[_ScriptedClient] = []
    snapshot = await _run_single_subagent(
        [
            # Round 1: model stalls — reasoning fragment, no text, no tool calls.
            [
                StreamThinkingDelta(thinking="Let me also look at the other route files."),
                StreamDone(usage=None),
            ],
            # Round 2: forced summary (tools off) — real prose report.
            [
                StreamTextDelta(text="最终报告：115 个测试文件，649 个用例，覆盖率良好。"),
                StreamDone(usage=None),
            ],
        ],
        tmp_path,
        client_out=clients,
    )

    assert snapshot.status.kind.value == "completed"
    assert snapshot.result == "最终报告：115 个测试文件，649 个用例，覆盖率良好。"
    assert "Let me also look" not in snapshot.result

    client = clients[0]
    assert client.calls == 2
    # Round 1 offered tools; the forced-summary round 2 stripped them.
    assert client.requests[0].tools
    assert not client.requests[1].tools
