"""Session-maintenance half of the Engine (mixin).

Pre-tool snapshots + undo, crash checkpoints, session persistence,
compaction, and cycle advancement.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from deepseek_tui.engine.capacity import CompactionResult, compact_messages_safe
from deepseek_tui.engine.cycle import archive_cycle, should_advance_cycle
from deepseek_tui.protocol.messages import Message

logger = logging.getLogger(__name__)


class SessionMaintenanceMixin:
    """Checkpoint / persistence / compaction / cycle methods shared into Engine."""

    _SNAPSHOT_TOOLS: frozenset[str] = frozenset(
        {"write_file", "edit_file", "apply_patch"}
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

    async def _maybe_layered_context_checkpoint(
        self, messages: list[Message], model: str
    ) -> None:
        """Pre-request soft seam — mirrors ``layered_context_checkpoint`` (#159).
        阈值分级(seam.py:23-31),按当前输入 token 递进,每级只触发一次、且必须按序:

        L1 = 192K、L2 = 384K、L3 = 576K
        对应产物字数上限逐级收紧:800 / 600 / 400 词
        """
        seam = self.seam_manager
        if seam is None or not seam.config.enabled:
            return

        # Prefer the provider's real input_tokens (zero estimation error);
        # fall back to the char-based estimate on the first turn only.
        # Same fix as should_compact — the estimate undercounts ~6x and
        # made seam's L1 (192K) unreachable in practice.
        tokens = self.last_real_input_tokens
        if tokens <= 0:
            from deepseek_tui.engine.context import estimated_input_tokens

            try:
                tokens = estimated_input_tokens(messages)
            except Exception:  # noqa: BLE001
                return
        highest = await seam.highest_level()
        level = seam.seam_level_for(tokens, highest)
        if level is None:
            return
        msg_count = len(messages)
        verbatim_start = seam.verbatim_window_start(msg_count)
        if verbatim_start <= 0:
            return
        pinned = self.working_set.pinned_message_indices(
            messages, self.tool_context.working_directory
        )
        try:
            existing = seam.collect_seam_texts(messages)
            from deepseek_tui.engine.usage_ledger import usage_source

            with usage_source("seam"):
                if existing:
                    recent = messages[:verbatim_start]
                    seam_text = await seam.recompact(
                        existing, recent, level, 0, verbatim_start
                    )
                else:
                    seam_text = await seam.produce_soft_seam(
                        messages,
                        level,
                        0,
                        verbatim_start,
                        pinned_indices=sorted(pinned),
                    )
        except Exception as err:  # noqa: BLE001
            logger.warning("layered_context_checkpoint failed: %s", err)
            return
        if seam_text and seam_text.strip():
            # Insert seam at verbatim window boundary — between old messages
            # and recent verbatim turns. This preserves prefix cache (no
            # deletion of prior messages) while placing the summary where
            # the LLM can use it as a bridge between stale prefix and fresh
            # context.
            #
            # Align off Role.TOOL so we never split assistant(tool_calls)
            # from its tool results (API orphan sequences).
            from deepseek_tui.protocol.messages import Role

            insert_at = verbatim_start
            while insert_at > 0 and messages[insert_at].role == Role.TOOL:
                insert_at -= 1
            messages.insert(insert_at, Message.assistant(seam_text))

    async def _auto_persist_session(self) -> None:
        """Best-effort session persistence after each turn.

        Writes session_messages to a JSON file so sessions survive restarts.
        Silent on failure.
        """
        try:
            from deepseek_tui.config.paths import user_sessions_dir

            sessions_dir = user_sessions_dir()
            sessions_dir.mkdir(parents=True, exist_ok=True)
            session_file = sessions_dir / "current.json"
            import json as _json

            data = {
                "model": self.default_model,
                "turn_counter": self.turn_counter,
                "messages": [m.model_dump() for m in self.session_messages],
                "compaction_summary_prompt": self._compaction_summary_prompt,
                "metadata": {
                    "id": self._cycle_session_id,
                },
            }
            tmp = session_file.with_suffix(".tmp")
            tmp.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(session_file)
        except Exception:  # noqa: BLE001
            pass

    _COMPACTION_SUMMARY_MAX_CHARS = 20_000

    def _record_compaction_summary(self, summary_prompt: str | None) -> None:
        """Accumulate a compaction summary so later turns retain it.

        Keeps the tail when the accumulated text exceeds the cap (newer
        summaries are more relevant than older ones).
        """
        if not summary_prompt:
            return
        if self._compaction_summary_prompt:
            combined = f"{self._compaction_summary_prompt}\n\n{summary_prompt}"
        else:
            combined = summary_prompt
        if len(combined) > self._COMPACTION_SUMMARY_MAX_CHARS:
            combined = combined[-self._COMPACTION_SUMMARY_MAX_CHARS :]
        self._compaction_summary_prompt = combined

    async def _run_compaction(
        self, messages: list[Message]
    ) -> CompactionResult:
        """Run compaction and return the full result (incl. success flag).

        Shared by :meth:`_emergency_compact` (TurnLoop callback, which
        only wants the messages) and the manual ``/compact`` path in
        ``threads.py`` (which needs ``success`` to surface failures to
        the user).
        """
        from deepseek_tui.engine.usage_ledger import usage_source

        with usage_source("compaction"):
            result = await compact_messages_safe(
                self.client,
                messages,
                self.compaction_config,
                workspace=self.tool_context.working_directory,
                model_override=self.default_model,
            )
        # Persist the summary — previously discarded, so emergency/manual
        # compaction lost the archived history entirely.
        self._record_compaction_summary(result.summary_prompt)
        return result

    async def _emergency_compact(
        self, messages: list[Message]
    ) -> tuple[list[Message], str | None]:
        """Emergency compaction for TurnLoop / capacity overflow recovery.

        Returns ``(messages, summary_prompt)``. Callers must merge
        ``summary_prompt`` into the *current* request's system prompt —
        otherwise this turn only sees the pinned tail and the archive is
        deferred until the next user turn.
        """
        result = await self._run_compaction(messages)
        return result.messages, result.summary_prompt

    async def _maybe_advance_cycle(
        self, messages: list[Message], model: str
    ) -> None:
        """Archive a full cycle to disk and trim history when threshold crossed.

        Produces a model-curated briefing via produce_briefing (or Flash seam
        briefing if seams exist) so the next cycle starts with context about
        decisions, constraints, and progress from the archived history.
        """
        if not messages:
            return

        # Prefer the provider's real input_tokens (zero estimation error);
        # fall back to the char-based estimate on the first turn only.
        # Same fix as should_compact — the estimate undercounts ~6x and
        # made cycle's 768K threshold unreachable in practice.
        active_tokens = self.last_real_input_tokens
        if active_tokens <= 0:
            from deepseek_tui.engine.context import estimated_input_tokens

            try:
                active_tokens = estimated_input_tokens(messages)
            except Exception:  # noqa: BLE001 — token estimation is best-effort
                return
        if not should_advance_cycle(
            active_tokens,
            reserved_headroom_tokens=8_000,
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
        except OSError as exc:
            logger.warning("cycle_archive_failed error=%s", exc)
            return

        # --- Produce briefing for the next cycle ---
        briefing_text = ""
        from deepseek_tui.engine.cycle import (
            CycleBriefing,
            StructuredState,
            build_seed_messages,
            produce_briefing,
        )
        from deepseek_tui.engine.usage_ledger import usage_source

        # Build structured state snapshot
        structured = StructuredState(
            mode_label=self.mode or "agent",
            workspace=str(self.tool_context.working_directory),
            working_set_summary=self.working_set.summary() or None,
        )
        structured_block = structured.to_system_block()

        # Try Flash briefing from seams first (cheap); fall back to full
        # produce_briefing if no seams or if Flash fails.
        try:
            with usage_source("cycle_briefing"):
                if self.seam_manager is not None:
                    existing_seams = self.seam_manager.collect_seam_texts(messages)
                    if existing_seams:
                        briefing_text = await self.seam_manager.produce_flash_briefing(
                            existing_seams, structured_state=structured_block
                        )
                if not briefing_text:
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

        seed_dicts = build_seed_messages(
            structured_state_block=structured_block,
            briefing=briefing_obj,
            pending_user_message=None,
        )

        # Convert seed dicts to Message objects and preserve recent messages.
        # When the briefing came back empty (Flash refused, timed out, or no
        # seams existed), preserving only 4 recent messages would silently
        # discard the entire pre-cycle history with no replacement. Fall back
        # to a larger verbatim window so the next cycle at least has recent
        # context to work from, and warn so the empty briefing is observable.
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
        from deepseek_tui.protocol.messages import Role

        start = max(0, len(messages) - keep)
        while start > 0 and messages[start].role == Role.TOOL:
            start -= 1
        recent = messages[start:]

        messages.clear()
        for sd in seed_dicts:
            role = sd["role"]
            content = sd["content"]
            if role == "user":
                messages.append(Message.user(content))
            else:
                messages.append(Message.assistant(content))
        messages.extend(recent)

        # Reset seam tracking for the new cycle
        if self.seam_manager is not None:
            await self.seam_manager.reset()

        self._cycle_n += 1
        self._cycle_started_at = int(time.time())
        logger.info(
            "cycle_advanced new_cycle=%d seed_msgs=%d briefing_tokens=%d",
            self._cycle_n,
            len(messages),
            estimate_tokens(briefing_text) if briefing_text else 0,
        )
