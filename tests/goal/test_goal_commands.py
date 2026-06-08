from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle, GoalFollowUpOp
from deepseek_tui.tui.commands.handlers import _schedule_goal_follow_up


@pytest.mark.asyncio
async def test_schedule_goal_follow_up_enqueues_op(tmp_path) -> None:
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
        config=Config(),
        working_directory=tmp_path,
    )
    try:
        goal = engine.goal_controller.create("ship from command")
        sent: list[GoalFollowUpOp] = []

        async def capture_send_goal_follow_up(
            goal_id: str, content: str, model: str | None = None
        ) -> None:
            sent.append(GoalFollowUpOp(goal_id=goal_id, content=content, model=model))

        app = SimpleNamespace(
            _engine=engine,
            handle=SimpleNamespace(send_goal_follow_up=capture_send_goal_follow_up),
            config=Config(model="deepseek-chat"),
            run_worker=lambda coro, **_: asyncio.get_running_loop().create_task(coro),
            _listen_events=AsyncMock(),
        )

        _schedule_goal_follow_up(app)  # type: ignore[arg-type]
        await asyncio.sleep(0)

        assert len(sent) == 1
        assert sent[0].goal_id == goal.goal_id
        assert engine.goal_controller.take_pending_follow_up() is None
    finally:
        await engine.shutdown_session()


@pytest.mark.asyncio
async def test_turn_complete_plans_follow_up_for_active_goal(tmp_path) -> None:
    from deepseek_tui.protocol.responses import Usage

    engine = await Engine.create(
        handle=EngineHandle(),
        client=AsyncMock(),
        config=Config(),
        working_directory=tmp_path,
    )
    try:
        controller = engine.goal_controller
        controller.create("active goal")
        controller.on_turn_start()
        follow_up = controller.on_turn_complete(Usage(input_tokens=3, output_tokens=2))
        assert follow_up is not None
        assert follow_up.goal_id == controller.current.goal_id
    finally:
        await engine.shutdown_session()
