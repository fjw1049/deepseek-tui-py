"""Engine-owned lifecycle observer registration at capability attach time."""

from __future__ import annotations


def _lifecycle_observer_registered(registry: object, observer_id: str) -> bool:
    return any(
        registration.id == observer_id
        for registration in registry.registrations()  # type: ignore[attr-defined]
    )


def register_engine_lifecycle_observers(engine: object) -> None:
    """Register dynamic engine-owned lifecycle observers once after attach."""
    registry = engine.lifecycle_registry  # type: ignore[attr-defined]
    tool_context = engine.tool_context  # type: ignore[attr-defined]

    if not _lifecycle_observer_registered(registry, "lsp.after_tool"):
        from deepseek_tui.capabilities.lsp import (
            lsp_manager_from_context,
            lsp_tool_observer,
        )

        registry.add(
            id="lsp.after_tool",
            owner="lsp",
            order=50,
            observer=lsp_tool_observer(
                manager=lambda: lsp_manager_from_context(
                    services=tool_context.services,
                ),
                workspace=lambda: tool_context.working_directory,
                turn_counter=lambda: engine.turn_counter,  # type: ignore[attr-defined]
                add_pending_blocks=engine.pending_lsp_blocks.extend,  # type: ignore[attr-defined]
            ),
        )

    if not _lifecycle_observer_registered(registry, "memory.before_turn"):
        from deepseek_tui.capabilities.memory import dynamic_memory_before_turn_observer

        registry.add(
            id="memory.before_turn",
            owner="memory",
            order=100,
            observer=dynamic_memory_before_turn_observer(
                coordinator=lambda: engine.memory_coordinator,  # type: ignore[attr-defined]
                memory_thread_id=lambda: engine.memory_thread_id,  # type: ignore[attr-defined]
                cycle_session_id=lambda: engine._cycle_session_id,  # type: ignore[attr-defined]
                memory_mode=lambda: engine.memory_mode,  # type: ignore[attr-defined]
            ),
        )

    if not _lifecycle_observer_registered(registry, "post_turn.after_tool"):
        from deepseek_tui.capabilities.post_turn import dynamic_post_turn_tool_observer

        registry.add(
            id="post_turn.after_tool",
            owner="post_turn",
            order=100,
            observer=dynamic_post_turn_tool_observer(lambda: engine.post_turn),  # type: ignore[attr-defined]
        )

    if not _lifecycle_observer_registered(registry, "goal.lifecycle"):
        from deepseek_tui.capabilities.goal import goal_lifecycle_observer

        registry.add(
            id="goal.lifecycle",
            owner="goal",
            order=200,
            observer=goal_lifecycle_observer(lambda: engine.goal_controller),  # type: ignore[attr-defined]
        )
