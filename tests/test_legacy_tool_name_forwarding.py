"""Execution-layer forwarding of retired tool names.

``agent_resume`` and ``exec_shell_interact`` are no longer registered or
advertised in the schema; the execution layer forwards calls under the old
names onto the merged tools (debug-logged) for one deprecation cycle. Same
for the Phase B task-surface consolidation: ``task_read`` / ``task_cancel``
/ ``task_resume`` / ``task_shell_start`` / ``task_shell_wait`` and the
retired ``agent`` list/result/cancel actions forward onto the unified
``task_create`` / ``task_list`` / ``task_output`` / ``task_stop`` tools.
"""

from __future__ import annotations

import pytest

from deepseek_tui.engine.dispatch import normalize_legacy_tool_call
from deepseek_tui.tools.registry import ToolContext, ToolRegistry
from deepseek_tui.tools.shell import ExecShellTool, wait_background_process
from deepseek_tui.tools.subagent import AgentTool
from deepseek_tui.tools.subagent.types import (
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentType,
)


def test_agent_resume_name_forwards_to_agent_resume_param() -> None:
    name, args = normalize_legacy_tool_call("agent_resume", {"agent_id": "a1"})
    assert name == "agent"
    assert args == {"resume": "a1"}


def test_agent_resume_forwarding_accepts_legacy_id_alias() -> None:
    name, args = normalize_legacy_tool_call("agent_resume", {"id": "a1"})
    assert name == "agent"
    assert args == {"resume": "a1"}


def test_agent_resume_forwarding_tolerates_non_dict_arguments() -> None:
    name, args = normalize_legacy_tool_call("agent_resume", None)
    assert name == "agent"
    assert args == {}


def test_exec_shell_interact_name_forwards_with_same_arguments() -> None:
    original = {"process_id": "p1", "input": "x\n", "close_stdin": True}
    name, args = normalize_legacy_tool_call("exec_shell_interact", original)
    assert name == "exec_shell"
    assert args == original


def test_unrelated_tool_names_pass_through() -> None:
    name, args = normalize_legacy_tool_call("agent", {"action": "wait"})
    assert name == "agent"
    assert args == {"action": "wait"}


# --- Phase B: unified task surface (task 8 → 4) ------------------------------


def test_task_read_forwards_to_task_output() -> None:
    name, args = normalize_legacy_tool_call("task_read", {"task_id": "t1"})
    assert name == "task_output"
    assert args == {"task_id": "t1"}


def test_task_cancel_forwards_to_task_stop() -> None:
    name, args = normalize_legacy_tool_call("task_cancel", {"task_id": "t1"})
    assert name == "task_stop"
    assert args == {"task_id": "t1"}


def test_task_resume_forwards_to_task_create_resume() -> None:
    name, args = normalize_legacy_tool_call("task_resume", {"task_id": "t1"})
    assert name == "task_create"
    assert args == {"resume": "t1"}
    # Legacy id alias works too.
    name, args = normalize_legacy_tool_call("task_resume", {"id": "t2"})
    assert name == "task_create"
    assert args == {"resume": "t2"}


def test_task_shell_wait_forwards_to_task_output_blocking() -> None:
    """task_shell_wait always blocked — the forwarded call keeps that."""
    name, args = normalize_legacy_tool_call(
        "task_shell_wait", {"process_id": "p1", "task_id": "t1"}
    )
    assert name == "task_output"
    assert args == {"process_id": "p1", "task_id": "t1", "block": True}


def test_task_shell_start_forwards_to_exec_shell_background() -> None:
    """The task_id → process_id ownership mapping is dropped on forwarding."""
    name, args = normalize_legacy_tool_call(
        "task_shell_start", {"task_id": "t1", "command": "make", "pty": False}
    )
    assert name == "exec_shell"
    assert args == {"command": "make", "pty": False, "background": True}


def test_task_gate_run_is_not_forwarded() -> None:
    """D3: the gate heuristic survives only in the implementation layer."""
    name, args = normalize_legacy_tool_call(
        "task_gate_run", {"gate": "test", "command": "pytest"}
    )
    assert name == "task_gate_run"
    assert args == {"gate": "test", "command": "pytest"}


def test_agent_list_action_forwards_to_task_list() -> None:
    name, args = normalize_legacy_tool_call("agent", {"action": "list"})
    assert name == "task_list"
    assert args == {}


def test_agent_result_action_forwards_to_task_output() -> None:
    name, args = normalize_legacy_tool_call(
        "agent",
        {"action": "result", "agent_id": "a1", "block": True, "timeout_ms": 5000},
    )
    assert name == "task_output"
    assert args == {"agent_id": "a1", "block": True, "timeout_ms": 5000}
    # process_id branch forwards too.
    name, args = normalize_legacy_tool_call(
        "agent", {"action": "result", "process_id": "p1"}
    )
    assert name == "task_output"
    assert args == {"process_id": "p1"}


