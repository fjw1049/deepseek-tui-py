"""The run panel reads a child's display history, not its mailbox rail.

Reasoning models narrate tool rounds in the thinking channel and leave the
text block empty, so a history that only keeps raw reasoning shows the panel a
wall of tool rows with nothing between them. The loop already derives a
one-line narration for the mailbox; the display history must carry it too.

A round without tool calls is not the end of the run either: stall nudges and
summary recovery keep going, so only the text the executor delivers is final.
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
    StreamToolCallComplete,
    ToolCall,
)
from deepseek_tui.tools.run_conversation import load_run_conversation
from deepseek_tui.tools.subagent import (
    Mailbox,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentType,
    get_real_subagent_executor,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))


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


async def _run(scripts: list[list[StreamEvent]], tmp_path: Path) -> str:
    mailbox = Mailbox()
    manager = SubAgentManager(
        workspace=tmp_path,
        mailbox=mailbox,
        executor=get_real_subagent_executor(),
        default_model="deepseek-chat",
    )
    manager.attach_loop_runtime(
        SubAgentRuntime(
            manager=manager,
            client=_ScriptedClient(scripts),
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
                assignment=SubAgentAssignment(objective="run history", role="qa"),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        snapshot = await manager.get_result(spawned.agent_id)
        assert snapshot.status.kind.value == "completed"
        return spawned.agent_id
    finally:
        await manager.shutdown()


_THINKING_TOOL_ROUND = [
    StreamThinkingDelta(thinking="Inspect the test directory first.\n\nThen count files."),
    StreamToolCallComplete(
        tool_call=ToolCall(
            id="call1", name="file_search", arguments={"pattern": "", "path": "."}
        )
    ),
    StreamDone(usage=None),
]
_STALL_TEXT = [StreamTextDelta(text="继续读 plugins/store.py。"), StreamDone(usage=None)]
_REPORT_TEXT = "### SUMMARY\n共 115 个测试文件、649 个用例。"
_REPORT = [StreamTextDelta(text=_REPORT_TEXT), StreamDone(usage=None)]


async def test_thinking_only_tool_round_carries_narration(tmp_path: Path) -> None:
    agent_id = await _run([_THINKING_TOOL_ROUND, _REPORT], tmp_path)

    blocks = load_run_conversation("subagent", agent_id)["blocks"]
    reasoning = [b for b in blocks if b["kind"] == "reasoning"]
    assert reasoning[0]["narration"] == "Inspect the test directory first."
    assert reasoning[0]["text"].endswith("Then count files.")


async def test_only_the_delivered_report_is_final(tmp_path: Path) -> None:
    agent_id = await _run([_THINKING_TOOL_ROUND, _STALL_TEXT, _REPORT], tmp_path)

    blocks = load_run_conversation("subagent", agent_id)["blocks"]
    answers = [b for b in blocks if b["kind"] == "assistant"]
    stall = next(b for b in answers if b["text"] == "继续读 plugins/store.py。")
    assert stall["agentSegment"] == "mid_turn_preface"
    finals = [b for b in answers if b.get("agentSegment") == "final_answer"]
    assert [b["text"] for b in finals] == [_REPORT_TEXT]
    assert blocks[-1]["id"] == finals[0]["id"]
