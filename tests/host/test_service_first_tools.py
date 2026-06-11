from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deepseek_tui.capabilities.rlm import rlm_tool_bindings
from deepseek_tui.capabilities.workflow import workflow_tool_bindings
from deepseek_tui.evolution.constants import (
    CURATED_MEMORY_STORE_KEY,
    EVOLUTION_LEDGER_KEY,
    SKILL_STORE_KEY,
)
from deepseek_tui.goal.controller import GoalController
from deepseek_tui.goal.tools import GOAL_CONTROLLER_KEY, goal_controller_from_context
from deepseek_tui.hooks.executor import HookContext, HookExecutor
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.memory.native.provider import NativeMemoryProvider
from deepseek_tui.tools.automation_manager import AutomationManager
from deepseek_tui.tools.automation_tools import AUTOMATION_MANAGER_KEY, _get_manager
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.mcp_tools import MCP_MANAGER_KEY, _manager
from deepseek_tui.tools.memory_curate_tool import _store_from_context as curated_store_from_context
from deepseek_tui.tools.memory_tools import MEMORY_PROVIDER_KEY, _require_provider
from deepseek_tui.tools.shell_tools import _shell_env_from_hooks
from deepseek_tui.tools.skill_manage_tool import _store_from_context as skill_store_from_context
from deepseek_tui.tools.subagent_tools import _require_manager as require_subagent_manager
from deepseek_tui.tools.task_manager import TaskManager, TaskManagerConfig
from deepseek_tui.tools.task_tools import _require_manager as require_task_manager
from deepseek_tui.tools.todo_tools import _task_manager_from_context


class _ServiceHookExecutor(HookExecutor):
    def has_hooks_for_event(self, event: str) -> bool:
        return event == "shell_env"

    async def collect_shell_env_async(self, context: HookContext) -> dict[str, str]:
        return {"SERVICE_HOOK": context.tool_name or ""}


def test_goal_tool_reads_controller_from_services(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    controller = GoalController(tmp_path, "thread-1")
    context.services.add(
        GoalController,
        controller,
        owner="test",
        scope="engine",
    )

    assert goal_controller_from_context(context) is controller
    assert GOAL_CONTROLLER_KEY not in context.metadata


def test_mcp_tool_reads_manager_from_services(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    manager = McpManager([])
    context.services.add_named(MCP_MANAGER_KEY, manager, owner="test", scope="engine")

    assert _manager(context) is manager


def test_memory_tool_reads_provider_from_services(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    provider = NativeMemoryProvider.__new__(NativeMemoryProvider)
    context.services.add_named(MEMORY_PROVIDER_KEY, provider, owner="test", scope="engine")

    assert _require_provider(context) is provider


def test_automation_tool_reads_manager_from_services(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    manager = AutomationManager.open(tmp_path / "automations")
    context.services.add(
        AutomationManager,
        manager,
        owner="test",
        scope="engine",
    )

    assert _get_manager(context) is manager
    assert AUTOMATION_MANAGER_KEY not in context.metadata


def test_task_tool_reads_manager_from_services(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    manager = TaskManager(
        TaskManagerConfig(
            data_dir=tmp_path / "tasks",
            default_workspace=tmp_path,
        )
    )
    context.services.add(TaskManager, manager, owner="test", scope="engine")

    assert require_task_manager(context) is manager
    assert "task_manager" not in context.metadata


def test_todo_tool_reads_task_manager_from_services(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    manager = TaskManager(
        TaskManagerConfig(
            data_dir=tmp_path / "tasks",
            default_workspace=tmp_path,
        )
    )
    context.services.add_named("task_manager", manager, owner="test", scope="engine")

    assert _task_manager_from_context(context) is manager
    assert "task_manager" not in context.metadata


def test_subagent_tool_reads_manager_from_services(tmp_path: Path) -> None:
    from deepseek_tui.tools.subagent import AgentRunOutput, SubAgent, SubAgentManager

    async def _executor(
        _agent: SubAgent,
        _cancel: asyncio.Event,
    ) -> AgentRunOutput:
        return AgentRunOutput(text="ok", structured=None)

    context = ToolContext(working_directory=tmp_path)
    manager = SubAgentManager(workspace=tmp_path, executor=_executor)
    context.services.add(type(manager), manager, owner="test", scope="engine")

    assert require_subagent_manager(context) is manager


@pytest.mark.asyncio
async def test_shell_tool_reads_hook_executor_from_services(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    executor = _ServiceHookExecutor.disabled()
    context.services.add(HookExecutor, executor, owner="test", scope="engine")

    env = await _shell_env_from_hooks(context, "echo hi")

    assert env is not None
    assert env["SERVICE_HOOK"] == "exec_shell"
    assert "hook_executor" not in context.metadata


def test_evolution_tools_read_stores_from_services(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    curated_store = object()
    skill_store = object()
    ledger = object()
    context.services.add_named(
        CURATED_MEMORY_STORE_KEY,
        curated_store,
        owner="test",
        scope="engine",
    )
    context.services.add_named(SKILL_STORE_KEY, skill_store, owner="test", scope="engine")
    context.services.add_named(EVOLUTION_LEDGER_KEY, ledger, owner="test", scope="engine")

    assert curated_store_from_context(context) is curated_store
    assert skill_store_from_context(context) is skill_store


def test_workflow_tool_bindings_are_scoped(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    emitted: list[object] = []

    with workflow_tool_bindings(
        context,
        cancel_event=asyncio.Event(),
        tool_call_id="tool-1",
        emit=lambda event: not emitted.append(event),
    ):
        assert context.metadata["workflow_tool_call_id"] == "tool-1"
        assert callable(context.metadata["workflow_emit"])
        assert callable(context.metadata["workflow_status_cb"])

    assert "engine_cancel_event" not in context.metadata
    assert "workflow_tool_call_id" not in context.metadata
    assert "workflow_emit" not in context.metadata
    assert "workflow_status_cb" not in context.metadata


def test_rlm_tool_bindings_are_scoped(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    emitted: list[object] = []

    with rlm_tool_bindings(context, emit=lambda event: not emitted.append(event)):
        callback = context.metadata["rlm_progress_cb"]
        assert callable(callback)
        callback(1, "summary", 2)

    assert "rlm_progress_cb" not in context.metadata
    assert len(emitted) == 1
    assert emitted[0].iteration == 1
    assert emitted[0].summary == "summary"
    assert emitted[0].rpc_count == 2
