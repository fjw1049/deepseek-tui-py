"""Batch handoff ledger: classify slots, count them, name who to resume."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.tools.subagent.agent import SubAgent, _stub_executor
from deepseek_tui.tools.subagent.handoff_ledger import (
    HandoffOutcome,
    build_handoff_ledger,
    classify_handoff,
    is_resumable,
)
from deepseek_tui.tools.subagent.types import (
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentType,
)


def _snap(
    *,
    agent_id: str = "agent_a",
    result: str | None = None,
    status: SubAgentStatus | None = None,
    structured: object | None = None,
) -> SubAgentResult:
    return SubAgentResult(
        agent_id=agent_id,
        agent_type=SubAgentType.EXPLORE,
        assignment=SubAgentAssignment(objective="x"),
        model="deepseek-chat",
        nickname=None,
        status=status or SubAgentStatus.completed(),
        result=result,
        steps_taken=1,
        duration_ms=1,
        structured=structured,
    )


def test_classify_failed_cancelled_interrupted() -> None:
    assert classify_handoff(_snap(status=SubAgentStatus.failed("boom"))) is HandoffOutcome.FAILED
    assert classify_handoff(_snap(status=SubAgentStatus.cancelled())) is HandoffOutcome.CANCELLED
    assert (
        classify_handoff(_snap(status=SubAgentStatus.interrupted("restart")))
        is HandoffOutcome.INTERRUPTED
    )


def test_empty_completed_is_not_success() -> None:
    assert classify_handoff(_snap(result=None)) is HandoffOutcome.EMPTY
    assert classify_handoff(_snap(result="Done.")) is HandoffOutcome.EMPTY
    assert classify_handoff(_snap(result="### SUMMARY\n做完了。")) is HandoffOutcome.EMPTY


def test_usable_report_or_structured_is_completed() -> None:
    assert (
        classify_handoff(
            _snap(result="### SUMMARY\n已修复 maintenance.py:228。")
        )
        is HandoffOutcome.COMPLETED
    )
    assert classify_handoff(_snap(result="", structured={"ok": True})) is HandoffOutcome.COMPLETED


def test_single_success_has_no_ledger() -> None:
    assert (
        build_handoff_ledger(
            [_snap(result="### SUMMARY\n已修复 maintenance.py:228。")]
        )
        is None
    )


def test_batch_counts_and_names_resume_ids() -> None:
    ok = _snap(
        agent_id="agent_ok",
        result="### SUMMARY\n已修复 maintenance.py:228。",
    )
    empty = _snap(agent_id="agent_empty", result="Done.")
    failed = _snap(agent_id="agent_fail", status=SubAgentStatus.failed("timeout"))
    body = build_handoff_ledger([ok, empty, failed])
    assert body is not None
    assert "<summary>completed: 1, empty: 1, failed: 1</summary>" in body
    assert "agent(resume=" in body
    assert 'outcome="completed"' in body
    assert 'agent_id="agent_empty"' in body
    assert 'outcome="empty"' in body
    assert 'outcome="failed"' in body


def test_all_success_batch_has_no_resume_hint() -> None:
    snaps = [
        _snap(agent_id="a1", result="### SUMMARY\n已修复 a.py:1。"),
        _snap(agent_id="a2", result="### SUMMARY\n已修复 b.py:2。"),
    ]
    body = build_handoff_ledger(snaps)
    assert body is not None
    assert "<summary>completed: 2</summary>" in body
    assert "resume_hint" not in body


@pytest.mark.asyncio
async def test_empty_completed_can_resume(tmp_path: Path) -> None:
    from deepseek_tui.tools.subagent.manager import SubAgentManager

    mgr = SubAgentManager(workspace=tmp_path, executor=_stub_executor)
    empty = SubAgent(
        agent_type=SubAgentType.EXPLORE,
        prompt="look around",
        assignment=SubAgentAssignment(objective="look"),
        model="deepseek-chat",
        nickname=None,
        allowed_tools=None,
        session_boot_id=mgr._session_boot_id,
        workspace=tmp_path,
    )
    empty.status = SubAgentStatus.completed()
    empty.result = "Done."
    mgr._agents[empty.id] = empty
    assert is_resumable(empty.snapshot()) is True
    snap = await mgr.resume(empty.id)
    assert snap.status.kind.value == "running"


@pytest.mark.asyncio
async def test_usable_completed_can_resume(tmp_path: Path) -> None:
    from deepseek_tui.tools.subagent.manager import SubAgentManager

    mgr = SubAgentManager(workspace=tmp_path, executor=_stub_executor)
    done = SubAgent(
        agent_type=SubAgentType.EXPLORE,
        prompt="look around",
        assignment=SubAgentAssignment(objective="look"),
        model="deepseek-chat",
        nickname=None,
        allowed_tools=None,
        session_boot_id=mgr._session_boot_id,
        workspace=tmp_path,
    )
    done.status = SubAgentStatus.completed()
    done.result = "### SUMMARY\n已修复 maintenance.py:228。"
    mgr._agents[done.id] = done
    # Ledger still scores this completed so the parent is not told to resume
    # every successful child; the call itself is allowed.
    assert is_resumable(done.snapshot()) is False
    snap = await mgr.resume(done.id)
    assert snap.status.kind.value == "running"
