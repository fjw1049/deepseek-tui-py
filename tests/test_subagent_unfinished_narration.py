"""Next-action prose is a stall; the checkpoint outlives the report.

Tonight's F2 wrote "继续读 plugins/store.py 与 source.py." with no tool call.
The loop treated that as a finish, then wiped the transcript so resume
restarted from the original prompt and threw away 35 steps of reading.
Kimi keeps context memory after distillSummary; we do the same, and also
refuse to graduate a next-step note.
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
from deepseek_tui.tools.durable_transcript import (
    load_transcript,
    subagent_transcript_path,
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
from deepseek_tui.tools.subagent.completion import (
    has_summary_section,
    looks_like_unfinished_narration,
)


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


def _request_text(request: MessageRequest) -> str:
    return "\n".join(
        str(getattr(block, "text", ""))
        for message in request.messages
        for block in message.content
    )


_NARRATE = [
    StreamTextDelta(text="继续读 plugins/store.py 与 source.py。"),
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
_LONG_NO_HEADING = [
    StreamTextDelta(
        text=(
            "I walked the plugin loader, the source registry, and the store "
            "layer, and the wiring is consistent across those three modules "
            "but this note still has no report heading so it is not a handoff."
        )
    ),
    StreamDone(usage=None),
]


def test_next_action_notes_are_unfinished_narration() -> None:
    assert looks_like_unfinished_narration(
        "继续读 plugins/store.py 与 source.py。"
    )
    assert looks_like_unfinished_narration("Next I'll read the other route files.")
    assert looks_like_unfinished_narration("Let me check source.py next.")
    assert not looks_like_unfinished_narration(
        "### SUMMARY\n共 115 个测试文件、649 个用例。"
    )
    assert not looks_like_unfinished_narration("Done.")
    assert not looks_like_unfinished_narration(
        "I walked the plugin loader, the source registry, and the store "
        "layer, and the wiring is consistent across those three modules "
        "but this note still has no report heading so it is not a handoff."
    )


async def _attach(
    tmp_path: Path, scripts: list[list[StreamEvent]]
) -> tuple[SubAgentManager, _ScriptedClient]:
    mailbox = Mailbox()
    manager = SubAgentManager(
        workspace=tmp_path,
        mailbox=mailbox,
        executor=get_real_subagent_executor(),
        default_model="deepseek-chat",
    )
    client = _ScriptedClient(scripts)
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
    return manager, client


@pytest.mark.asyncio
async def test_next_action_prose_keeps_the_tools(tmp_path: Path) -> None:
    manager, client = await _attach(
        tmp_path, [_NARRATE, _TOOL_CALL, _REAL_SUMMARY]
    )
    try:
        spawned = await manager.spawn(
            SpawnRequest(
                prompt="调研测试目录",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(
                    objective="unfinished narration", role="qa"
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        snapshot = await manager.get_result(spawned.agent_id)
    finally:
        await manager.shutdown()

    assert snapshot.status.kind.value == "completed"
    assert "649" in (snapshot.result or "")
    after = client.requests[1]
    assert after.tools, "the next-action note confiscated the tool catalog"
    assert "stall" in _request_text(after)
    assert "Stop exploring" not in _request_text(after)


@pytest.mark.asyncio
async def test_empty_completion_keeps_the_transcript_for_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "ds_home"))
    # One heading-less essay, one continuation, then accept.
    manager, client = await _attach(
        tmp_path, [_LONG_NO_HEADING, _LONG_NO_HEADING, _REAL_SUMMARY]
    )
    try:
        spawned = await manager.spawn(
            SpawnRequest(
                prompt="调研测试目录",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(
                    objective="keep checkpoint", role="qa"
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        first = await manager.get_result(spawned.agent_id)
        assert first.status.kind.value == "completed"
        assert not has_summary_section(first.result)

        existing = load_transcript(
            subagent_transcript_path(tmp_path, first.agent_id)
        )
        assert existing is not None
        assert existing.steps_taken == 2

        await manager.resume(first.agent_id)
        await manager.wait([first.agent_id], mode="all", timeout_ms=10_000)
        second = await manager.get_result(first.agent_id)
    finally:
        await manager.shutdown()

    assert second.steps_taken == 3
    assert has_summary_section(second.result)
    assert "649" in (second.result or "")
    # Resume reused the checkpoint; it did not restart from the raw prompt.
    assert any(
        "Continue from the checkpoint" in _request_text(req)
        for req in client.requests[2:]
    )


@pytest.mark.asyncio
async def test_a_real_report_keeps_the_transcript_until_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "ds_home"))
    manager, _client = await _attach(tmp_path, [_REAL_SUMMARY])
    try:
        spawned = await manager.spawn(
            SpawnRequest(
                prompt="调研测试目录",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(
                    objective="keep until close", role="qa"
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        snapshot = await manager.get_result(spawned.agent_id)
        existing = load_transcript(
            subagent_transcript_path(tmp_path, snapshot.agent_id)
        )
        assert has_summary_section(snapshot.result)
        assert existing is not None

        await manager.close(snapshot.agent_id)
        assert (
            load_transcript(subagent_transcript_path(tmp_path, snapshot.agent_id))
            is None
        )
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_a_real_report_can_still_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "ds_home"))
    follow_up = [
        StreamTextDelta(
            text=(
                "### SUMMARY\n补看了 store.py，接口在第 40 行。\n\n"
                "### EVIDENCE\nplugins/store.py:40"
            )
        ),
        StreamDone(usage=None),
    ]
    manager, client = await _attach(tmp_path, [_REAL_SUMMARY, follow_up])
    try:
        spawned = await manager.spawn(
            SpawnRequest(
                prompt="调研测试目录",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(
                    objective="resume after a report", role="qa"
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        first = await manager.get_result(spawned.agent_id)
        assert has_summary_section(first.result)

        await manager.resume(first.agent_id)
        await manager.wait([first.agent_id], mode="all", timeout_ms=10_000)
        second = await manager.get_result(first.agent_id)
    finally:
        await manager.shutdown()

    assert second.steps_taken == 2
    assert "store.py" in (second.result or "")
    assert any(
        "Continue from the checkpoint" in _request_text(req)
        for req in client.requests[1:]
    )
