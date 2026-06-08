from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.app_server.runtime_threads import (
    CreateThreadRequest,
    RuntimeThreadManagerConfig,
    StartTurnRequest,
)
from deepseek_tui.app_server.thread_manager import RuntimeThreadManager
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.goal.controller import GoalController
from deepseek_tui.tools.context import ToolContext


@pytest.mark.asyncio
async def test_start_turn_rejects_stale_goal_follow_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create(**kwargs: object) -> SimpleNamespace:
        workspace = Path(kwargs.get("working_directory", tmp_path))  # type: ignore[arg-type]
        controller = GoalController(workspace, "thr_test")
        controller.current = None
        ctx = ToolContext(working_directory=workspace)
        ctx.metadata["runtime_thread_id"] = "thr_test"
        return SimpleNamespace(
            goal_controller=controller,
            tool_context=ctx,
            mode="agent",
            run=AsyncMock(),
        )

    monkeypatch.setattr("deepseek_tui.engine.engine.Engine.create", fake_create)

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    mgr = RuntimeThreadManager(
        config=Config(
            features=FeatureConfig(mcp=False, tasks=False, subagents=False, automations=False)
        ),
        workspace=tmp_path,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tasks_dir),
        llm_client=object(),
    )
    thread = await mgr.create_thread(CreateThreadRequest())
    with pytest.raises(ValueError, match="stale"):
        await mgr.start_turn(
            thread.id,
            StartTurnRequest(
                prompt="stale follow-up",
                hidden=True,
                internal_kind="goal_follow_up",
                goal_id="goal_missing123",
            ),
        )
