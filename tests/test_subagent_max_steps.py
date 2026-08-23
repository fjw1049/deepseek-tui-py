"""Running out of steps is not the same as finishing.

``run_subagent_loop`` exits its ``while steps < DEFAULT_MAX_STEPS`` loop two
ways: the child broke out because it had written its report, or the budget ran
out under it. Both landed on the same return path, so the manager marked the
agent ``completed`` and the parent got a done sentinel carrying a step count and
nothing else — a half-finished run read exactly like a finished one.

Kimi raises on its step cap and fails the turn; Grok keeps the outcome but
labels it ``MaxTurnsReached``. Grok's shape is the one worth copying here: the
work the child did manage to write is still worth handing over, as long as the
parent can tell it is looking at an interrupted run.
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
from deepseek_tui.tools.subagent.completion import build_completion_payload
from deepseek_tui.tools.subagent.handoff_ledger import (
    HandoffOutcome,
    build_handoff_ledger,
    classify_handoff,
    is_resumable,
)

_MAX_STEPS = 3


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


@pytest.fixture(autouse=True)
def _small_step_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Burning 100 real rounds to prove this would only make the test slow."""
    monkeypatch.setattr(
        "deepseek_tui.tools.subagent.loop.DEFAULT_MAX_STEPS", _MAX_STEPS
    )


async def _run(scripts: list[list[StreamEvent]], tmp_path: Path) -> object:
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
                assignment=SubAgentAssignment(
                    objective="step budget handling", role="qa"
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        return await manager.get_result(spawned.agent_id)
    finally:
        await manager.shutdown()


# A child that only ever calls tools never reaches the report, so the budget is
# what stops it.
_NEVER_FINISHES = [
    StreamToolCallComplete(
        tool_call=ToolCall(id="c1", name="file_search", arguments={"query": "*.py"})
    ),
    StreamDone(usage=None),
]
_REPORTS = [
    StreamTextDelta(
        text="### SUMMARY\n共 115 个测试文件、649 个用例。"
    ),
    StreamDone(usage=None),
]


@pytest.mark.asyncio
async def test_exhausting_the_step_budget_is_flagged(tmp_path: Path) -> None:
    snapshot = await _run([_NEVER_FINISHES], tmp_path)

    assert snapshot.max_steps_reached is True
    assert snapshot.steps_taken == _MAX_STEPS


@pytest.mark.asyncio
async def test_exhausted_run_still_hands_over_what_it_has(tmp_path: Path) -> None:
    """Grok's shape: label the run, do not throw its work away."""
    snapshot = await _run([_NEVER_FINISHES], tmp_path)

    assert snapshot.status.kind.value == "completed"


@pytest.mark.asyncio
async def test_the_parent_is_told_the_budget_ran_out(tmp_path: Path) -> None:
    """A step count alone never said which of the two endings this was."""
    snapshot = await _run([_NEVER_FINISHES], tmp_path)

    payload = build_completion_payload(snapshot)
    assert "max_steps_reached" in payload


@pytest.mark.asyncio
async def test_a_child_that_reports_is_not_flagged(tmp_path: Path) -> None:
    snapshot = await _run([_REPORTS], tmp_path)

    assert snapshot.status.kind.value == "completed"
    assert snapshot.max_steps_reached is False
    assert "max_steps_reached" not in build_completion_payload(snapshot)


@pytest.mark.asyncio
async def test_an_exhausted_slot_is_resumable(tmp_path: Path) -> None:
    """``classify_handoff`` called it COMPLETED, so the ledger offered no id to
    resume and the parent had nothing telling it the assignment was unfinished."""
    snapshot = await _run([_NEVER_FINISHES], tmp_path)

    assert classify_handoff(snapshot) is HandoffOutcome.MAX_STEPS
    assert is_resumable(snapshot) is True


@pytest.mark.asyncio
async def test_the_ledger_names_the_exhausted_slot(tmp_path: Path) -> None:
    snapshot = await _run([_NEVER_FINISHES], tmp_path)

    ledger = build_handoff_ledger([snapshot])
    assert ledger is not None, "an unfinished slot must not be silent"
    assert 'outcome="max_steps_reached"' in ledger
    assert "agent(resume=" in ledger


@pytest.mark.asyncio
async def test_a_reporting_slot_stays_a_quiet_success(tmp_path: Path) -> None:
    snapshot = await _run([_REPORTS], tmp_path)

    assert classify_handoff(snapshot) is HandoffOutcome.COMPLETED
    assert build_handoff_ledger([snapshot]) is None
