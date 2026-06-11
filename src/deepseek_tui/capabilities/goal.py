"""Goal capability runtime wiring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepseek_tui.goal.controller import GoalController
from deepseek_tui.goal.tools import GOAL_CONTROLLER_KEY
from deepseek_tui.host.services import ServiceRegistry, ServiceScope

GOAL_TURN_RESULT_DECORATION = "goal.turn_result"


@dataclass(slots=True)
class GoalRuntime:
    controller: GoalController


@dataclass(slots=True)
class GoalTurnResult:
    follow_up: object | None
    steer: str | None


@dataclass(slots=True)
class GoalLifecycleObserver:
    controller: Callable[[], GoalController]

    async def on_turn_started(self, _context: object) -> None:
        self.controller().on_turn_start()

    async def on_turn_completed(self, context: object) -> None:
        controller = self.controller()
        follow_up = controller.on_turn_complete(
            context.usage,  # type: ignore[attr-defined]
        )
        context.decorations[GOAL_TURN_RESULT_DECORATION] = GoalTurnResult(  # type: ignore[attr-defined]
            follow_up=follow_up,
            steer=controller.take_pending_steer(),
        )

    async def on_turn_failed(self, context: object) -> None:
        controller = self.controller()
        controller.on_turn_failed(
            context.reason,  # type: ignore[attr-defined]
            context.usage,  # type: ignore[attr-defined]
        )
        context.decorations[GOAL_TURN_RESULT_DECORATION] = GoalTurnResult(  # type: ignore[attr-defined]
            follow_up=None,
            steer=controller.take_pending_steer(),
        )


@dataclass(slots=True)
class GoalFollowUpStartPayload:
    prompt: str
    input_summary: str
    model: str | None
    mode: str | None
    hidden: bool
    internal_kind: str
    goal_id: str

    def as_dict(self) -> dict[str, object | None]:
        return {
            "prompt": self.prompt,
            "input_summary": self.input_summary,
            "model": self.model,
            "mode": self.mode,
            "hidden": self.hidden,
            "internal_kind": self.internal_kind,
            "goal_id": self.goal_id,
        }


def create_goal_runtime(
    services: ServiceRegistry,
    *,
    workspace: Path,
    thread_id: str | None,
) -> GoalRuntime:
    controller = GoalController(
        workspace,
        thread_id or "default",
    )
    if services.optional(GoalController) is None:
        services.add(
            GoalController,
            controller,
            owner="goal",
            scope=ServiceScope.ENGINE,
        )
    return GoalRuntime(controller=controller)


def attach_engine_goal(engine: object) -> GoalController:
    """Create goal runtime and bind it on an Engine shell."""
    tool_context = engine.tool_context  # type: ignore[attr-defined]
    goal_thread_id = str(tool_context.metadata.get("runtime_thread_id") or "default")
    goal_runtime = create_goal_runtime(
        tool_context.services,
        workspace=tool_context.working_directory,
        thread_id=goal_thread_id,
    )
    engine.goal_controller = goal_runtime.controller  # type: ignore[attr-defined]
    attach_goal_bindings(goal_runtime, services=tool_context.services)
    return goal_runtime.controller


def attach_goal_bindings(
    runtime: GoalRuntime,
    *,
    services: ServiceRegistry,
) -> None:
    if services.optional_named(GOAL_CONTROLLER_KEY) is None:
        services.add_named(
            GOAL_CONTROLLER_KEY,
            runtime.controller,
            owner="goal",
            scope=ServiceScope.ENGINE,
        )
    if services.optional(GoalController) is None:
        services.add(
            GoalController,
            runtime.controller,
            owner="goal",
            scope=ServiceScope.ENGINE,
        )


def goal_lifecycle_observer(
    controller: Callable[[], GoalController],
) -> GoalLifecycleObserver:
    return GoalLifecycleObserver(controller=controller)


def rebind_goal_thread_if_local(
    controller: GoalController,
    *,
    metadata: dict[str, object],
    thread_id: str,
) -> None:
    if not metadata.get("runtime_thread_id"):
        controller.rebind(thread_id=thread_id)


def bind_goal_runtime_thread(
    controller: GoalController,
    *,
    thread_id: str,
    journal_path: Path,
    on_change: Callable[[], None],
) -> None:
    controller.rebind(thread_id=thread_id, journal_path=journal_path)
    controller._on_change = on_change


def goal_controller_from_engine(engine: object) -> GoalController | None:
    tool_context = getattr(engine, "tool_context", None)
    services = getattr(tool_context, "services", None)
    if services is not None:
        typed = services.optional(GoalController)
        if typed is not None:
            return typed
        named = services.optional_named(GOAL_CONTROLLER_KEY)
        if isinstance(named, GoalController):
            return named
    return None


def goal_mode_hint(mode: str, controller: GoalController) -> str:
    if mode != "goal" or controller.current is not None:
        return ""
    return (
        "\n\n[Turn hint] No active goal exists — use create_goal "
        "to establish an objective from the user's request, "
        "then proceed."
    )


def validate_goal_follow_up(controller: GoalController, goal_id: str | None) -> bool:
    if not goal_id:
        return True
    return controller.validate_follow_up(goal_id)


def start_goal_turn(controller: GoalController) -> None:
    controller.on_turn_start()


def fail_goal_turn(
    controller: GoalController,
    reason: str,
    usage: Any | None = None,
) -> None:
    controller.on_turn_failed(reason, usage)


def finish_goal_turn(
    controller: GoalController,
    *,
    turn_ok: bool,
    usage: Any | None,
    failure_reason: str,
) -> GoalTurnResult:
    follow_up = None
    if turn_ok:
        follow_up = controller.on_turn_complete(usage)
    else:
        controller.on_turn_failed(failure_reason, usage)
    return GoalTurnResult(
        follow_up=follow_up,
        steer=controller.take_pending_steer(),
    )


def should_dispatch_goal_follow_up(
    follow_up: object | None,
    *,
    metadata: dict[str, object],
) -> bool:
    return follow_up is not None and not metadata.get("runtime_thread_id")


def goal_status_payload(controller: GoalController) -> dict[str, object]:
    goal = controller.current
    if goal is None:
        return {"goal": None}
    return {
        "goal": {
            "goal_id": goal.goal_id,
            "objective": goal.objective[:120],
            "status": goal.status.value,
            "tokens_used": goal.usage.tokens_used,
            "token_budget": goal.token_budget,
            "active_seconds": round(goal.usage.active_seconds, 1),
        }
    }


def take_valid_goal_follow_up(controller: GoalController) -> object | None:
    follow_up = controller.take_pending_follow_up()
    if follow_up is None:
        return None
    if not controller.validate_follow_up(follow_up.goal_id):
        return None
    return follow_up


def goal_follow_up_is_stale(
    controller: object | None,
    *,
    internal_kind: str | None,
    goal_id: str | None,
) -> bool:
    if internal_kind != "goal_follow_up" or not goal_id:
        return False
    if controller is None or not hasattr(controller, "validate_follow_up"):
        return True
    return not bool(controller.validate_follow_up(goal_id))  # type: ignore[attr-defined]


def build_goal_follow_up_start_payload(
    follow_up: object,
    *,
    model: str | None,
    mode: str | None,
) -> GoalFollowUpStartPayload:
    return GoalFollowUpStartPayload(
        prompt=follow_up.content,  # type: ignore[attr-defined]
        input_summary="Goal continuation",
        model=model,
        mode=mode,
        hidden=True,
        internal_kind="goal_follow_up",
        goal_id=follow_up.goal_id,  # type: ignore[attr-defined]
    )
