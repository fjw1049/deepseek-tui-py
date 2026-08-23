"""Live path: eight children finish, parent handoff must score the batch.

This is the wait-for-8 case: harness does not re-run anyone, but the parent
must see empty/failed slots and the resume ids — not just the successes.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from deepseek_tui.engine.handle import SUBAGENT_BACKGROUND_DONE_KIND, SendMessageOp
from deepseek_tui.tools.subagent import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentCompletion,
    SubAgentType,
)
from deepseek_tui.tools.subagent.types import SubAgentStatusKind

_GOOD = "### SUMMARY\n已修复 maintenance.py:228。"


async def _wait_for_n_completions(engine, n: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if engine._subagent_completions.qsize() >= n:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(
        f"expected {n} completions, queue has {engine._subagent_completions.qsize()}"
    )


@pytest.mark.asyncio
async def test_eight_children_handoff_scores_empty_and_failed(
    engine_ctx: tuple,
) -> None:
    engine, _handle = engine_ctx
    mgr = engine.tool_context.subagent_manager
    assert mgr is not None

    async def _executor(agent, cancel):  # noqa: ANN001
        prompt = agent.prompt
        if prompt.startswith("fail:"):
            raise RuntimeError("child exploded")
        if prompt.startswith("empty:"):
            return "Done."
        return _GOOD

    mgr._executor = _executor  # noqa: SLF001

    ids: list[str] = []
    for i in range(8):
        if i < 5:
            prompt = f"ok:{i}"
        elif i < 7:
            prompt = f"empty:{i}"
        else:
            prompt = f"fail:{i}"
        snap = await mgr.spawn(
            SpawnRequest(
                prompt=prompt,
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(objective=prompt),
                parent_depth=0,
            )
        )
        ids.append(snap.agent_id)

    waited = await mgr.wait(ids, mode="all", timeout_ms=5_000)
    kinds = {s.agent_id: s.status.kind for s in waited}
    assert sum(1 for k in kinds.values() if k is SubAgentStatusKind.COMPLETED) == 7
    assert sum(1 for k in kinds.values() if k is SubAgentStatusKind.FAILED) == 1

    await _wait_for_n_completions(engine, 8)
    messages: list = []
    injected = await engine._handle_subagent_turn_handoff(messages)
    assert injected is True
    assert len(messages) == 9  # ledger + 8 dones

    ledger = messages[0].text_content()
    assert "<subagent_handoff>" in ledger
    assert "completed: 5" in ledger
    assert "empty: 2" in ledger
    assert "failed: 1" in ledger
    assert "agent(resume=" in ledger
    empty_ids = [s.agent_id for s in waited if (s.result or "").strip() == "Done."]
    failed_ids = [
        s.agent_id for s in waited if s.status.kind is SubAgentStatusKind.FAILED
    ]
    assert len(empty_ids) == 2
    assert len(failed_ids) == 1
    for aid in empty_ids + failed_ids:
        assert aid in ledger

    # Ledger still scores a good report completed (no resume_hint in the
    # scorecard), but resume itself is allowed on either slot.
    good_id = next(
        s.agent_id for s in waited if (s.result or "").startswith("### SUMMARY")
    )
    resumed_good = await mgr.resume(good_id)
    assert resumed_good.status.kind is SubAgentStatusKind.RUNNING
    resumed = await mgr.resume(empty_ids[0])
    assert resumed.status.kind is SubAgentStatusKind.RUNNING


@pytest.mark.asyncio
async def test_eight_successes_have_ledger_but_no_resume_hint(
    engine_ctx: tuple,
) -> None:
    engine, _handle = engine_ctx
    mgr = engine.tool_context.subagent_manager
    assert mgr is not None

    async def _executor(agent, cancel):  # noqa: ANN001
        return _GOOD

    mgr._executor = _executor  # noqa: SLF001
    ids = []
    for i in range(8):
        snap = await mgr.spawn(
            SpawnRequest(
                prompt=f"ok:{i}",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(objective=f"ok:{i}"),
                parent_depth=0,
            )
        )
        ids.append(snap.agent_id)
    await mgr.wait(ids, mode="all", timeout_ms=5_000)
    await _wait_for_n_completions(engine, 8)
    messages: list = []
    assert await engine._handle_subagent_turn_handoff(messages) is True
    ledger = messages[0].text_content()
    assert "<summary>completed: 8</summary>" in ledger
    assert "resume_hint" not in ledger
    assert len(messages) == 9


@pytest.mark.asyncio
async def test_single_success_still_has_no_ledger(engine_ctx: tuple) -> None:
    engine, _handle = engine_ctx
    mgr = engine.tool_context.subagent_manager
    assert mgr is not None

    async def _executor(agent, cancel):  # noqa: ANN001
        return _GOOD

    mgr._executor = _executor  # noqa: SLF001
    await mgr.spawn(
        SpawnRequest(
            prompt="ok",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="ok"),
            parent_depth=0,
        )
    )
    await _wait_for_n_completions(engine, 1)
    messages: list = []
    assert await engine._handle_subagent_turn_handoff(messages) is True
    assert len(messages) == 1
    assert "<subagent_handoff>" not in messages[0].text_content()
    assert "subagent.done" in messages[0].text_content()


@pytest.mark.asyncio
async def test_idle_delivery_includes_ledger_when_idle(engine_ctx: tuple) -> None:
    engine, handle = engine_ctx
    mgr = engine.tool_context.subagent_manager
    assert mgr is not None
    assert handle.is_turn_active() is False

    from deepseek_tui.tools.subagent.agent import SubAgent
    from deepseek_tui.tools.subagent.types import SubAgentStatus

    for agent_id, result in (
        ("agent_idle_ok", _GOOD),
        ("agent_idle_empty", "Done."),
    ):
        agent = SubAgent(
            agent_type=SubAgentType.EXPLORE,
            prompt="hi",
            assignment=SubAgentAssignment(objective="hi"),
            model="deepseek-chat",
            nickname=None,
            allowed_tools=None,
            session_boot_id=mgr._session_boot_id,
            workspace=engine.tool_context.working_directory,
        )
        agent.id = agent_id
        agent.status = SubAgentStatus.completed()
        agent.result = result
        mgr._agents[agent_id] = agent
        engine._enqueue_subagent_completion(
            SubAgentCompletion(agent_id=agent_id, payload=f"payload-{agent_id}")
        )

    ops: list[SendMessageOp] = []

    async def _capture(op):  # noqa: ANN001
        ops.append(op)

    handle.send_op = _capture  # type: ignore[method-assign]
    await engine._deliver_subagent_completions_when_idle()
    assert len(ops) == 1
    assert ops[0].hidden is True
    assert ops[0].internal_kind == SUBAGENT_BACKGROUND_DONE_KIND
    body = ops[0].content
    assert "<subagent_handoff>" in body
    assert "empty: 1" in body
    assert "payload-agent_idle_ok" in body
    assert "payload-agent_idle_empty" in body
