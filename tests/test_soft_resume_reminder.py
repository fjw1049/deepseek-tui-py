"""Tests for soft-resume reminder builder (P0 durable-resume trigger)."""

from __future__ import annotations

from types import SimpleNamespace

from deepseek_tui.server.threads.soft_resume import (
    SOFT_RESUME_LEAD,
    build_soft_resume_reminder,
    is_resumable_agent,
    is_resumable_task,
)
from deepseek_tui.tools.subagent.types import (
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentType,
)
from deepseek_tui.tools.task.models import TaskStatus


def _agent(
    agent_id: str,
    *,
    kind: str = "cancelled",
    objective: str = "explore the repo",
    steps: int = 3,
) -> SubAgentResult:
    status = {
        "cancelled": SubAgentStatus.cancelled(),
        "failed": SubAgentStatus.failed("boom"),
        "interrupted": SubAgentStatus.interrupted("restart"),
        "completed": SubAgentStatus.completed(),
        "running": SubAgentStatus.running(),
    }[kind]
    return SubAgentResult(
        agent_id=agent_id,
        agent_type=SubAgentType.EXPLORE,
        assignment=SubAgentAssignment(objective=objective),
        model="deepseek-chat",
        nickname=None,
        status=status,
        result=None,
        steps_taken=steps,
        duration_ms=100,
    )


def test_empty_lists_fall_back_to_the_lead() -> None:
    assert build_soft_resume_reminder() == SOFT_RESUME_LEAD
    assert build_soft_resume_reminder(agents=[], tasks=[]) == SOFT_RESUME_LEAD
    assert (
        build_soft_resume_reminder(
            agents=[_agent("a1", kind="completed")],
            tasks=[SimpleNamespace(id="t1", status=TaskStatus.COMPLETED, prompt="x")],
        )
        == SOFT_RESUME_LEAD
    )


def test_lists_resumable_agents_and_forbids_spawn() -> None:
    text = build_soft_resume_reminder(
        agents=[
            _agent("agent_abc", kind="cancelled", objective="find bugs", steps=4),
            _agent("agent_done", kind="completed"),
            _agent("agent_fail", kind="failed", objective="x" * 120, steps=1),
        ]
    )
    assert SOFT_RESUME_LEAD in text
    assert "subagent agent_abc (cancelled, steps=4)" in text
    assert "objective=find bugs" in text
    assert "agent_done" not in text
    assert "subagent agent_fail (failed" in text
    assert "…" in text  # long objective clipped
    assert 'resume="<id>"' in text
    assert 'action="spawn"' in text


def test_lists_resumable_tasks() -> None:
    text = build_soft_resume_reminder(
        tasks=[
            SimpleNamespace(
                id="task_1",
                status=TaskStatus.FAILED,
                prompt_summary="run checks",
            ),
            SimpleNamespace(
                id="task_2",
                status=TaskStatus.QUEUED,
                prompt_summary="should skip",
            ),
            SimpleNamespace(
                id="task_3",
                status=TaskStatus.TIMED_OUT,
                prompt="full prompt text",
            ),
        ]
    )
    assert "task task_1 (failed) prompt=run checks" in text
    assert "task_2" not in text
    assert "task task_3 (timed_out) prompt=full prompt text" in text
    assert 'task_create with only resume="<id>"' in text


def test_is_resumable_helpers() -> None:
    assert is_resumable_agent(_agent("a", kind="interrupted"))
    assert not is_resumable_agent(_agent("a", kind="running"))
    assert is_resumable_task(SimpleNamespace(status=TaskStatus.CANCELED))
    assert not is_resumable_task(SimpleNamespace(status=TaskStatus.RUNNING))


def test_lead_defers_to_the_users_new_message() -> None:
    assert "user's next message" in SOFT_RESUME_LEAD
    assert "finish the original objective" not in SOFT_RESUME_LEAD


async def test_manager_lists_only_this_threads_tasks() -> None:
    from deepseek_tui.server.threads.manager import RuntimeThreadManager

    def task(tid, thread):
        return SimpleNamespace(
            id=tid, status=TaskStatus.FAILED, prompt_summary=tid, thread_id=thread
        )

    async def list_tasks(limit=None):
        return [task("task_here", "thr_a"), task("task_elsewhere", "thr_b")]

    manager = SimpleNamespace(
        _active={"thr_a": SimpleNamespace(engine=SimpleNamespace(tool_context=SimpleNamespace(
            subagent_manager=None, task_manager=SimpleNamespace(list_tasks=list_tasks))))},
        _shared_tool_runtime=None,
    )
    text = await RuntimeThreadManager._build_soft_resume_reminder_text(manager, "thr_a")
    assert "task_here" in text and "task_elsewhere" not in text
