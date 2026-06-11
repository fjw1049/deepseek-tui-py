"""Evolution capability prompt contributions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.config.models import Config
from deepseek_tui.evolution.constants import (
    CURATED_MEMORY_STORE_KEY,
    EVOLUTION_LEDGER_KEY,
    SKILL_STORE_KEY,
    TURN_EVIDENCE_FACTORY_KEY,
    TURN_EVIDENCE_KEY,
)
from deepseek_tui.host.prompts import (
    FunctionPromptContributor,
    PromptContributor,
    PromptContributorContext,
)
from deepseek_tui.host.services import ServiceRegistry, ServiceScope

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.evolution.pipeline import EvolutionPipeline


EmitEvent = Callable[[object], Awaitable[None]]
TurnEvidenceFactory = Callable[[], object]


@dataclass(slots=True)
class EvolutionRuntime:
    pipeline: EvolutionPipeline | None = None
    curated_snapshot: str | None = None


def create_evolution_runtime(
    config: Config,
    client: LLMClient,
    services: ServiceRegistry,
    *,
    workspace: Path,
    emit_event: EmitEvent | None,
) -> EvolutionRuntime:
    if not config.evolution.enabled:
        return EvolutionRuntime()

    from deepseek_tui.evolution.pipeline import EvolutionPipeline, build_evolution_pipeline

    pipeline = build_evolution_pipeline(
        config,
        client,
        workspace.resolve(),
        emit_event=emit_event,
    )
    if services.optional(EvolutionPipeline) is None:
        services.add(
            EvolutionPipeline,
            pipeline,
            owner="evolution",
            scope=ServiceScope.ENGINE,
        )
    return EvolutionRuntime(
        pipeline=pipeline,
        curated_snapshot=pipeline.curated_stable_block(),
    )


def attach_engine_evolution(
    engine: object,
    config: Config,
    client: LLMClient,
    *,
    workspace: Path,
    emit_event: EmitEvent | None,
) -> EvolutionRuntime:
    """Wire evolution runtime onto a materialized engine."""
    evolution_runtime = create_evolution_runtime(
        config,
        client,
        engine.tool_context.services,  # type: ignore[attr-defined]
        workspace=workspace,
        emit_event=emit_event,
    )
    engine._curated_snapshot = evolution_runtime.curated_snapshot  # type: ignore[attr-defined]
    engine._evolution_pipeline = evolution_runtime.pipeline  # type: ignore[attr-defined]
    attach_evolution_bindings(
        evolution_runtime,
        services=engine.tool_context.services,  # type: ignore[attr-defined]
    )
    return evolution_runtime


def attach_evolution_bindings(
    runtime: EvolutionRuntime,
    *,
    services: ServiceRegistry,
) -> None:
    pipeline = runtime.pipeline
    if pipeline is None:
        return
    _add_named_if_missing(
        services,
        CURATED_MEMORY_STORE_KEY,
        pipeline.curated_store,
    )
    _add_named_if_missing(services, SKILL_STORE_KEY, pipeline.skill_store)
    _add_named_if_missing(services, EVOLUTION_LEDGER_KEY, pipeline.ledger)


def publish_turn_evidence(
    *,
    metadata: dict[str, Any],
    services: ServiceRegistry | None = None,
    pipeline: object | None,
    evidence: object,
    live_evidence_factory: TurnEvidenceFactory | None,
    final: bool,
    thread_id: str,
) -> None:
    if services is None or services.optional_named(EVOLUTION_LEDGER_KEY) is None:
        return
    if final:
        metadata[TURN_EVIDENCE_KEY] = evidence
        metadata.pop(TURN_EVIDENCE_FACTORY_KEY, None)
    else:
        metadata.pop(TURN_EVIDENCE_KEY, None)
        if live_evidence_factory is not None:
            metadata[TURN_EVIDENCE_FACTORY_KEY] = live_evidence_factory
    if pipeline is not None and hasattr(pipeline, "note_active_turn"):
        pipeline.note_active_turn(thread_id)


def evolution_record_to_dict(record: object) -> dict[str, object]:
    from dataclasses import asdict, is_dataclass

    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    return {"repr": repr(record)}


def evolution_action_response(record: object) -> dict[str, object]:
    return {"ok": True, "record": evolution_record_to_dict(record)}


def evolution_decision_from_record_status(status: str) -> str:
    from deepseek_tui.evolution.tool_response import decision_from_record_status

    return decision_from_record_status(status)


def build_main_tool_evolution_response(
    *,
    record: object,
    decision: str,
    apply_result: object | None = None,
    mutation: object | None = None,
    store: object | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    from deepseek_tui.evolution.tool_response import build_evolution_tool_response

    return build_evolution_tool_response(
        record=record,  # type: ignore[arg-type]
        decision=decision,
        apply_result=apply_result,  # type: ignore[arg-type]
        mutation=mutation,  # type: ignore[arg-type]
        store=store,
        error=error,
    )


async def evolution_ledger_for_thread(request: object, thread_id: str) -> object:
    from deepseek_tui.app_server.runtime_api.errors import api_error
    from deepseek_tui.app_server.runtime_api.routes._deps import manager

    mgr = manager(request)
    try:
        thread = await mgr.get_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    async with mgr._active_lock:
        state = mgr._active.get(thread_id)
    if state is None:
        await mgr._ensure_engine_loaded(thread)
        async with mgr._active_lock:
            state = mgr._active.get(thread_id)
    if state is None:
        raise api_error(503, "thread engine not loaded", error="engine_not_loaded")
    pipeline = getattr(state.engine, "_evolution_pipeline", None)
    if pipeline is None:
        raise api_error(503, "evolution not enabled", error="evolution_disabled")
    return pipeline.ledger


def _add_named_if_missing(
    services: ServiceRegistry,
    key: str,
    value: object,
) -> None:
    if services.optional_named(key) is not None:
        return
    services.add_named(
        key,
        value,
        owner="evolution",
        scope=ServiceScope.ENGINE,
    )


def contribute_runtime_surfaces(registry: object) -> None:
    from deepseek_tui.app_server.runtime_api.routes.evolution import (
        approve_evolution,
        list_pending_evolution,
        reject_evolution,
    )

    registry.add_route(  # type: ignore[attr-defined]
        id="evolution.list_pending",
        owner="evolution",
        method="GET",
        path="/v1/evolution/pending",
        handler=list_pending_evolution,
    )
    registry.add_route(  # type: ignore[attr-defined]
        id="evolution.approve",
        owner="evolution",
        method="POST",
        path="/v1/evolution/{record_id}/approve",
        handler=approve_evolution,
    )
    registry.add_route(  # type: ignore[attr-defined]
        id="evolution.reject",
        owner="evolution",
        method="POST",
        path="/v1/evolution/{record_id}/reject",
        handler=reject_evolution,
    )


def evolution_prompt_contributors() -> list[PromptContributor]:
    return [
        FunctionPromptContributor("evolution-snapshot", 300, _evolution_snapshot),
        FunctionPromptContributor("evolution-guidance", 310, _evolution_guidance),
        FunctionPromptContributor("session-evolution", 1100, _session_evolution),
    ]


def _evolution_snapshot(ctx: PromptContributorContext) -> str | None:
    if ctx.evolution_enabled and ctx.curated_snapshot:
        return ctx.curated_snapshot
    return None


def _evolution_guidance(ctx: PromptContributorContext) -> str | None:
    if not ctx.evolution_enabled:
        return None
    from deepseek_tui.evolution.prompts import (
        EVOLUTION_GUIDANCE,
        SKILLS_EVOLUTION_GUIDANCE,
    )

    return EVOLUTION_GUIDANCE + "\n\n" + SKILLS_EVOLUTION_GUIDANCE


def _session_evolution(ctx: PromptContributorContext) -> str | None:
    if not ctx.session_evolution_lines:
        return None
    return (
        "<session-evolution>\n"
        + "\n".join(ctx.session_evolution_lines)
        + "\n</session-evolution>"
    )
