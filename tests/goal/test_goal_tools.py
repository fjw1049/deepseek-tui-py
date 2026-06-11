from __future__ import annotations

import json

import pytest

from deepseek_tui.goal.controller import GoalController
from deepseek_tui.goal.tools import CreateGoalTool, GetGoalTool, UpdateGoalTool
from deepseek_tui.host.services import ServiceScope
from deepseek_tui.tools.builder import build_default_registry
from deepseek_tui.tools.context import ToolContext


@pytest.mark.asyncio
async def test_goal_tools_share_attached_controller(tmp_path) -> None:
    controller = GoalController(tmp_path, "thread-a")
    context = ToolContext(working_directory=tmp_path)
    context.services.add(
        GoalController,
        controller,
        owner="test",
        scope=ServiceScope.ENGINE,
    )

    create = await CreateGoalTool().execute({"objective": "finish tests"}, context)
    assert create.success
    status = await GetGoalTool().execute({}, context)
    payload = json.loads(status.content)
    assert payload["goal"]["objective"] == "finish tests"

    complete = await UpdateGoalTool().execute({"status": "complete"}, context)
    assert complete.success
    assert json.loads(complete.content)["status"] == "complete"


def test_default_registry_includes_goal_tools() -> None:
    registry = build_default_registry()

    assert registry.contains("get_goal")
    assert registry.contains("create_goal")
    assert registry.contains("update_goal")
