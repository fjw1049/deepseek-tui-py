"""Sub-agent mailbox emits round narration before tool calls."""

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
    StreamToolCallComplete,
    ToolCall,
)
from deepseek_tui.tools.subagent import (
    Mailbox,
    MailboxMessageKind,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentType,
    get_real_subagent_executor,
)
from deepseek_tui.tools.subagent.loop import _mailbox_round_narration


class _ScriptedClient(LLMClient):
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        self._scripts = scripts
        self.calls = 0

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        script = self._scripts[min(self.calls, len(self._scripts) - 1)]
        self.calls += 1
        for event in script:
            yield event


def test_mailbox_round_narration_prefers_text_over_thinking() -> None:
    assert (
        _mailbox_round_narration("先看 chat 组件", "internal scratch")
        == "先看 chat 组件"
    )


def test_mailbox_round_narration_falls_back_to_thinking() -> None:
    out = _mailbox_round_narration("", "确认 Workflow 入口后再读文件。")
    assert out is not None
    assert "Workflow" in out


def test_mailbox_round_narration_empty_when_blank() -> None:
    assert _mailbox_round_narration("", "") is None
    assert _mailbox_round_narration("   ", "  ") is None


@pytest.mark.asyncio
async def test_progress_emitted_before_tool_calls(tmp_path: Path) -> None:
    mailbox = Mailbox()
    manager = SubAgentManager(
        workspace=tmp_path,
        mailbox=mailbox,
        executor=get_real_subagent_executor(),
        default_model="deepseek-chat",
    )
    client = _ScriptedClient(
        [
            [
                StreamTextDelta(text="先看目录结构，确认入口。"),
                StreamToolCallComplete(
                    tool_call=ToolCall(
                        id="call_list",
                        name="list_dir",
                        arguments={"path": str(tmp_path)},
                    )
                ),
                StreamDone(usage=None),
            ],
            [
                StreamTextDelta(text="目录为空，探索结束。"),
                StreamDone(usage=None),
            ],
        ]
    )
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
                prompt="explore tmp",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(
                    objective="mailbox narration order",
                    role="qa",
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
    finally:
        await manager.shutdown()

    envelopes = await mailbox.drain_available()
    kinds = [env.message.kind for env in envelopes]
    # started … progress → tool_call_started → tool_call_completed … progress … completed
    assert MailboxMessageKind.PROGRESS in kinds
    assert MailboxMessageKind.TOOL_CALL_STARTED in kinds

    first_progress = kinds.index(MailboxMessageKind.PROGRESS)
    first_tool = kinds.index(MailboxMessageKind.TOOL_CALL_STARTED)
    assert first_progress < first_tool

    first_narration = next(
        env.message.status
        for env in envelopes
        if env.message.kind is MailboxMessageKind.PROGRESS
    )
    assert first_narration is not None
    assert "目录结构" in first_narration
