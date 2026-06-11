from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.capabilities.goal import (
    attach_goal_legacy_bindings,
    bind_goal_runtime_thread,
    build_goal_follow_up_start_payload,
    create_goal_runtime,
    fail_goal_turn,
    finish_goal_turn,
    goal_follow_up_is_stale,
    goal_mode_hint,
    goal_status_payload,
    rebind_goal_thread_if_local,
    should_dispatch_goal_follow_up,
    start_goal_turn,
    take_valid_goal_follow_up,
    validate_goal_follow_up,
)
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.goal.controller import GoalController
from deepseek_tui.goal.tools import GOAL_CONTROLLER_KEY
from deepseek_tui.host.services import ServiceRegistry


def test_goal_capability_creates_controller_and_legacy_bindings(
    tmp_path: Path,
) -> None:
    services = ServiceRegistry()

    runtime = create_goal_runtime(
        services,
        workspace=tmp_path,
        thread_id="thread-1",
    )
    metadata: dict[str, object] = {}
    attach_goal_legacy_bindings(runtime, metadata=metadata, services=services)

    assert runtime.controller.thread_id == "thread-1"
    assert runtime.controller.workspace == tmp_path.resolve()
    assert metadata[GOAL_CONTROLLER_KEY] is runtime.controller
    assert services.require(GoalController) is runtime.controller
    assert services.require_named(GOAL_CONTROLLER_KEY) is runtime.controller


def test_goal_capability_allows_existing_service(tmp_path: Path) -> None:
    services = ServiceRegistry()
    first = create_goal_runtime(services, workspace=tmp_path, thread_id="first")
    second = create_goal_runtime(services, workspace=tmp_path, thread_id="second")

    assert first.controller.thread_id == "first"
    assert second.controller.thread_id == "second"
    assert services.require(GoalController) is first.controller


def test_goal_capability_rebinds_only_local_thread(tmp_path: Path) -> None:
    controller = GoalController(tmp_path, "default")

    rebind_goal_thread_if_local(
        controller,
        metadata={},
        thread_id="cycle-thread",
    )
    assert controller.thread_id == "cycle-thread"

    rebind_goal_thread_if_local(
        controller,
        metadata={"runtime_thread_id": "runtime-thread"},
        thread_id="other-cycle-thread",
    )
    assert controller.thread_id == "cycle-thread"


def test_goal_capability_binds_runtime_thread(tmp_path: Path) -> None:
    controller = GoalController(tmp_path, "default")
    changed = False

    def _on_change() -> None:
        nonlocal changed
        changed = True

    bind_goal_runtime_thread(
        controller,
        thread_id="runtime-thread",
        journal_path=tmp_path / "goal.jsonl",
        on_change=_on_change,
    )

    assert controller.thread_id == "runtime-thread"
    controller.create("ship goal")
    assert changed is True


def test_goal_capability_lifecycle_helpers(tmp_path: Path) -> None:
    controller = GoalController(tmp_path, "thread-1")

    assert "No active goal" in goal_mode_hint("goal", controller)
    assert goal_mode_hint("agent", controller) == ""
    assert validate_goal_follow_up(controller, None) is True
    assert should_dispatch_goal_follow_up(object(), metadata={}) is True
    assert (
        should_dispatch_goal_follow_up(
            object(),
            metadata={"runtime_thread_id": "thread-1"},
        )
        is False
    )

    start_goal_turn(controller)
    result = finish_goal_turn(
        controller,
        turn_ok=True,
        usage=None,
        failure_reason="failed",
    )
    assert result.steer is None
    fail_goal_turn(controller, "failed")


def test_goal_capability_status_payload_and_follow_up(tmp_path: Path) -> None:
    controller = GoalController(tmp_path, "thread-1")
    assert goal_status_payload(controller) == {"goal": None}

    controller.create("x" * 150, token_budget=1000)
    payload = goal_status_payload(controller)
    goal = payload["goal"]
    assert isinstance(goal, dict)
    assert goal["objective"] == "x" * 120
    assert goal["token_budget"] == 1000

    follow_up = take_valid_goal_follow_up(controller)
    assert follow_up is not None
    assert take_valid_goal_follow_up(controller) is None


def test_goal_capability_follow_up_start_payload(tmp_path: Path) -> None:
    controller = GoalController(tmp_path, "thread-1")
    goal = controller.create("ship goal", token_budget=1000)

    follow_up = take_valid_goal_follow_up(controller)
    assert follow_up is not None
    assert not goal_follow_up_is_stale(
        controller,
        internal_kind="goal_follow_up",
        goal_id=goal.goal_id,
    )
    assert goal_follow_up_is_stale(
        controller,
        internal_kind="goal_follow_up",
        goal_id="stale-goal",
    )
    assert goal_follow_up_is_stale(
        None,
        internal_kind="goal_follow_up",
        goal_id=goal.goal_id,
    )
    assert not goal_follow_up_is_stale(
        controller,
        internal_kind=None,
        goal_id=None,
    )

    payload = build_goal_follow_up_start_payload(
        follow_up,
        model="deepseek-chat",
        mode="goal",
    )

    assert payload.as_dict() == {
        "prompt": follow_up.content,
        "input_summary": "Goal continuation",
        "model": "deepseek-chat",
        "mode": "goal",
        "hidden": True,
        "internal_kind": "goal_follow_up",
        "goal_id": goal.goal_id,
    }


@pytest.mark.asyncio
async def test_engine_create_goal_uses_capability_bindings(tmp_path: Path) -> None:
    engine = await Engine.create(
        handle=EngineHandle(),
        client=AsyncMock(),
        config=Config(features=FeatureConfig(mcp=False, tasks=False, subagents=False)),
        working_directory=tmp_path,
        start_mcp=False,
    )
    try:
        assert isinstance(engine.goal_controller, GoalController)
        assert engine.tool_context.metadata[GOAL_CONTROLLER_KEY] is engine.goal_controller
        assert engine.tool_context.services.require(GoalController) is engine.goal_controller
        assert engine.tool_context.services.require_named(GOAL_CONTROLLER_KEY) is (
            engine.goal_controller
        )
    finally:
        await engine.shutdown_session()
