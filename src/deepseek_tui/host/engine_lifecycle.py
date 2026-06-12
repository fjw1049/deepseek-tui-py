"""Engine-owned lifecycle observer registration at capability attach time."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.engine.engine import Engine
    from deepseek_tui.tools.context import ToolContext


@dataclass(frozen=True, slots=True)
class EngineLifecycleAccess:
    """Narrow live view exposed to engine lifecycle capability adapters."""

    tool_context: ToolContext
    turn_counter: Callable[[], int]
    pending_lsp_blocks: list[object]
    memory_coordinator: Callable[[], object | None]
    memory_thread_id: Callable[[], str | None]
    cycle_session_id: Callable[[], str | None]
    memory_mode: Callable[[], str | None]
    post_turn: Callable[[], object | None]
    goal_controller: Callable[[], object | None]

    @classmethod
    def from_engine(cls, engine: Engine) -> EngineLifecycleAccess:
        return cls(
            tool_context=engine.tool_context,
            turn_counter=lambda: engine.turn_counter,
            pending_lsp_blocks=engine.pending_lsp_blocks,
            memory_coordinator=lambda: engine.memory_coordinator,
            memory_thread_id=lambda: engine.memory_thread_id,
            cycle_session_id=lambda: engine._cycle_session_id,
            memory_mode=lambda: engine.memory_mode,
            post_turn=lambda: engine.post_turn,
            goal_controller=lambda: engine.goal_controller,
        )


def register_engine_lifecycle_observers(engine: Engine) -> None:
    """Register dynamic engine-owned lifecycle observers once after attach."""
    from deepseek_tui.capabilities import goal, lsp, memory, post_turn

    registry = engine.lifecycle_registry
    access = EngineLifecycleAccess.from_engine(engine)
    lsp.register_engine_lifecycle_observer(access, registry)
    memory.register_engine_lifecycle_observer(access, registry)
    post_turn.register_engine_lifecycle_observer(access, registry)
    goal.register_engine_lifecycle_observer(access, registry)
