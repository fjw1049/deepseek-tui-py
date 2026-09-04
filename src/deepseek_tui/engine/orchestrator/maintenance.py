"""Session-maintenance half of the Engine (mixin).

Pre-tool snapshots + undo, crash checkpoints, session persistence,
compaction, and cycle advancement.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from deepseek_tui.engine.capacity import (
    L0_HARD_CLEAR_MIN_RECLAIM,
    MAX_WORKING_SET_PATHS,
    CompactionResult,
    ToolPruneConfig,
    compact_messages_safe,
    prune_old_tool_results,
    should_l0_prune,
)
from deepseek_tui.engine.cycle import (
    StructuredState,
    archive_cycle,
    should_advance_cycle,
)
from deepseek_tui.protocol.messages import Message

logger = logging.getLogger(__name__)


class SessionMaintenanceMixin:
    """Checkpoint / persistence / compaction / cycle methods shared into Engine."""

    _SNAPSHOT_TOOLS: frozenset[str] = frozenset(
        {"write_file", "edit_file"}
    )

    def _take_pre_tool_snapshot(
        self, tool_call_id: str, tool_name: str, args: dict[str, Any]
    ) -> None:
        """Capture file contents before a write tool runs.

        Best-effort — failures here must never block tool execution.
        """
        if tool_name not in self._SNAPSHOT_TOOLS:
            return
        from deepseek_tui.integrations.lsp import edited_paths_for_tool

        try:
            paths = edited_paths_for_tool(tool_name, args)
        except Exception:  # noqa: BLE001
            return
        workspace = self.tool_context.working_directory
        snapshots: list[tuple[Path, bytes | None]] = []
        for p in paths:
            absolute = p if p.is_absolute() else workspace / p
            try:
                size = absolute.stat().st_size
                if size > self._max_snapshot_file_size:
                    continue
                snapshots.append((absolute, absolute.read_bytes()))
            except FileNotFoundError:
                snapshots.append((absolute, None))
            except OSError:
                continue
        if snapshots:
            self.tool_snapshots[tool_call_id] = snapshots
            while len(self.tool_snapshots) > self._max_tool_snapshots:
                oldest = next(iter(self.tool_snapshots))
                del self.tool_snapshots[oldest]

    def undo_last_tool(self) -> tuple[bool, str]:
        """Restore the most recent tool snapshot.

        Returns (success, message).
        """
        if not self.tool_snapshots:
            return False, "No tool snapshots available to undo."
        last_id = next(reversed(self.tool_snapshots))
        snapshots = self.tool_snapshots.pop(last_id)
        restored = 0
        errors: list[str] = []
        for path, original in snapshots:
            try:
                if original is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.write_bytes(original)
                restored += 1
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        if errors:
            return False, f"Restored {restored}; errors: {'; '.join(errors)}"
        return True, f"Reverted {restored} file(s) from tool {last_id[:8]}"

    def _save_crash_checkpoint(
        self,
        messages: list[Message],
        *,
        model: str,
    ) -> None:
        """Write ``latest.json`` before a turn — mirrors ``save_checkpoint``."""
        try:
            from deepseek_tui.state.session import save_checkpoint

            save_checkpoint(
                {
                    "metadata": {
                        "id": self._cycle_session_id,
                        "workspace": str(
                            self.tool_context.working_directory.resolve()
                        ),
                        "model": model,
                    },
                    "model": model,
                    "turn_counter": self.turn_counter,
                    "messages": [m.model_dump() for m in messages],
                }
            )
        except Exception:  # noqa: BLE001
            logger.debug("checkpoint save failed", exc_info=True)

    # Long-session drift reminder: first injection once the context passes
    # _DRIFT_REMINDER_FIRST_RATIO of the window, then again after each
    # further _DRIFT_REMINDER_STEP_RATIO of growth (0.4 → 0.6 → 0.8).
    _DRIFT_REMINDER_FIRST_RATIO = 0.40
    _DRIFT_REMINDER_STEP_RATIO = 0.20

    def _maybe_inject_long_session_reminder(
        self,
        messages: list[Message],
        model: str,
        *,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        """Append a short values reminder when the session grows long.

        Counters attention decay on the distant system prefix (the
        ``long_conversation_reminder`` pattern): a ~150-token re-anchor of
        the load-bearing disciplines, injected as a user-role
        ``<system-reminder>`` at the context tail. Earlier copies are never
        removed (prefix-cache friendly); compaction/rewrite archives them
        naturally, and the tracker resets when the context shrinks past the
        last injection point.
        """
        from deepseek_tui.engine import reminders
        from deepseek_tui.engine.context_pressure import measure_context_pressure
        from deepseek_tui.engine.prompts import LONG_SESSION_REMINDER

        pressure = measure_context_pressure(
            model,
            messages,
            real_input_tokens=self.last_real_input_tokens,
            real_input_estimate=getattr(self, "last_real_input_estimate", 0),
            system_prompt=system_prompt,
            tools=tools,
        )
        if pressure.tokens < int(pressure.window * self._DRIFT_REMINDER_FIRST_RATIO):
            return
        last = getattr(self, "_drift_reminder_tokens", 0)
        if last > pressure.tokens:
            # Context shrank (compaction/rewrite/cycle) past the last
            # injection point — the old copy was archived, start over.
            last = 0
        step = int(pressure.window * self._DRIFT_REMINDER_STEP_RATIO)
        if last and pressure.tokens - last < step:
            return
        self._drift_reminder_tokens = pressure.tokens
        logger.info(
            "long_session_reminder_injected tokens=%d window=%d",
            pressure.tokens,
            pressure.window,
        )
        messages.append(
            reminders.reminder_message(
                reminders.LONG_SESSION_DRIFT, LONG_SESSION_REMINDER
            )
        )

    async def _auto_persist_session(self) -> None:
        """Best-effort standalone-TUI persistence in the canonical thread store."""
        try:
            meta = getattr(getattr(self, "tool_context", None), "metadata", None)
            if isinstance(meta, dict) and (
                meta.get("runtime_thread_id") or meta.get("subagent_id")
            ):
                return

            from deepseek_tui.config.paths import user_threads_dir
            from deepseek_tui.server.sessions import persist_tui_thread
            from deepseek_tui.server.threads import RuntimeThreadStore

            config = getattr(self, "_app_config", None)
            goal = self.goal_service.dump()
            persist_tui_thread(
                RuntimeThreadStore(user_threads_dir()),
                thread_id=self._cycle_session_id,
                messages=self.session_messages,
                model=self.default_model,
                provider=str(getattr(config, "provider", "deepseek") or "deepseek"),
                workspace=str(self.tool_context.working_directory.resolve()),
                mode=self.mode,
                trust_mode=bool(self.tool_context.trust_mode),
                goal=goal.goal,
                goal_queue=goal.queue,
            )
        except Exception:  # noqa: BLE001
            logger.debug("TUI thread persistence failed", exc_info=True)

    _COMPACTION_SUMMARY_MAX_CHARS = 20_000

    def _record_compaction_summary(self, summary_prompt: str | None) -> None:
        """Remember the latest summary for iterative re-compaction.

        Does **not** accumulate into the system prompt. The live bridge is
        a leading user message in ``messages``.

        Stores the summary *inside* the ``<archived_context>`` block rather than
        the whole bridge body: the next compaction replays this as
        ``<previous-summary>``, and handing it our own prefix and caveat would
        have the summarizer fold that framing into the next summary, once per
        pass.
        """
        if not summary_prompt:
            return
        from deepseek_tui.engine.context_pressure import unwrap_archived_context

        text = unwrap_archived_context(summary_prompt)
        if not text:
            return
        if len(text) > self._COMPACTION_SUMMARY_MAX_CHARS:
            text = text[-self._COMPACTION_SUMMARY_MAX_CHARS :]
        self._compaction_summary_prompt = text

    async def _run_compaction(
        self, messages: list[Message]
    ) -> CompactionResult:
        """Run compaction and return the full result (incl. success flag).

        Successful results have the ``<archived_context>`` bridge already
        prepended to ``result.messages`` — callers must not inject it into
        the system prompt.
        """
        from deepseek_tui.engine.usage_ledger import usage_source

        pinned = self.working_set.pinned_message_indices(
            messages, self.tool_context.working_directory
        )
        paths = self.working_set.top_paths(MAX_WORKING_SET_PATHS)

        with usage_source("compaction"):
            result = await compact_messages_safe(
                self.client,
                messages,
                self.compaction_config,
                workspace=self.tool_context.working_directory,
                pinned_indices=pinned or None,
                working_set_paths=paths or None,
                model_override=self.default_model,
                previous_summary=self._compaction_summary_prompt,
            )
        self._record_compaction_summary(result.summary_prompt)
        if result.success:
            from deepseek_tui.tools.plan_mode import sync_approved_plan_reminder

            sync_approved_plan_reminder(
                result.messages,
                mode=self.mode,
                working_directory=self.tool_context.working_directory,
                metadata=self.tool_context.metadata,
            )
        return result

    async def _emergency_compact(
        self, messages: list[Message]
    ) -> tuple[list[Message], str | None]:
        """Emergency compaction for TurnLoop / capacity overflow recovery.

        Returns ``(messages, bridge_text)``. The bridge is already inside
        ``messages``; the second value is for logging only.
        """
        result = await self._run_compaction(messages)
        return result.messages, result.summary_prompt

    def _maybe_l0_prune_tool_results(
        self,
        messages: list[Message],
        model: str,
        *,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Prune old tool bodies when context ratio ≥ L0 threshold."""
        from deepseek_tui.engine.context_pressure import measure_context_pressure

        pressure = measure_context_pressure(
            model,
            messages,
            real_input_tokens=self.last_real_input_tokens,
            real_input_estimate=getattr(self, "last_real_input_estimate", 0),
            system_prompt=system_prompt,
            tools=tools,
        )
        if not should_l0_prune(
            model=model,
            messages=messages,
            real_input_tokens=self.last_real_input_tokens,
            real_input_estimate=getattr(self, "last_real_input_estimate", 0),
            config=self.compaction_config,
            system_prompt=system_prompt,
            tools=tools,
            pressure=pressure,
        ):
            return 0
        # Stop before an ``<archived_context level=...>`` block if one is
        # present. Nothing produces those any more (soft seams were removed),
        # but a resumed pre-existing session can still carry one, and the
        # messages after it are the recent verbatim window.
        boundary = len(messages)
        for i, msg in enumerate(messages):
            text = ""
            for block in msg.content:
                if hasattr(block, "text") and isinstance(block.text, str):
                    text = block.text
                    break
            if '<archived_context level="' in text:
                boundary = i
                break
        # Soft trims land near the tail and cost the KV prefix almost nothing,
        # but a hard clear rewrites bodies deep inside it, so every request
        # after one re-bills the whole tail at full price. Ages tick per user
        # turn, so left alone a single newly-aged result breaks the prefix every
        # turn for a few thousand chars of relief. Batch the clears instead —
        # except once pressure reaches the rewrite band, where the window
        # matters more and a rewrite is about to break the prefix regardless.
        min_reclaim = (
            0
            if pressure.ratio >= self.compaction_config.rewrite_ratio
            else L0_HARD_CLEAR_MIN_RECLAIM
        )
        changed = prune_old_tool_results(
            messages,
            config=ToolPruneConfig(
                enabled=True,
                trigger_ratio=self.compaction_config.l0_prune_ratio,
                hard_clear_min_reclaim=min_reclaim,
            ),
            mutate_before_index=boundary,
        )
        if changed:
            logger.info(
                "l0_tool_prune changed=%d boundary=%d ratio=%.2f min_reclaim=%d",
                changed,
                boundary,
                pressure.ratio,
                min_reclaim,
            )
        return changed

    def _cycle_structured_state(self) -> StructuredState:
        """Capture live UI/runtime state before replacing conversation history."""
        from deepseek_tui.tools.subagent.types import SubAgentStatusKind

        metadata = self.tool_context.metadata
        todo_store = metadata.get("todos")
        todo_items = (
            todo_store.get("items", []) if isinstance(todo_store, dict) else []
        )
        todos = [
            {"content": item.content, "status": item.status}
            for item in todo_items
            if hasattr(item, "content") and hasattr(item, "status")
        ]

        plan_store = metadata.get("plan")
        raw_steps = (
            plan_store.get("steps", []) if isinstance(plan_store, dict) else []
        )
        plan = [
            {
                "step": str(step.get("title") or step.get("step") or ""),
                "status": str(step.get("status") or "pending"),
            }
            for step in raw_steps
            if isinstance(step, dict) and (step.get("title") or step.get("step"))
        ]

        agents: list[dict[str, str]] = []
        manager = self.tool_context.subagent_manager
        if manager is not None:
            for snapshot in manager.list_agents():
                if snapshot.status.kind is not SubAgentStatusKind.RUNNING:
                    continue
                agents.append(
                    {
                        "agent_id": snapshot.agent_id,
                        "role": snapshot.assignment.role or snapshot.agent_type.value,
                        "objective": snapshot.assignment.objective,
                    }
                )

        return StructuredState(
            mode_label=self.mode or "agent",
            workspace=str(self.tool_context.working_directory),
            working_set_summary=self.working_set.summary() or None,
            todo_snapshot=todos or None,
            plan_snapshot=plan or None,
            subagent_snapshots=agents,
        )

    async def _maybe_advance_cycle(
        self,
        messages: list[Message],
        model: str,
        *,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        """Archive a full cycle to disk and trim history when threshold crossed.

        Produces a model-curated briefing via produce_briefing so the next
        cycle starts with context about decisions, constraints, and progress
        from the archived history.
        """
        if not messages:
            return

        # Prefer the provider's real input_tokens (zero estimation error);
        # fall back to the estimate on the first turn only. The estimate must
        # include the system prompt and tool schemas — they are a multi-
        # thousand-token constant the message list cannot see, and leaving
        # them out kept cycle's threshold out of reach on the estimate path.
        from deepseek_tui.engine.context_pressure import measure_context_pressure

        try:
            active_tokens = measure_context_pressure(
                model,
                messages,
                real_input_tokens=self.last_real_input_tokens,
                real_input_estimate=getattr(self, "last_real_input_estimate", 0),
                system_prompt=system_prompt,
                tools=tools,
            ).tokens
        except Exception:  # noqa: BLE001 — token estimation is best-effort
            return
        if not should_advance_cycle(
            active_tokens,
            model=model,
            config=self.cycle_config,
            in_flight=False,
        ):
            return
        logger.info(
            "cycle_advance_triggered cycle_n=%d active_tokens=%d msg_count=%d",
            self._cycle_n,
            active_tokens,
            len(messages),
        )
        try:
            archive_path = archive_cycle(
                session_id=self._cycle_session_id,
                cycle_n=self._cycle_n,
                messages=list(messages),
                model=model,
                started=self._cycle_started_at,
            )
            logger.info("cycle_archived path=%s", archive_path)
            # The seed names this file, so the read sandbox has to allow it.
            self.tool_context.cycle_archive_root = archive_path.parent
        except OSError as exc:
            logger.warning("cycle_archive_failed error=%s", exc)
            return

        # --- Produce briefing for the next cycle ---
        briefing_text = ""
        from deepseek_tui.engine.cycle import (
            CycleBriefing,
            build_seed_messages,
            produce_briefing,
        )
        from deepseek_tui.engine.usage_ledger import usage_source

        # Build structured state snapshot
        structured = self._cycle_structured_state()
        structured_block = structured.to_system_block()

        try:
            with usage_source("cycle_briefing"):
                briefing_text = await produce_briefing(
                    self.client,
                    model,
                    messages,
                    self.cycle_config.briefing_max_for(model),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cycle_briefing_failed error=%s", exc)
            # Continue without briefing — still better than crashing

        # Assemble seed messages for the new cycle
        from deepseek_tui.engine.context import estimate_tokens

        briefing_obj = None
        if briefing_text:
            briefing_obj = CycleBriefing(
                cycle=self._cycle_n,
                timestamp=int(time.time()),
                briefing_text=briefing_text,
                token_estimate=estimate_tokens(briefing_text),
            )

        from deepseek_tui.engine.context_pressure import (
            collect_user_requests,
            find_last_real_user_query,
        )

        last_real_query = find_last_real_user_query(messages)
        seed_dicts = build_seed_messages(
            structured_state_block=structured_block,
            briefing=briefing_obj,
            pending_user_message=last_real_query,
            archive_path=archive_path,
            prior_requests=collect_user_requests(messages),
        )

        # Convert seed dicts to Message objects and preserve recent messages.
        # When the briefing came back empty (the model refused or timed out),
        # preserving only 4 recent messages would silently discard the entire
        # pre-cycle history with no replacement. Fall back to a larger verbatim
        # window so the next cycle at least has recent context to work from,
        # and warn so the empty briefing is observable.
        if briefing_text:
            keep = min(4, len(messages))
        else:
            keep = min(16, len(messages))
            logger.warning(
                "cycle_briefing_empty fallback_keep=%d/%d — preserving extra "
                "recent messages because briefing generation produced no text",
                keep, len(messages),
            )

        # Do not start the kept window on a tool-result message — that would
        # orphan TOOL rows from their parent assistant(tool_calls) message.
        from deepseek_tui.protocol.messages import MessageOrigin, Role

        start = max(0, len(messages) - keep)
        while start > 0 and messages[start].role == Role.TOOL:
            start -= 1
        recent = messages[start:]

        messages.clear()
        for sd in seed_dicts:
            role = sd["role"]
            content = sd["content"]
            origin_raw = sd.get("origin")
            origin = None
            if origin_raw:
                try:
                    origin = MessageOrigin(origin_raw)
                except ValueError:
                    origin = None
            if role == "user":
                messages.append(Message.user(content, origin=origin))
            else:
                messages.append(Message.assistant(content, origin=origin))
        messages.extend(recent)
        from deepseek_tui.tools.plan_mode import sync_approved_plan_reminder

        sync_approved_plan_reminder(
            messages,
            mode=self.mode,
            working_directory=self.tool_context.working_directory,
            metadata=self.tool_context.metadata,
        )

        self._cycle_n += 1
        self._cycle_started_at = int(time.time())
        logger.info(
            "cycle_advanced new_cycle=%d seed_msgs=%d briefing_tokens=%d",
            self._cycle_n,
            len(messages),
            estimate_tokens(briefing_text) if briefing_text else 0,
        )
