"""Ask mode must stay read-only even with an agent-built shared registry."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config import Config
from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.orchestrator.helpers import _resolve_app_mode
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.approval import ExecPolicyEngine
from deepseek_tui.tools.registry import ToolContext, ToolError, build_default_registry


def test_ask_has_its_own_prompt_and_readonly_registry():
    mode = _resolve_app_mode("ask")
    assert mode.value == "ask"
    assert "Mode: Ask" in mode.mode_prompt()
    assert "exit_plan_mode" not in mode.approval_prompt()
    names = set(build_default_registry(Config(allow_shell=True), mode="ask").names())
    assert {"read_file", "file_search", "grep_files", "request_user_input"} <= names
    assert not names & {"write_file", "edit_file", "exec_shell", "agent", "task_create",
                        "task_stop", "cron_create", "cron_update", "cron_delete",
                        "update_plan", "checklist", "CreateGoal", "UpdateGoal",
                        "browser_use", "browser_skill", "enter_plan_mode", "exit_plan_mode"}


@pytest.mark.asyncio
async def test_switch_to_ask_blocks_stale_catalog_and_preserves_real_file(tmp_path):
    target = tmp_path / "example.txt"
    target.write_text("original", encoding="utf-8")
    registry = build_default_registry(Config(allow_shell=True))
    engine = Engine(
        handle=EngineHandle(), client=AsyncMock(), tool_registry=registry,
        tool_context=ToolContext(working_directory=tmp_path, trust_mode=True),
        exec_policy=ExecPolicyEngine(approval_policy="auto"),
        approval_handler=AutoApprovalHandler(),
    )
    stale_catalog = registry.to_api_tools()
    engine.mode = "ask"
    catalog = await engine._get_tools_with_mcp()
    assert "write_file" not in {tool["function"]["name"] for tool in catalog}
    note = next(tool["function"] for tool in catalog if tool["function"]["name"] == "note")
    assert note["parameters"]["properties"]["action"]["enum"] == ["read"]
    assert note["parameters"]["required"] == ["action"]
    assert "append" in registry.get("note").input_schema()["properties"]["action"]["enum"]
    # Even a call from the previous agent request cannot cross the mode boundary.
    for name, args in [
        ("write_file", {"path": "example.txt", "content": "overwritten"}),
        ("exec_shell", {"command": "touch should-not-exist"}),
        ("task_create", {"prompt": "modify files"}),
        ("enter_plan_mode", {}),
    ]:
        with pytest.raises(ToolError, match="ask mode"):
            await engine._execute_single_tool(ToolCall(id=name, name=name, arguments=args), stale_catalog, "test")
    result = await engine._execute_single_tool(
        ToolCall(id="read", name="read_file", arguments={"path": "example.txt"}), catalog, "test"
    )
    assert result is not None and result.success and "original" in result.content
    assert target.read_text() == "original"
    assert not (tmp_path / "should-not-exist").exists()


@pytest.mark.asyncio
async def test_plan_can_inspect_saved_automations_but_cannot_change_them(tmp_path):
    from deepseek_tui.config.models import FeatureConfig
    from deepseek_tui.tools.automation import AUTOMATION_MANAGER_KEY, AutomationManager, CreateAutomationRequest

    manager = AutomationManager.open(tmp_path / "automations")
    record = manager.create_automation(CreateAutomationRequest(name="Daily report", prompt="report", schedule="0 * * * *"))
    config = Config(features=FeatureConfig(automations=True))
    plan_registry = build_default_registry(config, mode="plan")
    assert "cron_list" in plan_registry.names()
    registry = build_default_registry(config)
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_registry=registry,
        tool_context=ToolContext(working_directory=tmp_path, metadata={AUTOMATION_MANAGER_KEY: manager}),
        exec_policy=ExecPolicyEngine(approval_policy="auto"), approval_handler=AutoApprovalHandler())
    engine.configure_interaction_mode("plan")
    tools = await engine._get_tools_with_mcp()
    read = await engine._execute_single_tool(ToolCall(id="list", name="cron_list", arguments={}), tools, "test")
    assert read.success and "Daily report" in read.content
    with pytest.raises(ToolError, match="plan mode"):
        await engine._execute_single_tool(ToolCall(id="delete", name="cron_delete", arguments={"automation_id": record.id}), registry.to_api_tools(), "test")
    assert manager.get_automation(record.id).name == "Daily report"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,enabled", [("ask", True), ("plan", True), ("agent", False)])
async def test_disabled_computer_use_closes_session_and_removes_tools(tmp_path, mode, enabled):
    from tests.engine.test_ui_task_turns import FakeDesktopTool

    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(working_directory=tmp_path))
    engine.mode = mode
    engine._app_config = SimpleNamespace(cua=SimpleNamespace(enabled=enabled))
    session = SimpleNamespace(instructions="", human_reserved=False, close=AsyncMock())
    engine._cua_session = session
    engine.tool_context.metadata["cua_session"] = session
    engine.tool_registry.register(FakeDesktopTool())
    assert engine._cua_surfaces() == frozenset()
    await engine._prepare_cua()
    session.close.assert_awaited_once()
    assert engine._cua_session is None
    assert engine._cua_prompt() == ""
    assert "cua_session" not in engine.tool_context.metadata
    assert "cua_js" not in engine.tool_registry.names()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ask", "plan"])
async def test_readonly_task_output_cannot_archive_process_output(tmp_path, mode):
    from deepseek_tui.tools.task import TaskManager, TaskManagerConfig, NewTaskRequest
    from deepseek_tui.tools.shell import ExecShellTool
    from deepseek_tui.tools.task.tools import TaskOutputTool

    manager = TaskManager(TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path))
    task = await manager.add_task(NewTaskRequest(prompt="inspect"))
    context = ToolContext(working_directory=tmp_path, task_manager=manager)
    shell_result = await ExecShellTool().execute({"command": "printf audit-output", "background": True}, context)
    process_id = shell_result.content
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_registry=build_default_registry(Config()),
                    tool_context=context)
    engine.mode = mode
    try:
        with pytest.raises(ToolError, match="Archiving"):
            await engine._execute_single_tool(ToolCall(id="archive", name="task_output", arguments={
                "task_id": task.id, "process_id": process_id, "block": True
            }), await engine._get_tools_with_mcp(), "test")
        assert not (await manager.get_task(task.id)).artifacts
        output = await TaskOutputTool().execute({"process_id": process_id, "block": True}, context)
        assert output.success and "audit-output" in output.content
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_private_registry_recovers_when_leaving_ask(tmp_path):
    config = Config(allow_shell=True)
    engine = Engine(handle=EngineHandle(), client=AsyncMock(),
                    tool_registry=build_default_registry(config),
                    tool_context=ToolContext(working_directory=tmp_path, trust_mode=True))
    engine._app_config = config
    engine._owns_tool_runtime = True
    engine.configure_interaction_mode("ask")
    assert engine.tool_context.execution_sandbox_policy.kind == "read-only"
    assert not engine.tool_registry.contains("write_file")
    engine.configure_interaction_mode("agent")
    result = await engine._execute_single_tool(
        ToolCall(id="write", name="write_file", arguments={"path": "restored.txt", "content": "restored"}),
        await engine._get_tools_with_mcp(), "test",
    )
    assert result is not None and result.success
    assert (tmp_path / "restored.txt").read_text() == "restored"


@pytest.mark.asyncio
async def test_leaving_yolo_restores_the_original_approval_handler(tmp_path):
    handler = AsyncMock()
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), approval_handler=handler,
                    tool_context=ToolContext(working_directory=tmp_path))
    await engine.apply_interaction_mode("yolo")
    assert engine.approval_handler is not handler
    await engine.apply_interaction_mode("ask")
    await engine.apply_interaction_mode("agent")
    assert engine.approval_handler is handler
