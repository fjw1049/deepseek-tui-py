"""The run panel reads a child's display history, not its mailbox rail.

Reasoning models narrate tool rounds in the thinking channel and leave the
text block empty, so a history that only keeps raw reasoning shows the panel a
wall of tool rows with nothing between them. The loop already derives a
one-line narration for the mailbox; the display history must carry it too.

A round without tool calls is not the end of the run either: stall nudges and
summary recovery keep going, so only the text the executor delivers is final.
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
    StreamError,
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


def _manager(client: LLMClient, tmp_path: Path) -> SubAgentManager:
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
            client=client,
            model="deepseek-chat",
            config=Config(),
            workspace=tmp_path,
            mailbox=mailbox,
            auto_approve=True,
        )
    )
    return manager


async def _spawn(manager: SubAgentManager) -> str:
    spawned = await manager.spawn(
        SpawnRequest(
            prompt="调研测试目录",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="run history", role="qa"),
        )
    )
    return spawned.agent_id


async def _run(scripts: list[list[StreamEvent]], tmp_path: Path) -> str:
    manager = _manager(_ScriptedClient(scripts), tmp_path)
    try:
        agent_id = await _spawn(manager)
        await manager.wait([agent_id], mode="all", timeout_ms=10_000)
        snapshot = await manager.get_result(agent_id)
        assert snapshot.status.kind.value == "completed"
        return agent_id
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


_FRAGMENT = "调研到一半就断了，这句话没写完"


def _texts(agent_id: str) -> list[str]:
    return [b.get("text") or "" for b in load_run_conversation("subagent", agent_id)["blocks"]]


async def test_failed_round_fragment_is_dropped_from_history(tmp_path: Path) -> None:
    broken = [
        StreamThinkingDelta(thinking="half a thought"),
        StreamTextDelta(text=_FRAGMENT),
        StreamError(message="HTTP 500 from upstream provider", retryable=False),
    ]
    agent_id = await _run([broken, _REPORT], tmp_path)

    texts = _texts(agent_id)
    assert _FRAGMENT not in texts
    assert "half a thought" not in texts
    assert texts[-1] == _REPORT_TEXT


async def test_truncated_round_is_dropped_with_a_note(tmp_path: Path) -> None:
    truncated = [StreamTextDelta(text=_FRAGMENT), StreamDone(usage=None, truncated=True)]
    agent_id = await _run([truncated, _REPORT], tmp_path)

    blocks = load_run_conversation("subagent", agent_id)["blocks"]
    assert _FRAGMENT not in [b.get("text") for b in blocks]
    notes = [b for b in blocks if b["kind"] == "system"]
    assert len(notes) == 1 and "超出长度上限" in notes[0]["text"]
    assert blocks[-1]["text"] == _REPORT_TEXT


class _BlockingFirstRound(LLMClient):
    """Streams a fragment and hangs on the first request; reports afterwards."""

    def __init__(self) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        self.started = asyncio.Event()
        self.calls = 0

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        if self.calls == 1:
            yield StreamTextDelta(text="INCOMPLETE OLD ANSWER")
            self.started.set()
            await asyncio.Event().wait()
        yield StreamTextDelta(text=_REPORT_TEXT)
        yield StreamDone(usage=None)


async def test_interrupted_generation_is_dropped_from_history(tmp_path: Path) -> None:
    client = _BlockingFirstRound()
    manager = _manager(client, tmp_path)
    try:
        agent_id = await _spawn(manager)
        await asyncio.wait_for(client.started.wait(), 5)
        await manager.send_input(agent_id, "NEW REQUIREMENT", interrupt=True)
        await manager.wait([agent_id], mode="all", timeout_ms=10_000)
    finally:
        await manager.shutdown()

    blocks = load_run_conversation("subagent", agent_id)["blocks"]
    texts = [b.get("text") for b in blocks]
    assert "INCOMPLETE OLD ANSWER" not in texts
    assert [b["text"] for b in blocks if b["kind"] == "user"][-1] == "NEW REQUIREMENT"
    assert texts[-1] == _REPORT_TEXT
    assert len({b["id"] for b in blocks}) == len(blocks)


class _RecordingClient(_ScriptedClient):
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        super().__init__(scripts)
        self.requests: list[MessageRequest] = []

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        self.requests.append(request.model_copy(deep=True))
        async for event in super().stream_chat_completion(request):
            yield event


def _tool_round(n: int) -> list[StreamEvent]:
    return [
        StreamToolCallComplete(
            tool_call=ToolCall(
                id=f"call{n}", name="file_search", arguments={"pattern": "", "path": "."}
            )
        ),
        StreamDone(usage=None),
    ]


async def test_round_budget_reminder_repeats_every_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deepseek_tui.tools.subagent import loop

    monkeypatch.setattr(loop, "SUBAGENT_ROUND_NUDGE_INTERVAL", 2)
    client = _RecordingClient([*(_tool_round(n) for n in range(1, 6)), _REPORT])
    manager = _manager(client, tmp_path)
    try:
        agent_id = await _spawn(manager)
        await manager.wait([agent_id], mode="all", timeout_ms=10_000)
    finally:
        await manager.shutdown()

    marker = "rounds. If the assignment is answered"
    seen = [request.model_dump_json().count(marker) for request in client.requests]
    # Reminded after rounds 2 and 4; tools stay available the whole time.
    assert seen == [0, 0, 1, 1, 2, 2]
    assert "used 4 of" in client.requests[4].model_dump_json()
    assert all(request.tools for request in client.requests)
