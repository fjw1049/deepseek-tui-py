"""Unified background-entity tools (Phase B: task 8 → 4).

``task_create`` / ``task_list`` / ``task_output`` / ``task_stop`` manage all
three kinds of background entities: durable tasks, sub-agents, and
in-memory background shell processes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.tools.approval import build_approval_key
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.shell import ExecShellTool
from deepseek_tui.tools.subagent.tools import AgentTool
from deepseek_tui.tools.subagent.types import (
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentType,
)
from deepseek_tui.tools.task import (
    NewTaskRequest,
    TaskManager,
    TaskManagerConfig,
    TaskStatus,
)
from deepseek_tui.tools.task.tools import (
    TaskCreateTool,
    TaskListTool,
    TaskOutputTool,
    TaskStopTool,
)


def _agent_result(agent_id: str, status: SubAgentStatus | None = None) -> SubAgentResult:
    return SubAgentResult(
        agent_id=agent_id,
        agent_type=SubAgentType.GENERAL,
        assignment=SubAgentAssignment(objective="obj"),
        model="m",
        nickname=None,
        status=status or SubAgentStatus.running(),
        result="done-text",
        steps_taken=1,
        duration_ms=10,
    )


class _StubSubAgentManager:
    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.snapshots: list[SubAgentResult] = []
        self.results: dict[str, SubAgentResult] = {}

    def list_filtered(self, include_archived: bool = False) -> list[SubAgentResult]:
        return list(self.snapshots)

    async def get_result(self, agent_id: str) -> SubAgentResult:
        return self.results[agent_id]

    async def wait(self, agent_ids, mode="any", timeout_ms=None) -> list[SubAgentResult]:
        return [self.results[a] for a in agent_ids]

    async def cancel(self, agent_id: str) -> SubAgentResult:
        self.cancelled.append(agent_id)
        return self.results[agent_id]


def _task_manager(tmp_path: Path, **kwargs) -> TaskManager:
    cfg = TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path)
    # No start(): tasks stay QUEUED, which keeps cancel/resume deterministic.
    return TaskManager(cfg, **kwargs)


# --- task_list: three-source aggregation --------------------------------------


async def test_task_list_aggregates_all_three_sources(tmp_path) -> None:
    manager = _task_manager(tmp_path)
    task = await manager.add_task(NewTaskRequest(prompt="durable work"))
    sub = _StubSubAgentManager()
    sub.snapshots.append(_agent_result("agent_x1"))
    ctx = ToolContext(
        working_directory=tmp_path, task_manager=manager, subagent_manager=sub
    )
    pid_result = await ExecShellTool().execute(
        {"command": "sleep 30", "background": True}, ctx
    )
    pid = pid_result.content
    try:
        result = await TaskListTool().execute({}, ctx)

        tasks = result.metadata["tasks"]
        agents = result.metadata["agents"]
        processes = result.metadata["processes"]
        assert [t["id"] for t in tasks] == [task.id]
        assert tasks[0]["kind"] == "task"
        assert [a["agent_id"] for a in agents] == ["agent_x1"]
        assert agents[0]["kind"] == "agent"
        assert [p["process_id"] for p in processes] == [pid]
        assert processes[0]["kind"] == "process"
        assert processes[0]["command"] == "sleep 30"
        assert processes[0]["status"] == "running"
        assert "1 task(s):" in result.content
        assert "1 agent(s):" in result.content
        assert "1 process(es):" in result.content
    finally:
        await TaskStopTool().execute({"process_id": pid}, ctx)


async def test_task_list_kind_filter(tmp_path) -> None:
    manager = _task_manager(tmp_path)
    await manager.add_task(NewTaskRequest(prompt="durable work"))
    ctx = ToolContext(working_directory=tmp_path, task_manager=manager)

    only_tasks = await TaskListTool().execute({"kind": "task"}, ctx)
    assert len(only_tasks.metadata["tasks"]) == 1
    assert only_tasks.metadata["agents"] == []
    assert only_tasks.metadata["processes"] == []

    only_processes = await TaskListTool().execute({"kind": "process"}, ctx)
    assert only_processes.metadata["tasks"] == []

    with pytest.raises(ToolError, match="kind must be one of"):
        await TaskListTool().execute({"kind": "bogus"}, ctx)


# --- task_output: three branches ----------------------------------------------


async def test_task_output_task_branch_reads_record(tmp_path) -> None:
    manager = _task_manager(tmp_path)
    task = await manager.add_task(NewTaskRequest(prompt="durable work"))
    ctx = ToolContext(working_directory=tmp_path, task_manager=manager)

    result = await TaskOutputTool().execute({"task_id": task.id}, ctx)

    assert result.metadata["task_id"] == task.id
    assert result.metadata["status"] == "queued"


async def test_task_output_agent_branch_nonblocking_snapshot(tmp_path) -> None:
    sub = _StubSubAgentManager()
    sub.results["agent_x1"] = _agent_result("agent_x1")
    ctx = ToolContext(working_directory=tmp_path, subagent_manager=sub)  # type: ignore[arg-type]

    result = await TaskOutputTool().execute({"agent_id": "agent_x1"}, ctx)

    assert result.success is True
    assert result.metadata["agent_id"] == "agent_x1"
    assert result.metadata["result"] == "done-text"


async def test_task_output_agent_branch_block_waits(tmp_path) -> None:
    sub = _StubSubAgentManager()
    sub.results["agent_x1"] = _agent_result(
        "agent_x1", SubAgentStatus.completed()
    )
    ctx = ToolContext(working_directory=tmp_path, subagent_manager=sub)  # type: ignore[arg-type]

    result = await TaskOutputTool().execute(
        {"agent_id": "agent_x1", "block": True, "timeout_ms": 5000}, ctx
    )

    assert result.metadata["agent_id"] == "agent_x1"
    assert result.metadata["status"]["kind"] == "completed"


async def test_task_output_process_branch_archives_on_task(tmp_path) -> None:
    """process_id + task_id keeps the retired task_shell_wait archival."""
    manager = _task_manager(tmp_path)
    task = await manager.add_task(NewTaskRequest(prompt="durable work"))
    ctx = ToolContext(working_directory=tmp_path, task_manager=manager)
    spawned = await ExecShellTool().execute(
        {"command": "echo archived-output", "background": True}, ctx
    )
    pid = spawned.content

    result = await TaskOutputTool().execute(
        {"process_id": pid, "task_id": task.id, "block": True, "timeout_ms": 5000},
        ctx,
    )

    assert result.metadata["status"] == "completed"
    assert "archived-output" in result.content
    updated = await manager.get_task(task.id)
    assert any(a.label.startswith("shell[") for a in updated.artifacts)
    assert any(e.kind == "shell_completed" for e in updated.timeline)


# --- task_stop: three branches -------------------------------------------------


async def test_task_stop_task_branch_cancels(tmp_path) -> None:
    manager = _task_manager(tmp_path)
    task = await manager.add_task(NewTaskRequest(prompt="durable work"))
    ctx = ToolContext(working_directory=tmp_path, task_manager=manager)

    result = await TaskStopTool().execute({"task_id": task.id}, ctx)

    assert result.metadata["status"] == "canceled"
    updated = await manager.get_task(task.id)
    assert updated.status is TaskStatus.CANCELED


async def test_task_stop_writes_stop_intent_for_workflow_detach(tmp_path) -> None:
    from deepseek_tui.workflow.detach import encode_detach_prompt
    from deepseek_tui.workflow.store import has_stop_intent

    run_id = "run_test_stop_intent"
    prompt = encode_detach_prompt(run_id=run_id, workspace=tmp_path)
    manager = _task_manager(tmp_path)
    task = await manager.add_task(NewTaskRequest(prompt=prompt))
    ctx = ToolContext(working_directory=tmp_path, task_manager=manager)

    result = await TaskStopTool().execute({"task_id": task.id}, ctx)

    assert result.metadata["status"] == "canceled"
    assert has_stop_intent(run_id, workspace=tmp_path)


async def test_task_stop_agent_branch_cancels_subagent(tmp_path) -> None:
    sub = _StubSubAgentManager()
    sub.results["agent_x1"] = _agent_result("agent_x1")
    ctx = ToolContext(working_directory=tmp_path, subagent_manager=sub)  # type: ignore[arg-type]

    result = await TaskStopTool().execute({"agent_id": "agent_x1"}, ctx)

    assert result.success is True
    assert sub.cancelled == ["agent_x1"]


def test_task_stop_approval_key_is_target_scoped() -> None:
    """Approving a stop for A must not green-light stopping B; the retired
    task_cancel name shares the fingerprint (execution-layer forwarding)."""
    key_a = build_approval_key("task_stop", {"task_id": "a1"})
    assert key_a != build_approval_key("task_stop", {"task_id": "b2"})
    assert key_a != build_approval_key("task_stop", {"agent_id": "a1"})
    assert key_a == build_approval_key("task_cancel", {"task_id": "a1"})
    assert build_approval_key("task_stop", {"process_id": "p1"}) != key_a


# --- task_create: resume parameter ----------------------------------------------


async def test_task_create_resume_requeues_same_id(tmp_path) -> None:
    manager = _task_manager(tmp_path)
    task = await manager.add_task(NewTaskRequest(prompt="durable work"))
    ctx = ToolContext(working_directory=tmp_path, task_manager=manager)
    await manager.cancel_task(task.id)

    result = await TaskCreateTool().execute({"resume": task.id}, ctx)

    assert result.metadata["task_id"] == task.id
    assert result.metadata["status"] == "queued"
    assert len(manager._tasks) == 1  # noqa: SLF001 — no duplicate created


async def test_task_create_resume_and_prompt_are_mutually_exclusive(tmp_path) -> None:
    ctx = ToolContext(
        working_directory=tmp_path, task_manager=_task_manager(tmp_path)
    )
    with pytest.raises(ToolError, match="mutually exclusive"):
        await TaskCreateTool().execute(
            {"resume": "task_x", "prompt": "new work"}, ctx
        )


async def test_task_create_requires_prompt_or_resume(tmp_path) -> None:
    ctx = ToolContext(
        working_directory=tmp_path, task_manager=_task_manager(tmp_path)
    )
    with pytest.raises(ToolError, match="prompt"):
        await TaskCreateTool().execute({}, ctx)


# --- agent tool: narrowed action set ---------------------------------------------


def test_agent_action_enum_is_narrowed() -> None:
    from deepseek_tui.tools.subagent import PLAN_AGENT_ACTIONS

    schema = AgentTool().input_schema()
    assert schema["properties"]["action"]["enum"] == [
        "spawn",
        "send_input",
        "wait",
    ]
    # Params of the retired actions are gone from the schema.
    for retired_param in ("process_id", "block", "include_archived"):
        assert retired_param not in schema["properties"]

    plan_schema = AgentTool(
        allowed_actions=PLAN_AGENT_ACTIONS, allow_resume=False
    ).input_schema()
    assert plan_schema["properties"]["action"]["enum"] == ["wait"]
    assert "resume" not in plan_schema["properties"]
