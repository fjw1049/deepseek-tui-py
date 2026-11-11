from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from deepseek_tui.automation.permissions import (
    AutomationBrowser,
    browser_grant,
    browser_grant_valid,
    set_browser_permission,
)
from deepseek_tui.config.models import Config
from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.routes import automations_router
from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.tools.approval import ExecPolicyEngine
from deepseek_tui.tools.automation import (
    AutomationManager,
    CreateAutomationRequest,
    UpdateAutomationRequest,
)
from deepseek_tui.tools.browser import BrowserUseTool
from deepseek_tui.tools.registry import ToolContext, ToolRegistry
from deepseek_tui.tools.task import NewTaskRequest, TaskManager, TaskManagerConfig


def automation(tmp_path):
    manager = AutomationManager(tmp_path / "automations")
    record = manager.create_automation(
        CreateAutomationRequest(
            name="browser check",
            prompt="read the local test page",
            run_at="2027-01-01T00:00:00Z",
            cwds=[str(tmp_path)],
        )
    )
    return manager, record


async def test_user_http_grant_model_update_revocation_and_cold_task_store(tmp_path):
    manager, record = automation(tmp_path)
    runtime = AppRuntime(config=Config(), tool_runtime=SimpleNamespace(automation_manager=manager))
    app = FastAPI()
    app.state.runtime = runtime
    app.include_router(automations_router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://local"
    ) as client:
        path = f"/v1/automations/{record.id}/permissions"
        assert (await client.get(path)).json() == {"allow_browser": False}
        # Ordinary CRUD, also used by model tooling, cannot grant authority.
        await runtime.update_automation(record.id, {"allow_browser": True})
        assert browser_grant(manager.automations_dir, record.id) is None
        assert (await client.put(path, json={"allow_browser": True})).json()["allow_browser"]
        granted = browser_grant(manager.automations_dir, record.id)
        assert browser_grant_valid(granted)
        cfg = TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path)
        tasks = TaskManager(cfg)
        task = await tasks.add_task(NewTaskRequest(prompt="queued", browser_grant=granted))
        await tasks.cancel_task(task.id)
        await tasks.shutdown()
        tasks = TaskManager(cfg)
        await tasks.start()
        try:
            assert (await tasks.get_task(task.id)).browser_grant == granted
            await client.put(path, json={"allow_browser": False})
            assert not browser_grant_valid(granted)
            await client.put(path, json={"allow_browser": True})
            assert not browser_grant_valid(granted)  # old queued grants never revive
            granted = browser_grant(manager.automations_dir, record.id)
            manager.update_automation(record.id, UpdateAutomationRequest(prompt="different task"))
            assert not browser_grant_valid(granted)
            assert not (await client.get(path)).json()["allow_browser"]
            assert (await client.put(path, json={"allow_browser": "yes"})).status_code != 200
        finally:
            await tasks.shutdown()


async def test_revocation_is_checked_at_main_child_and_browser_execution(tmp_path):
    from deepseek_tui.tools.subagent.loop import _run_subagent_tool

    manager, record = automation(tmp_path)
    set_browser_permission(manager.automations_dir, record.id, True)
    grant = browser_grant(manager.automations_dir, record.id)
    scope = AutomationBrowser(tmp_path, "task_test", grant)
    parent = ToolContext(working_directory=tmp_path, metadata={"cron_restricted": True})
    child = ToolContext(
        working_directory=tmp_path, metadata={"cron_restricted": True}, mutation_agent_id="child"
    )
    scope.bind(parent)
    scope.bind(child)
    assert parent.metadata["runtime_thread_id"] != child.metadata["runtime_thread_id"]
    scope.service.action = AsyncMock(return_value={"success": True, "content": "read local page"})
    registry = ToolRegistry(parent)
    registry.register(BrowserUseTool())
    engine = Engine(
        handle=EngineHandle(),
        client=AsyncMock(),
        tool_context=parent,
        tool_registry=registry,
        exec_policy=ExecPolicyEngine(approval_policy="auto"),
        approval_handler=AutoApprovalHandler(),
    )
    call = ToolCall(id="click", name="browser_use", arguments={"action": "click", "ref": "e1"})
    result = await engine._execute_single_tool_impl(call, [], "test")
    assert result.success
    set_browser_permission(manager.automations_dir, record.id, False)
    result = await engine._execute_single_tool_impl(call, [], "test")
    assert not result.success and result.metadata["needs_assistance"]
    ok, _ = await _run_subagent_tool(
        registry, child, tool_name="browser_use", tool_input={"action": "status"}, auto_approve=True
    )
    assert not ok
    assert not (await BrowserUseTool().execute({"action": "status"}, parent)).success
    assert scope.service.action.await_count == 1
    await scope.close()


async def test_unattended_cua_never_initializes_native_session(tmp_path):
    context = ToolContext(working_directory=tmp_path, metadata={"cron_restricted": True})
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=context)
    engine._app_config = Config()
    engine._app_config.cua.enabled = True
    await engine._prepare_cua()
    assert engine._cua_session is None


@pytest.mark.parametrize(
    "value", [None, {}, {"grant_path": []}, {"grant_path": "/nonexistent", "revision": "fake"}]
)
def test_invalid_grants_fail_closed(value):
    assert not browser_grant_valid(value)
