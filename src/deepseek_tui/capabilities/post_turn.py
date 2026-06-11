"""Post-turn capability adapter for Engine assembly."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from deepseek_tui.config.models import Config


def build_post_turn_pipelines(
    config: Config,
    *,
    memory_coordinator: object | None,
    evolution_pipeline: object | None,
) -> list[object]:
    pipelines: list[object] = []
    if memory_coordinator is not None:
        from deepseek_tui.post_turn.pipelines.memory_pipeline import MemoryPipeline

        pipelines.append(MemoryPipeline(memory_coordinator, config))
    if evolution_pipeline is not None:
        pipelines.append(evolution_pipeline)
    return pipelines


async def attach_engine_post_turn(
    engine: object,
    config: Config,
    *,
    evolution_pipeline: object | None,
) -> None:
    """Start the post-turn orchestrator on a materialized engine."""
    pipelines = build_post_turn_pipelines(
        config,
        memory_coordinator=engine.memory_coordinator,  # type: ignore[attr-defined]
        evolution_pipeline=evolution_pipeline,
    )
    engine.post_turn = await start_post_turn_orchestrator(config, pipelines)  # type: ignore[attr-defined]


async def start_post_turn_orchestrator(
    config: Config,
    pipelines: list[object],
) -> object | None:
    if not config.post_turn.enabled or not pipelines:
        return None
    from deepseek_tui.post_turn.orchestrator import PostTurnOrchestrator

    orchestrator = PostTurnOrchestrator(
        pipelines,  # type: ignore[arg-type]
        flush_timeout_s=config.evolution.flush_timeout_s,
    )
    await orchestrator.start()
    return orchestrator


async def stop_post_turn_orchestrator(orchestrator: object | None) -> None:
    if orchestrator is None:
        return
    from deepseek_tui.post_turn.orchestrator import PostTurnOrchestrator

    if isinstance(orchestrator, PostTurnOrchestrator):
        await orchestrator.stop()


async def run_post_turn_after_turn(
    *,
    post_turn: object | None,
    evidence: object | None,
    memory_coordinator: object | None,
) -> None:
    if evidence is None:
        return
    if post_turn is not None:
        await post_turn.after_turn(evidence)  # type: ignore[attr-defined]
        return
    from deepseek_tui.capabilities.memory import capture_memory_after_turn

    await capture_memory_after_turn(memory_coordinator, evidence)


async def flush_post_turn_before_loss(
    *,
    post_turn: object | None,
    evidence: object | None,
) -> None:
    if post_turn is None or evidence is None:
        return
    await post_turn.flush_before_loss(evidence)  # type: ignore[attr-defined]


@dataclass(slots=True)
class PostTurnToolObserver:
    post_turn: object | None

    async def after_tool(self, context: object) -> None:
        notify_post_turn_main_tool_called(
            self.post_turn,
            context.tool_name,  # type: ignore[attr-defined]
        )


@dataclass(slots=True)
class DynamicPostTurnToolObserver:
    post_turn: Callable[[], object | None]

    async def after_tool(self, context: object) -> None:
        notify_post_turn_main_tool_called(
            self.post_turn(),
            context.tool_name,  # type: ignore[attr-defined]
        )


def post_turn_tool_observer(post_turn: object | None) -> PostTurnToolObserver:
    return PostTurnToolObserver(post_turn=post_turn)


def dynamic_post_turn_tool_observer(
    post_turn: Callable[[], object | None],
) -> DynamicPostTurnToolObserver:
    return DynamicPostTurnToolObserver(post_turn=post_turn)


def notify_post_turn_main_tool_called(
    post_turn: object | None,
    tool_name: str,
) -> None:
    if post_turn is None or not hasattr(post_turn, "on_main_tool_called"):
        return
    post_turn.on_main_tool_called(tool_name)  # type: ignore[attr-defined]