def test_agent_result_with_wait_mode_is_not_forwarded() -> None:
    """Multi-id wait_mode calls were never valid for 'result' — the
    unknown-action steering error is more helpful than a wrong forward."""
    original = {"action": "result", "agent_ids": ["a1"], "wait_mode": "all"}
    name, args = normalize_legacy_tool_call("agent", original)
    assert name == "agent"
    assert args == original


def test_agent_cancel_action_forwards_to_task_stop() -> None:
    name, args = normalize_legacy_tool_call(
        "agent", {"action": "cancel", "agent_id": "a1"}
    )
    assert name == "task_stop"
    assert args == {"agent_id": "a1"}
    name, args = normalize_legacy_tool_call(
        "agent", {"action": "cancel", "process_id": "p1"}
    )
    assert name == "task_stop"
    assert args == {"process_id": "p1"}


def test_agent_live_actions_pass_through() -> None:
    for action in ("spawn", "wait", "send_input"):
        original = {"action": action, "agent_id": "a1"}
        name, args = normalize_legacy_tool_call("agent", original)
        assert name == "agent"
        assert args == original


def test_automation_create_forwards_to_cron_create() -> None:
    original = {"name": "n", "prompt": "p", "schedule": "0 * * * *"}
    name, args = normalize_legacy_tool_call("automation_create", original)
    assert name == "cron_create"
    assert args == original


def test_automation_list_and_read_forward_to_cron_list() -> None:
    name, args = normalize_legacy_tool_call("automation_list", {"limit": 5})
    assert name == "cron_list"
    assert args == {"limit": 5}
    name, args = normalize_legacy_tool_call(
        "automation_read", {"automation_id": "a1"}
    )
    assert name == "cron_list"
    assert args == {"automation_id": "a1"}


def test_automation_delete_forwards_to_cron_delete() -> None:
    name, args = normalize_legacy_tool_call(
        "automation_delete", {"automation_id": "a1"}
    )
    assert name == "cron_delete"
    assert args == {"automation_id": "a1"}


def test_retired_automation_mutations_are_not_forwarded() -> None:
    """update/pause/resume/run have no cron_* equivalent — the unknown-tool
    error steers the model onto cron_create/cron_delete instead."""
    for legacy in (
        "automation_update",
        "automation_pause",
        "automation_resume",
        "automation_run",
    ):
        name, args = normalize_legacy_tool_call(legacy, {"automation_id": "a1"})
        assert name == legacy
        assert args == {"automation_id": "a1"}


class _StubManager:
    def __init__(self) -> None:
        self.resumed: list[str] = []

    async def resume(self, agent_id: str) -> SubAgentResult:
        self.resumed.append(agent_id)
        return SubAgentResult(
            agent_id=agent_id,
            agent_type=SubAgentType.GENERAL,
            assignment=SubAgentAssignment(objective="obj"),
            model="m",
            nickname=None,
            status=SubAgentStatus.running(),
            result=None,
            steps_taken=0,
            duration_ms=0,
        )


@pytest.mark.asyncio
async def test_forwarded_agent_resume_executes(tmp_path) -> None:
    """A legacy agent_resume call, after normalization, runs the merged
    tool's resume logic against the registry."""
    manager = _StubManager()
    ctx = ToolContext(working_directory=tmp_path, subagent_manager=manager)  # type: ignore[arg-type]
    registry = ToolRegistry()
    registry.register(AgentTool())

    name, args = normalize_legacy_tool_call("agent_resume", {"agent_id": "a1"})
    result = await registry.execute(name, args, ctx)

    assert result.success is True
    assert result.content == "resumed a1"
    assert manager.resumed == ["a1"]


@pytest.mark.asyncio
async def test_forwarded_exec_shell_interact_executes(tmp_path) -> None:
    """A legacy exec_shell_interact call, after normalization, writes to the
    background process's stdin via the merged exec_shell tool."""
    ctx = ToolContext(working_directory=tmp_path)
    registry = ToolRegistry()
    registry.register(ExecShellTool())

    spawned = await registry.execute(
        "exec_shell", {"command": "cat", "background": True}, ctx
    )
    pid = spawned.content

    name, args = normalize_legacy_tool_call(
        "exec_shell_interact",
        {"process_id": pid, "input": "hi\n", "close_stdin": True},
    )
    sent = await registry.execute(name, args, ctx)
    assert sent.success is True

    collected = await wait_background_process(ctx, pid)
    assert collected.content == "hi"
