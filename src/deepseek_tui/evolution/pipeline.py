"""Evolution post-turn pipeline."""

from __future__ import annotations

import asyncio
import copy
import logging
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.evolution.backends.curated_memory import CuratedMemoryBackend
from deepseek_tui.evolution.backends.procedural_skill import ProceduralSkillBackend
from deepseek_tui.evolution.events import EvolutionAppliedEvent, EvolutionSuggestedEvent
from deepseek_tui.evolution.flush.runner import run_evolution_flush
from deepseek_tui.evolution.review.runner import run_evolution_review
from deepseek_tui.evolution.signals import detect_signals
from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.post_turn.gates import GateConfig, should_review
from deepseek_tui.post_turn.scheduler import PeriodicTurnScheduler

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.config.models import Config
    from deepseek_tui.evolution.ledger import ExperienceLedger

logger = logging.getLogger(__name__)

_REVIEW_BUFFER_MAX_TURNS = 8
_REVIEW_MESSAGE_CHAR_LIMIT = 1200


class EvolutionPipeline:
    name = "evolution"

    def __init__(
        self,
        *,
        config: Config,
        client: LLMClient,
        ledger: ExperienceLedger,
        curated_backend: CuratedMemoryBackend,
        skill_backend: ProceduralSkillBackend,
        curated_store: object,
        skill_store: object,
        audit: object,
        workspace: Path,
        emit_event: object | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._ledger = ledger
        self.ledger = ledger
        self.curated_store = curated_store
        self.skill_store = skill_store
        self._audit = audit
        self._emit_event = emit_event
        self._backends = [curated_backend, skill_backend]
        self._curated_backend = curated_backend
        self._skill_backend = skill_backend
        self._workspace = workspace
        sched = config.evolution.schedulers
        self._review_memory_sched = PeriodicTurnScheduler(
            every_n=sched.memory_nudge_every_n,
            idle_timeout_s=float(sched.review_idle_timeout_seconds),
            warmup_enabled=False,
        )
        self._skill_nudge_tool_rounds = sched.skill_nudge_tool_rounds
        self._flush_min_turns = config.evolution.flush_min_user_turns
        self._review_model = (
            config.evolution.review_model.strip()
            or config.effective_provider_config().model
            or config.default_text_model
        )
        self._review_max_steps = config.evolution.review_max_steps
        self._enabled = config.evolution.enabled
        self._gate_cfg = GateConfig(
            min_chars=config.memory.smart.capture_min_user_chars,
            skip_slash=config.memory.smart.capture_skip_slash_commands,
        )
        self._current_thread_id = ""
        self._review_tasks: set[asyncio.Task[None]] = set()
        self._review_turn_buffers: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
        self._skill_tool_rounds: dict[str, int] = defaultdict(int)

    async def start(self) -> None:
        await self._audit.initialize()

    async def stop(self) -> None:
        if self._review_tasks:
            await asyncio.gather(*list(self._review_tasks), return_exceptions=True)
        self._review_tasks.clear()

    async def after_turn(self, evidence: TurnEvidence) -> None:
        if not self._enabled:
            return
        self._current_thread_id = evidence.thread_id
        self._append_review_buffer(evidence)
        self._review_memory_sched.notify(evidence.thread_id, evidence)
        self._skill_tool_rounds[evidence.thread_id] += evidence.tool_rounds
        signals = detect_signals(
            evidence,
            evidence.messages,
            min_tool_calls=self._config.evolution.schedulers.min_tool_calls_signal,
        )
        scheduler_due = self._review_memory_sched.is_due(evidence.thread_id)
        skill_due = self._skill_tool_rounds[evidence.thread_id] >= self._skill_nudge_tool_rounds

        if not should_review(
            evidence,
            cfg=self._gate_cfg,
            scheduler_due=scheduler_due or skill_due,
            signals=signals,
        ):
            return

        if scheduler_due:
            self._review_memory_sched.reset(evidence.thread_id)
        if skill_due:
            self._skill_tool_rounds[evidence.thread_id] = 0

        review_evidence = self._review_evidence(evidence)
        task = asyncio.create_task(
            self._run_review(
                review_evidence,
                review_memory=scheduler_due or evidence.flush_mode,
                review_skill=skill_due or evidence.flush_mode,
            ),
            name=f"evolution-review-{evidence.turn_id or evidence.thread_id}",
        )
        self._review_tasks.add(task)
        task.add_done_callback(self._review_tasks.discard)

    async def _run_review(
        self,
        evidence: TurnEvidence,
        *,
        review_memory: bool,
        review_skill: bool,
    ) -> None:
        try:
            mutations = await run_evolution_review(
                self._client,
                model=str(self._review_model),
                evidence=evidence,
                backends=self._backends,
                ledger=self._ledger,
                review_memory=review_memory,
                review_skill=review_skill,
                max_steps=self._review_max_steps,
                workspace=self._workspace,
                curated_store=self.curated_store,
                skill_store=self.skill_store,
            )
            for mutation in mutations:
                await self._ledger.submit(mutation, source="review", evidence=evidence)
        except Exception:
            logger.exception("evolution review failed thread_id=%s", evidence.thread_id)

    async def flush_before_loss(self, evidence: TurnEvidence) -> None:
        if not self._enabled:
            return
        if evidence.user_turn_index < self._flush_min_turns:
            return
        try:
            mutations = await run_evolution_flush(
                self._client,
                str(self._review_model),
                evidence,
                self._backends,
                ledger=self._ledger,
                max_steps=self._review_max_steps,
                workspace=self._workspace,
                curated_store=self.curated_store,
                skill_store=self.skill_store,
            )
            for mutation in mutations:
                await self._ledger.submit(mutation, source="flush", evidence=evidence)
        except Exception:
            logger.exception("evolution flush failed thread_id=%s", evidence.thread_id)

    def note_active_turn(self, thread_id: str) -> None:
        """Mark thread for in-turn evolution tool calls (scheduler reset, etc.)."""
        if thread_id:
            self._current_thread_id = thread_id

    def on_main_tool_called(self, tool_name: str) -> None:
        if not self._current_thread_id:
            return
        if tool_name == "memory_curate":
            self._review_memory_sched.reset(self._current_thread_id)
        elif tool_name == "skill_manage":
            self._skill_tool_rounds[self._current_thread_id] = 0

    def _append_review_buffer(self, evidence: TurnEvidence) -> None:
        trimmed = _truncate_messages(evidence.messages, _REVIEW_MESSAGE_CHAR_LIMIT)
        buf = self._review_turn_buffers[evidence.thread_id]
        buf.append(trimmed)
        while len(buf) > _REVIEW_BUFFER_MAX_TURNS:
            buf.pop(0)

    def _review_evidence(self, evidence: TurnEvidence) -> TurnEvidence:
        if evidence.flush_mode:
            return evidence
        slices = self._review_turn_buffers.get(evidence.thread_id, [])
        if not slices:
            return evidence
        merged: list[dict[str, Any]] = []
        for turn_msgs in slices:
            merged.extend(turn_msgs)
        return replace(evidence, messages=merged)

    def curated_stable_block(self) -> str | None:
        return self._curated_backend.stable_prompt_block()

    def volatile_lines(self) -> list[str]:
        return self._skill_backend.volatile_prompt_lines()


def _truncate_messages(
    messages: list[dict[str, Any]], char_limit: int
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        row = copy.deepcopy(msg)
        content = str(row.get("content", "") or "")
        if len(content) > char_limit:
            row["content"] = content[: char_limit - 1] + "…"
        out.append(row)
    return out


def build_evolution_pipeline(
    cfg: Config,
    client: LLMClient,
    workspace: Path,
    *,
    emit_event: object | None = None,
) -> EvolutionPipeline:
    from deepseek_tui.config.paths import user_curated_memories_dir
    from deepseek_tui.evolution.audit.store import EvolutionAuditStore
    from deepseek_tui.evolution.curated.store import CuratedMemoryStore
    from deepseek_tui.evolution.ledger import ExperienceLedger
    from deepseek_tui.evolution.policy import DefaultEvolutionPolicy
    from deepseek_tui.evolution.procedural.skill_store import ProceduralSkillStore

    curated_dir = (
        Path(cfg.evolution.curated.dir).expanduser()
        if cfg.evolution.curated.dir.strip()
        else user_curated_memories_dir()
    )
    curated_store = CuratedMemoryStore(
        curated_dir,
        memory_char_limit=cfg.evolution.curated.memory_char_limit,
        user_char_limit=cfg.evolution.curated.user_char_limit,
    )
    curated_store.load_snapshot()
    skill_store = ProceduralSkillStore(
        workspace=workspace,
        default_scope=cfg.evolution.procedural.default_scope,
    )
    curated_backend = CuratedMemoryBackend(curated_store)
    skill_backend = ProceduralSkillBackend(skill_store)

    from deepseek_tui.evolution.sinks.trajectory import trajectory_sink_from_config

    audit = EvolutionAuditStore(cfg.resolved_database_path())
    policy = DefaultEvolutionPolicy(cfg.evolution)
    trajectory = trajectory_sink_from_config(cfg)

    async def _emit(event: object) -> None:
        if emit_event is None:
            return
        if isinstance(event, EvolutionAppliedEvent) and cfg.evolution.notify:
            from deepseek_tui.engine.events import StatusEvent

            if callable(emit_event):
                await emit_event(StatusEvent(message=f"💾 {event.summary}"))
        if isinstance(event, EvolutionSuggestedEvent):
            from deepseek_tui.engine.events import EvolutionProposalEvent

            if callable(emit_event):
                await emit_event(
                    EvolutionProposalEvent(
                        record_id=event.record_id,
                        kind=event.kind,
                        summary=event.summary,
                        asset_path=event.asset_path,
                    )
                )

    def _on_applied(_mutation: object, _result: object) -> None:
        return None

    ledger = ExperienceLedger(
        policy=policy,
        audit=audit,
        backends=[curated_backend, skill_backend],
        emit=_emit if emit_event else None,
        on_applied=_on_applied,
        trajectory=trajectory,
    )

    pipeline = EvolutionPipeline(
        config=cfg,
        client=client,
        ledger=ledger,
        curated_backend=curated_backend,
        skill_backend=skill_backend,
        curated_store=curated_store,
        skill_store=skill_store,
        audit=audit,
        workspace=workspace,
        emit_event=emit_event,
    )
    return pipeline
