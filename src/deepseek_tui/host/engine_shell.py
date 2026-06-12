"""Narrow host contract for engine-scoped capability attach.

Capability adapters receive :class:`EngineShell` instead of the full
:class:`~deepseek_tui.engine.engine.Engine` so attach code depends on explicit
slots rather than arbitrary engine internals.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from deepseek_tui.host.lifecycle import LifecycleRegistry
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from deepseek_tui.engine.engine import Engine
    from deepseek_tui.engine.handle import ApprovalHandler, EngineHandle
    from deepseek_tui.tools.subagent.completion import SubAgentCompletion


@dataclass(slots=True)
class EngineShell:
    """Typed view of engine-owned slots used during capability attach."""

    tool_context: ToolContext
    tool_registry: ToolRegistry
    handle: EngineHandle
    lifecycle_registry: LifecycleRegistry
    default_model: str
    approval_handler: ApprovalHandler
    hook_executor: object
    enqueue_subagent_completion: Callable[[SubAgentCompletion], None]
    memory_enabled: bool
    memory_path: Path | None
    memory_mode: str | None
    memory_thread_id: str | None
    memory_coordinator: object | None
    goal_controller: object | None
    cycle_config: object
    seam_manager: object | None
    cycle_session_id: str | None
    cycle_started_at: int | None
    curated_snapshot: str | None
    evolution_pipeline: object | None
    post_turn: object | None
    mode: str
    skill_registry: object | None
    capacity_controller: object
    turn_counter: int
    pending_lsp_blocks: list[Any]

    @classmethod
    def wrap(cls, engine: Engine) -> EngineShell:
        return cls(
            tool_context=engine.tool_context,
            tool_registry=engine.tool_registry,
            handle=engine.handle,
            lifecycle_registry=engine.lifecycle_registry,
            default_model=engine.default_model,
            approval_handler=engine.approval_handler,
            hook_executor=engine.hook_executor,
            enqueue_subagent_completion=engine._enqueue_subagent_completion,
            memory_enabled=engine.memory_enabled,
            memory_path=engine.memory_path,
            memory_mode=engine.memory_mode,
            memory_thread_id=engine.memory_thread_id,
            memory_coordinator=engine.memory_coordinator,
            goal_controller=getattr(engine, "goal_controller", None),
            cycle_config=engine.cycle_config,
            seam_manager=engine.seam_manager,
            cycle_session_id=engine._cycle_session_id,
            cycle_started_at=engine._cycle_started_at,
            curated_snapshot=engine._curated_snapshot,
            evolution_pipeline=engine._evolution_pipeline,
            post_turn=engine.post_turn,
            mode=engine.mode,
            skill_registry=engine.skill_registry,
            capacity_controller=engine.capacity_controller,
            turn_counter=engine.turn_counter,
            pending_lsp_blocks=engine.pending_lsp_blocks,
        )

    def apply_to(self, engine: Engine) -> None:
        engine.memory_enabled = self.memory_enabled
        engine.memory_path = self.memory_path
        engine.memory_mode = self.memory_mode
        engine.memory_thread_id = self.memory_thread_id
        engine.memory_coordinator = self.memory_coordinator
        engine.goal_controller = self.goal_controller
        engine.cycle_config = self.cycle_config
        engine.seam_manager = self.seam_manager
        engine._cycle_session_id = self.cycle_session_id
        engine._cycle_started_at = self.cycle_started_at
        engine._curated_snapshot = self.curated_snapshot
        engine._evolution_pipeline = self.evolution_pipeline
        engine.post_turn = self.post_turn
        engine.mode = self.mode
        engine.skill_registry = self.skill_registry
        engine.capacity_controller = self.capacity_controller
        engine.turn_counter = self.turn_counter
        engine.pending_lsp_blocks = self.pending_lsp_blocks

    @property
    def cancel_token(self) -> asyncio.Event:
        return cast(asyncio.Event, self.handle.cancel_event)
