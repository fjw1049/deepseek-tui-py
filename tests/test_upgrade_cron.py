"""Unattended authority is enforced at dispatch, including child agents."""

from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.tool_profiles import filter_tools_for_profile
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.approval import ExecPolicyEngine
from deepseek_tui.tools.file import WriteFileTool
from deepseek_tui.tools.registry import ToolContext, ToolError, ToolRegistry


def test_cron_catalog_does_not_trust_server_hints():
    names = [
        "write_file",
        "exec_shell",
        "agent",
        "task_output",
        "browser_use",
        "cua_js",
        "request_user_input",
        "mcp_remote_read",
        "mcp_remote_write",
    ]
    catalog = [{"type": "function", "function": {"name": name}} for name in names]
    visible = filter_tools_for_profile(catalog, "cron", trusted_mcp_tools=("mcp_remote_read",))
    assert [tool["function"]["name"] for tool in visible] == names[:4] + ["mcp_remote_read"]


@pytest.mark.parametrize(
    "name",
    [
        "browser_use",
        "cua_js",
        "mcp_remote_write",
        "request_user_input",
        "task_create",
        "exit_plan_mode",
    ],
)
async def test_forged_cron_tool_calls_are_blocked(tmp_path, name):
    context = ToolContext(
        working_directory=tmp_path, metadata={"cron_restricted": True, "unattended": True}
    )
    engine = Engine(
        handle=EngineHandle(),
        client=AsyncMock(),
        tool_context=context,
        exec_policy=ExecPolicyEngine(approval_policy="auto"),
        approval_handler=AutoApprovalHandler(),
    )
    result = await engine._execute_single_tool_impl(
        ToolCall(id="call", name=name, arguments={}), [], "test"
    )
    assert not result.success and result.metadata["needs_assistance"]["tool"] == name


async def test_cron_workspace_write_succeeds_but_outside_path_needs_person(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    context = ToolContext(
        working_directory=workspace, metadata={"cron_restricted": True, "unattended": True}
    )
    engine = Engine(
        handle=EngineHandle(),
        client=AsyncMock(),
        tool_context=context,
        tool_registry=registry,
        exec_policy=ExecPolicyEngine(approval_policy="auto"),
        approval_handler=AutoApprovalHandler(),
    )
    result = await engine._execute_single_tool_impl(
        ToolCall(
            id="write", name="write_file", arguments={"path": "report.txt", "content": "completed"}
        ),
        [],
        "test",
    )
    assert result.success and (workspace / "report.txt").read_text() == "completed"
    result = await engine._execute_single_tool_impl(
        ToolCall(
            id="outside",
            name="write_file",
            arguments={"path": str(tmp_path / "outside.txt"), "content": "blocked"},
        ),
        [],
        "test",
    )
    assert not result.success and not (tmp_path / "outside.txt").exists()


async def test_child_cannot_bypass_unattended_gate(tmp_path):
    from deepseek_tui.tools.subagent.loop import _run_subagent_tool

    context = ToolContext(working_directory=tmp_path, metadata={"cron_restricted": True})
    ok, message = await _run_subagent_tool(
        ToolRegistry(), context, tool_name="browser_use", tool_input={}, auto_approve=True
    )
    assert not ok and "Human assistance" in message


@pytest.mark.parametrize("pty", [False, True])
async def test_cron_shell_refuses_unconfined_execution(tmp_path, pty):
    from deepseek_tui.policy.sandbox import resolve_execution_sandbox_policy
    from deepseek_tui.tools.shell import ExecShellTool

    context = ToolContext(
        working_directory=tmp_path, trust_mode=True, metadata={"cron_restricted": True}
    )
    context.execution_sandbox_policy = resolve_execution_sandbox_policy(
        "agent",
        tmp_path,
        trust_mode=True,
        sandbox_mode="danger-full-access",
        approval_policy="auto",
    )
    with pytest.raises(ToolError, match="OS sandbox"):
        await ExecShellTool().execute({"command": "touch forbidden", "pty": pty}, context)
    assert not (tmp_path / "forbidden").exists()


async def test_cron_child_does_not_inherit_parent_outside_write_trust(tmp_path):
    from deepseek_tui.tools.subagent.loop import _run_subagent_tool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    context = ToolContext(
        working_directory=workspace, trust_mode=True, metadata={"cron_restricted": True}
    )
    ok, message = await _run_subagent_tool(
        registry,
        context,
        tool_name="write_file",
        tool_input={"path": str(tmp_path / "outside.txt"), "content": "forbidden"},
        auto_approve=True,
    )
    assert not ok and "Human assistance" in message
    assert not (tmp_path / "outside.txt").exists()
