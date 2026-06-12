from __future__ import annotations

import json

import pytest

from deepseek_tui.integrations.goal import GoalController
from deepseek_tui.integrations.goal import GOAL_CONTROLLER_KEY, CreateGoalTool, GetGoalTool, UpdateGoalTool
from deepseek_tui.tools.registry import build_default_registry
from deepseek_tui.tools.registry import ToolContext


@pytest.mark.asyncio
async def test_goal_tools_share_attached_controller(tmp_path) -> None:
    controller = GoalController(tmp_path, "thread-a")
    context = ToolContext(
        working_directory=tmp_path,
        metadata={GOAL_CONTROLLER_KEY: controller},
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
