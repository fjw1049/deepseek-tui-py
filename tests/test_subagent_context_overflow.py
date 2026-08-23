"""A sub-agent gets the same compaction lifeline the parent turn has.

``TurnLoop`` recovers from an over-budget request by calling ``compact_fn``
and retrying. The parent orchestrator passes ``_emergency_compact``; the
sub-agent loop passed nothing, so the recovery path incremented its counter,
called nothing, and looped — three no-op attempts, then ``CONTEXT_OVERFLOW``
with ``assistant_message=None``. The loop did not read ``outcome``, so that
empty round fell into the forced-summary branch and the child "finished"
with whatever it had.

Compaction can still legitimately fail (a first round that overflows on its
own has nothing to summarise). When it does, the run must fail loudly rather
than hand the parent a silent completion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.config.models import Config
from deepseek_tui.engine.turn import TurnOutcomeStatus, TurnResult
from deepseek_tui.tools.subagent import (
    Mailbox,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentType,
    get_real_subagent_executor,
)


class _RecordingTurnLoop:
    """Stands in for TurnLoop to capture how the sub-agent loop builds it."""

    instances: list[_RecordingTurnLoop] = []

    def __init__(self, client: Any, compact_fn: Any = None) -> None:
        self.client = client
        self.compact_fn = compact_fn
        self.runs = 0
        _RecordingTurnLoop.instances.append(self)

    async def run(self, request: Any, emit: Any, cancel: Any, **kwargs: Any):
        self.runs += 1
        return TurnResult(
            assistant_message=None,
            outcome=TurnOutcomeStatus.CONTEXT_OVERFLOW,
            error_message="Context remains above model limit after 3 attempts",
        )


async def _run_overflowing_subagent(tmp_path: Path) -> object:
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
            client=object(),
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
                prompt="调研一个超长上下文",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(
                    objective="context overflow handling", role="qa"
                ),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10_000)
        return await manager.get_result(spawned.agent_id)
    finally:
        await manager.shutdown()


@pytest.fixture(autouse=True)
def _recording_turn_loop(monkeypatch: pytest.MonkeyPatch):
    _RecordingTurnLoop.instances = []
    monkeypatch.setattr(
        "deepseek_tui.engine.turn.TurnLoop", _RecordingTurnLoop
    )
    return _RecordingTurnLoop


@pytest.mark.asyncio
async def test_subagent_turn_loop_is_given_a_compact_fn(tmp_path: Path) -> None:
    await _run_overflowing_subagent(tmp_path)

    assert _RecordingTurnLoop.instances, "the loop never built a TurnLoop"
    assert _RecordingTurnLoop.instances[0].compact_fn is not None


@pytest.mark.asyncio
async def test_unrecoverable_overflow_fails_instead_of_completing(
    tmp_path: Path,
) -> None:
    snapshot = await _run_overflowing_subagent(tmp_path)

    assert snapshot.status.kind.value == "failed"
    assert "overflow" in (snapshot.status.message or "").lower()


@pytest.mark.asyncio
async def test_overflow_is_not_retried_round_after_round(
    tmp_path: Path,
) -> None:
    """Overflow is deterministic — re-running the same messages cannot help."""
    await _run_overflowing_subagent(tmp_path)

    assert _RecordingTurnLoop.instances[0].runs == 1
