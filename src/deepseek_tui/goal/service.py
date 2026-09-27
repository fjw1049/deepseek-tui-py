"""Goal lifecycle, budget hard-stop, and continuation decisions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from deepseek_tui.goal.injection import GOAL_CONTINUATION_PROMPT, reminder_body
from deepseek_tui.goal.persist import dump_goal, load_queue, state_from_dict
from deepseek_tui.goal.queue import GoalQueue
from deepseek_tui.goal.state import (
    GoalState,
    apply_status,
    budget_block_reason,
    compute_budget_report,
    new_goal,
)
from deepseek_tui.goal.types import (
    ALLOWED_GOAL_MODES,
    MAX_UNRESOLVED_FAILURES,
    GOAL_TOOL_NAMES,
    ContinuationDecision,
    GoalActor,
    GoalBudgetLimits,
    GoalChange,
    GoalChangeKind,
    GoalDump,
    GoalError,
    GoalQueueItem,
    GoalSnapshot,
    GoalStatus,
)

UpdateHook = Callable[[GoalSnapshot | None, GoalChange], None]
MIN_WALL_CLOCK_BUDGET_MS = 1_000
MAX_WALL_CLOCK_BUDGET_MS = 24 * 60 * 60 * 1_000


class GoalService:
    def __init__(self, on_update: UpdateHook | None = None) -> None:
        self._state: GoalState | None = None
        self._queue = GoalQueue()
        self._on_update = on_update
        self._turn_counted = False
        self._last_promoted: GoalQueueItem | None = None
        self._turn_work_calls = 0
        self._turn_observations: list[str] = []
        self._turn_pending_work = False
        self.control_epoch = 0
        self.changed = asyncio.Event()
        self._workspace_digest: str | None = None

    @property
    def state(self) -> GoalState | None:
        return self._state

    def snapshot(self) -> GoalSnapshot | None:
        return None if self._state is None else self._state.snapshot()

    def queue_items(self) -> list[GoalQueueItem]:
        return list(self._queue.items)

    def dump(self) -> GoalDump:
        return dump_goal(self._state, self._queue)

    def restore(self, goal: dict[str, Any] | None, queue: object = None) -> None:
        self.control_epoch += 1
        self._workspace_digest = None
        self.changed.set()
        self._state = state_from_dict(goal)
        self._queue = load_queue(queue)
        self._turn_counted = False
        self._last_promoted = None
        self._turn_work_calls = 0
        self._turn_observations: list[str] = []
        self._turn_pending_work = False

    def assert_mode_allows_run(self, mode: str) -> None:
        normalized = (mode or "agent").strip() or "agent"
        if normalized not in ALLOWED_GOAL_MODES:
            raise GoalError(
                "mode_not_allowed",
                f"Goal mode cannot run in {normalized} mode. Switch to agent first.",
            )

    def create(
        self,
        objective: str,
        *,
        completion_criterion: str | None = None,
        replace: bool = False,
        actor: GoalActor = GoalActor.USER,
        mode: str = "agent",
        queue_item_id: str | None = None,
    ) -> GoalSnapshot:
        self.assert_mode_allows_run(mode)
        candidate = new_goal(objective, completion_criterion=completion_criterion)
        if queue_item_id is not None:
            head = self._queue.peek_next()
            if head is None or head.item_id != queue_item_id or head.objective != candidate.objective:
                raise GoalError("queue_changed", "Upcoming goal changed before promotion")
            candidate.queue_item_id = queue_item_id
        if self._state is not None and self._state.status is not GoalStatus.COMPLETE:
            if not replace:
                raise GoalError(
                    "already_exists",
                    "A goal already exists; use replace to start a new one",
                )
            self._clear(GoalActor.SYSTEM, emit=True)
        candidate.requirements = [{"id": "objective", "content": candidate.objective}]
        if candidate.completion_criterion:
            candidate.requirements.append(
                {"id": "criterion", "content": candidate.completion_criterion}
            )
        self._workspace_digest = None
        self._state = candidate
        self._turn_counted = False
        self._turn_work_calls = 0
        self._turn_observations: list[str] = []
        self._turn_pending_work = False
        self._last_promoted = None
        snapshot = self._state.snapshot()
        self._emit(snapshot, GoalChange(GoalChangeKind.LIFECYCLE, GoalStatus.ACTIVE, actor=actor))
        return snapshot

    def pause(
        self,
        reason: str | None = None,
        actor: GoalActor = GoalActor.USER,
    ) -> GoalSnapshot:
        state = self._require()
        if state.status is GoalStatus.PAUSED:
            return state.snapshot()
        if state.status is not GoalStatus.ACTIVE:
            raise GoalError(
                "status_invalid",
                f'Cannot pause a goal in status "{state.status.value}"',
            )
        return self._set_status(GoalStatus.PAUSED, reason or "Paused by user", actor)

    def resume(
        self,
        reason: str | None = None,
        actor: GoalActor = GoalActor.USER,
        *,
        mode: str = "agent",
        launch: bool = True,
    ) -> tuple[GoalSnapshot, ContinuationDecision]:
        if actor is GoalActor.MODEL:
            raise GoalError("user_controlled", "Only the user can resume a goal; use /goal resume.")
        self.assert_mode_allows_run(mode)
        state = self._require()
        if state.evidence_overflow:
            raise GoalError("evidence_overflow", "Review the transcript and replace this goal; its evidence index overflowed")
        if state.status is GoalStatus.COMPLETE and self._queue.peek_next() is not None:
            item = self._queue.peek_next()
            snapshot = self.create(item.objective, mode=mode, actor=actor, queue_item_id=item.item_id)
            return snapshot, (self.peek_continuation(mode=mode) if launch
                              else ContinuationDecision(False, reason="no_launch"))
        if state.status is GoalStatus.ACTIVE:
            return state.snapshot(), self.peek_continuation(mode=mode)
        if state.status not in (GoalStatus.PAUSED, GoalStatus.BLOCKED, GoalStatus.BUDGET_LIMITED):
            raise GoalError(
                "not_resumable",
                f'Cannot resume a goal in status "{state.status.value}"',
            )
        self._state = replace(state, stalled_turns=0, last_progress_signature="")
        snapshot = self._set_status(GoalStatus.ACTIVE, reason, actor)
        blocked = self._block_if_budget_reached(actor=GoalActor.RUNTIME)
        if blocked is not None:
            return blocked, ContinuationDecision(False, reason="budget")
        decision = (
            self.peek_continuation(mode=mode)
            if launch
            else ContinuationDecision(False, reason="no_launch")
        )
        return snapshot, decision

    def cancel(self, actor: GoalActor = GoalActor.USER) -> GoalSnapshot:
        state = self._require()
        snapshot = state.snapshot()
        self._clear(actor, emit=True)
        return snapshot

    def mark_complete(
        self,
        reason: str | None = None,
        actor: GoalActor = GoalActor.MODEL,
        *,
        evidence: object = None,
        audit: object = None,
    ) -> tuple[GoalSnapshot, GoalQueueItem | None]:
        self.validate_completion(reason, evidence, audit)
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            raise GoalError("not_found", "No active goal")
        self._state = apply_status(state, GoalStatus.COMPLETE, reason=reason)
        snapshot = self._state.snapshot()
        self._emit(
            snapshot,
            GoalChange(
                GoalChangeKind.COMPLETION,
                GoalStatus.COMPLETE,
                reason,
                actor,
            ),
        )
        promoted = self._queue.peek_next()
        self._last_promoted = promoted
        return snapshot, promoted

    def reopen(self, *, mode: str = "agent") -> tuple[GoalSnapshot, ContinuationDecision]:
        self.assert_mode_allows_run(mode)
        state = self._require()
        if state.status is not GoalStatus.COMPLETE:
            raise GoalError("status_invalid", "Only a completed goal can be reopened")
        # A reopened goal must be checked again against the current workspace.
        self.discard_promoted()
        self._state = replace(state, evidence=[], completion_evidence=(), completion_audit={})
        self._set_status(GoalStatus.PAUSED, "Reopened by user", GoalActor.USER)
        return self.resume(mode=mode)

    def save_checklist(self, items: list[dict[str, str]]) -> None:
        state = self._state
        if state is None or state.status is GoalStatus.COMPLETE or items == state.checklist:
            return
        # Dropping a plan item is not proof that its work disappeared.
        incoming = {item["id"]: dict(item) for item in items}
        for item in state.checklist:
            if item["id"] not in incoming and item["status"] != "completed":
                incoming[item["id"]] = dict(item)
        self._state = replace(state, checklist=list(incoming.values()))
        self._emit(
            self.snapshot(),
            GoalChange(GoalChangeKind.PROGRESS, state.status, actor=GoalActor.RUNTIME),
        )

    def observe_workspace(self, digest: str | None) -> None:
        state = self._state
        if state is None or state.status is GoalStatus.COMPLETE:
            return
        previous = self._workspace_digest
        self._workspace_digest = digest
        if digest is None or (previous is not None and digest != previous):
            self._state = replace(state, work_revision=state.work_revision + 1)
            self._emit(
                self.snapshot(),
                GoalChange(GoalChangeKind.PROGRESS, state.status, actor=GoalActor.RUNTIME),
            )

    def record_tool_result(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        *,
        success: bool,
        mutates: bool = False,
        finished: bool = True,
        verification: bool = True,
        output: str = "",
    ) -> None:
        state = self._state
        if state is None or state.status is GoalStatus.COMPLETE:
            return
        if name in GOAL_TOOL_NAMES or name == "checklist":
            return
        if state.status is not GoalStatus.ACTIVE:
            if mutates:
                self._state = replace(state, work_revision=state.work_revision + 1)
                self._emit(
                    self.snapshot(),
                    GoalChange(GoalChangeKind.PROGRESS, state.status, actor=GoalActor.RUNTIME),
                )
            return
        self._turn_work_calls += 1
        revision = state.work_revision + int(mutates)
        signature = hashlib.sha256(
            (name + json.dumps(arguments, sort_keys=True, ensure_ascii=False)).encode()
        ).hexdigest()
        output_digest = hashlib.sha256(output.encode()).hexdigest()
        self._turn_observations.append(signature + output_digest)
        self._turn_pending_work = self._turn_pending_work or not finished
        if name == "exec_shell":
            try:
                command = shlex.split(str(arguments.get("command") or ""))
            except ValueError:
                command = []
            # Environment discovery is useful work but cannot verify a deliverable.
            if command and command[0] in {"pwd", "whoami", "hostname", "date", "echo", "printf", "true"}:
                verification = False
        record = {
            "tool_call_id": call_id,
            "tool": name,
            "signature": signature,
            "description": str(arguments.get("command") or arguments.get("path") or name)[:240],
            "success": success,
            "finished": finished,
            "revision": revision,
            "verification": verification and not mutates,
            "output_excerpt": output[:512],
            "output_sha256": output_digest,
        }
        records = [*state.evidence, record]
        latest = {item["signature"]: item for item in records}
        # Keep unresolved failures even when successful history rolls over.
        recent_ids = {item["tool_call_id"] for item in records[-80:]}
        retained = [item for item in latest.values()
                    if not item["success"] and item["tool_call_id"] not in recent_ids]
        overflow = state.evidence_overflow or len(retained) > MAX_UNRESOLVED_FAILURES
        self._state = replace(
            state, work_revision=revision,
            evidence=[*retained[:MAX_UNRESOLVED_FAILURES], *records[-80:]],
            evidence_overflow=overflow,
        )
        if overflow:
            self._set_status(
                GoalStatus.PAUSED,
                "Goal evidence capacity exceeded; some failures cannot remain in the active index. "
                "Review the transcript and start a replacement goal with a bounded scope. "
                "This goal cannot be marked complete from incomplete evidence.",
                GoalActor.RUNTIME,
            )
            return
        self._emit(
            self.snapshot(),
            GoalChange(GoalChangeKind.PROGRESS, state.status, actor=GoalActor.RUNTIME),
        )

    def add_requirements(self, items: object) -> GoalSnapshot:
        state = self._require()
        if state.status is not GoalStatus.ACTIVE:
            raise GoalError("status_invalid", "Only an active goal can add acceptance requirements")
        if (
            not isinstance(items, list)
            or not items
            or len(items) > 64
            or any(not isinstance(item, str) or not item.strip() for item in items)
        ):
            raise GoalError(
                "requirements_invalid", "Provide nonempty acceptance requirement strings"
            )
        requirements = {item["id"]: dict(item) for item in state.requirements}
        for content in items:
            content = content.strip()
            key = hashlib.sha256(content.encode()).hexdigest()[:16]
            requirements.setdefault(key, {"id": key, "content": content})
        self._state = replace(state, requirements=list(requirements.values()))
        snapshot = self._state.snapshot()
        self._emit(
            snapshot, GoalChange(GoalChangeKind.PROGRESS, state.status, actor=GoalActor.MODEL)
        )
        return snapshot

    def validate_completion(
        self, reason: str | None, evidence: object, audit: object = None
    ) -> None:
        if self._state is None:
            raise GoalError("not_found", "No active goal")
        self._block_if_budget_reached(actor=GoalActor.RUNTIME, include_turn=False)
        state = self._require()
        if state.evidence_overflow:
            raise GoalError("evidence_overflow", "Evidence history exceeded capacity; review and replace this goal before completing")
        if state.status is not GoalStatus.ACTIVE:
            raise GoalError("status_invalid", "Only an active goal can complete")
        open_items = [
            item["content"]
            for item in state.checklist
            if item["status"] in {"pending", "in_progress"}
        ]
        if open_items:
            raise GoalError("incomplete", "Required work remains: " + "; ".join(open_items))
        if not reason or not isinstance(evidence, list) or not evidence:
            raise GoalError(
                "evidence_required",
                "Provide a completion audit in reason and actual "
                "tool call IDs in evidence. Use GetGoal to inspect recorded evidence.",
            )
        by_id = {item["tool_call_id"]: item for item in state.evidence}
        latest = {item["signature"]: item for item in state.evidence}
        for call_id in evidence:
            item = by_id.get(call_id) if isinstance(call_id, str) else None
            if (
                item is None
                or not item["success"]
                or not item["finished"]
                or not item["verification"]
                or item["revision"] != state.work_revision
                or latest[item["signature"]]["tool_call_id"] != call_id
            ):
                raise GoalError(
                    "evidence_invalid",
                    f"Evidence {call_id!r} is missing, failed, "
                    "unfinished, not a stable verification, superseded, "
                    "or predates a workspace edit. "
                    "Verify the current result before completing.",
                )
        if not isinstance(audit, dict) or not isinstance(audit.get("checks"), list):
            raise GoalError("audit_required", "Supply audit.checks for every GetGoal requirement")
        checks = audit["checks"]
        required = {item["id"] for item in state.requirements}
        seen = set()
        for check in checks:
            if not isinstance(check, dict):
                raise GoalError("audit_invalid", "Each check must identify a requirement")
            key = check.get("requirement_id")
            refs = check.get("evidence")
            if (
                not isinstance(key, str)
                or key not in required
                or key in seen
                or not isinstance(check.get("explanation"), str)
                or not check["explanation"].strip()
                or not isinstance(refs, list)
                or not refs
                or any(not isinstance(ref, str) or ref not in evidence for ref in refs)
            ):
                raise GoalError(
                    "audit_invalid", "Each requirement needs an explanation and cited evidence"
                )
            seen.add(key)
        if seen != required:
            raise GoalError(
                "incomplete", "Unverified requirements: " + ", ".join(sorted(required - seen))
            )
        # Failed explorations are legitimate, but cannot silently disappear behind pwd/read success.
        failures = {item["tool_call_id"] for item in latest.values() if not item["success"]}
        resolutions = audit.get("failure_resolutions", [])
        resolved = set()
        if not isinstance(resolutions, list):
            raise GoalError("audit_invalid", "failure_resolutions must be a list")
        for resolution in resolutions:
            if not isinstance(resolution, dict):
                raise GoalError("audit_invalid", "Invalid failure resolution")
            key = resolution.get("tool_call_id")
            refs = resolution.get("evidence")
            if (
                not isinstance(key, str)
                or key not in failures
                or not isinstance(resolution.get("reason"), str)
                or not resolution["reason"].strip()
                or not isinstance(refs, list)
                or not refs
                or any(not isinstance(ref, str) or ref not in evidence for ref in refs)
            ):
                raise GoalError("audit_invalid", "Explain each failed check using current evidence")
            resolved.add(key)
        if failures - resolved:
            raise GoalError(
                "unresolved_failures",
                "Unresolved tool failures: " + ", ".join(sorted(failures - resolved)),
            )
        cancelled = {item["id"] for item in state.checklist if item["status"] == "cancelled"}
        adjustments = audit.get("plan_adjustments", [])
        adjusted = set()
        if not isinstance(adjustments, list):
            raise GoalError("audit_invalid", "plan_adjustments must be a list")
        for adjustment in adjustments:
            if (
                not isinstance(adjustment, dict)
                or not isinstance(adjustment.get("item_id"), str)
                or adjustment["item_id"] not in cancelled
                or not isinstance(adjustment.get("reason"), str)
                or not adjustment["reason"].strip()
            ):
                raise GoalError(
                    "audit_invalid", "Explain cancelled plan items; requirements remain mandatory"
                )
            adjusted.add(adjustment["item_id"])
        if cancelled - adjusted:
            raise GoalError(
                "incomplete", "Cancelled plan items need an explicit scope-preserving explanation"
            )
        self._state = replace(
            state,
            completion_evidence=tuple(evidence),
            completion_audit=json.loads(json.dumps(audit)),
        )

    def consume_promoted(self) -> GoalQueueItem | None:
        item = self._last_promoted
        self._last_promoted = None
        if item is None:
            return None
        current = self._queue.peek_next()
        if current is None or current.item_id != item.item_id:
            return None
        return item

    def acknowledge_promoted(self, item_id: str) -> None:
        if self._state is not None and self._state.queue_item_id == item_id:
            # Queue may have been reordered while a launch was pending.
            self._queue.items[:] = [item for item in self._queue.items if item.item_id != item_id]
            self._state = replace(self._state, queue_item_id=None)
        elif self._queue.remove_item(item_id) is None:
            return
        snapshot = self.snapshot()
        self._emit(
            snapshot,
            GoalChange(
                GoalChangeKind.PROGRESS,
                None if snapshot is None else snapshot.status,
                actor=GoalActor.RUNTIME,
            ),
        )

    def discard_promoted(self) -> None:
        self._last_promoted = None

    def mark_blocked(
        self,
        reason: str | None = None,
        actor: GoalActor = GoalActor.MODEL,
    ) -> GoalSnapshot:
        """Commit the model's blocker assessment.

        The three-occurrence rule is semantic model guidance, not a counter of
        arbitrary turns. Terminal impossibility is allowed immediately.
        """
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            raise GoalError("not_found", "No active goal")
        return self._set_status(GoalStatus.BLOCKED, reason or "Blocked", actor)

    def mark_budget_limited(self, reason: str) -> GoalSnapshot:
        return self._set_status(GoalStatus.BUDGET_LIMITED, reason, GoalActor.RUNTIME)

    def set_budget(
        self,
        *,
        token_budget: int | None = None,
        turn_budget: int | None = None,
        wall_clock_budget_ms: int | None = None,
        actor: GoalActor = GoalActor.USER,
    ) -> GoalSnapshot:
        state = self._require()
        if actor is GoalActor.MODEL:
            raise GoalError(
                "user_controlled", "Only the user can change budgets; use /goal budget."
            )
        provided = [
            value
            for value in (token_budget, turn_budget, wall_clock_budget_ms)
            if value is not None
        ]
        if not provided:
            raise GoalError("budget_empty", "Provide at least one goal budget")
        if token_budget is not None and token_budget <= 0:
            raise GoalError("budget_invalid", "Token budget must be a positive integer")
        if turn_budget is not None and turn_budget <= 0:
            raise GoalError("budget_invalid", "Turn budget must be a positive integer")
        if wall_clock_budget_ms is not None and not (
            MIN_WALL_CLOCK_BUDGET_MS <= wall_clock_budget_ms <= MAX_WALL_CLOCK_BUDGET_MS
        ):
            raise GoalError(
                "budget_invalid",
                "Wall-clock budget must be between 1000ms and 24 hours",
            )
        extra = GoalBudgetLimits(
            token_budget=token_budget,
            turn_budget=turn_budget,
            wall_clock_budget_ms=wall_clock_budget_ms,
        )
        self._state = replace(state, budget_limits=state.budget_limits.merged(extra))
        blocked = self._block_if_budget_reached(
            actor=GoalActor.RUNTIME, include_turn=not self._turn_counted
        )
        if blocked is not None:
            return blocked
        snapshot = self._state.snapshot()
        self._emit(snapshot, GoalChange(GoalChangeKind.LIFECYCLE, snapshot.status, actor=actor))
        return snapshot

    def enqueue(self, objective: str) -> GoalQueueItem:
        return self._queue.add(objective)

    def queue_remove(self, index: int) -> GoalQueueItem:
        return self._queue.remove(index)

    def queue_move(self, src: int, dest: int) -> None:
        self._queue.move(src, dest)

    def format_queue(self) -> str:
        if not self._queue.items:
            return "No upcoming goals."
        lines = ["Upcoming goals (hidden from the agent until the current goal completes):"]
        for idx, item in enumerate(self._queue.items, start=1):
            lines.append(f"{idx}. {item.objective}")
        return "\n".join(lines)

    def on_turn_started(self) -> GoalSnapshot | None:
        self._turn_work_calls = 0
        self._turn_observations: list[str] = []
        self._turn_pending_work = False
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            self._turn_counted = False
            return None
        blocked = self._block_if_budget_reached(actor=GoalActor.RUNTIME)
        if blocked is not None:
            return blocked
        if state.queue_item_id is not None:
            self.acknowledge_promoted(state.queue_item_id)
        self.adopt_current_turn()
        return None if self._state is None else self._state.snapshot()

    def adopt_current_turn(self) -> GoalSnapshot | None:
        """Count this live turn once if a goal became active mid-turn."""
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE or self._turn_counted:
            return None if state is None else state.snapshot()
        self._state = replace(state, turns_used=state.turns_used + 1)
        self._turn_counted = True
        snapshot = self._state.snapshot()
        self._emit(
            snapshot,
            GoalChange(
                GoalChangeKind.PROGRESS,
                GoalStatus.ACTIVE,
                actor=GoalActor.RUNTIME,
            ),
        )
        return snapshot

    def account_tokens(self, output_tokens: int) -> GoalSnapshot | None:
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            return None
        delta = max(0, int(output_tokens))
        if delta:
            self._state = replace(state, tokens_used=state.tokens_used + delta)
        blocked = self._block_if_budget_reached(
            actor=GoalActor.RUNTIME,
            include_turn=False,
        )
        if blocked is not None:
            return blocked
        if delta:
            snapshot = self._state.snapshot()
            self._emit(
                snapshot,
                GoalChange(
                    GoalChangeKind.PROGRESS,
                    GoalStatus.ACTIVE,
                    actor=GoalActor.RUNTIME,
                ),
            )
        return None

    def on_turn_ended(
        self,
        *,
        cancelled: bool = False,
        failed: bool = False,
        error_message: str | None = None,
        output_tokens: int = 0,
        mode: str = "agent",
        automatic: bool = False,
    ) -> ContinuationDecision:
        self.account_tokens(output_tokens)
        self._turn_counted = False
        state = self._state
        if state is None:
            return ContinuationDecision(False, reason="none")
        if cancelled and state.status is GoalStatus.ACTIVE:
            self._set_status(GoalStatus.PAUSED, "Paused after interruption", GoalActor.USER)
            return ContinuationDecision(False, reason="paused")
        if failed and state.status is GoalStatus.ACTIVE:
            reason = "Paused after runtime error"
            if error_message:
                reason = f"{reason}: {error_message}"
            self._set_status(GoalStatus.PAUSED, reason, GoalActor.RUNTIME)
            return ContinuationDecision(False, reason="paused")
        if state.status is not GoalStatus.ACTIVE:
            return ContinuationDecision(False, reason=state.status.value)
        blocked = self._block_if_budget_reached(actor=GoalActor.RUNTIME)
        if blocked is not None:
            return ContinuationDecision(False, reason="budget")
        normalized_mode = (mode or "agent").strip() or "agent"
        if normalized_mode not in ALLOWED_GOAL_MODES:
            self._set_status(
                GoalStatus.PAUSED,
                f"Paused after mode changed to {normalized_mode}",
                GoalActor.RUNTIME,
            )
            return ContinuationDecision(False, reason="mode")
        if automatic and not self._turn_work_calls:
            self._set_status(
                GoalStatus.PAUSED,
                "Automatic continuation made no work tool calls; resume to continue.",
                GoalActor.RUNTIME,
            )
            return ContinuationDecision(False, reason="no_progress")
        progress = hashlib.sha256(
            json.dumps(
                {
                    "results": sorted(self._turn_observations),
                    "revision": state.work_revision,
                    "checklist": state.checklist,
                    "requirements": state.requirements,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        stalled = (
            state.stalled_turns + 1
            if automatic
            and not self._turn_pending_work
            and state.last_progress_signature == progress
            else 0
        )
        self._state = replace(state, last_progress_signature=progress, stalled_turns=stalled)
        if stalled >= 3:
            self._set_status(
                GoalStatus.PAUSED,
                "Repeated identical tool results without progress for three continuation turns. "
                "Review the blocker or strategy before resuming.",
                GoalActor.RUNTIME,
            )
            return ContinuationDecision(False, reason="no_progress")
        return self.peek_continuation(mode=normalized_mode)

    def peek_continuation(self, *, mode: str = "agent") -> ContinuationDecision:
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            return ContinuationDecision(False, reason="inactive")
        normalized_mode = (mode or "agent").strip() or "agent"
        if normalized_mode not in ALLOWED_GOAL_MODES:
            return ContinuationDecision(False, reason="mode")
        if state.snapshot().budget.over_budget:
            return ContinuationDecision(False, reason="budget")
        return ContinuationDecision(True, prompt=GOAL_CONTINUATION_PROMPT, reason="active")

    def reminder_text(self) -> str:
        snapshot = self.snapshot()
        if snapshot is None:
            return ""
        return reminder_body(snapshot)

    def format_status(self) -> str:
        snapshot = self.snapshot()
        if snapshot is None:
            queued = self.format_queue()
            if queued == "No upcoming goals.":
                return "No current goal."
            return f"No current goal.\n\n{queued}"
        lines = [
            f"Status: {snapshot.status.value}",
            f"Objective: {snapshot.objective}",
        ]
        if snapshot.completion_criterion:
            lines.append(f"Done when: {snapshot.completion_criterion}")
        if snapshot.terminal_reason:
            lines.append(f"Reason: {snapshot.terminal_reason}")
        lines.append(
            f"Progress: {snapshot.turns_used} turns, {snapshot.tokens_used} tokens, "
            f"{snapshot.wall_clock_ms}ms"
        )
        budget = snapshot.budget
        if budget.turn_budget or budget.token_budget or budget.wall_clock_budget_ms:
            lines.append(
                "Budget: "
                f"turns {snapshot.turns_used}/{budget.turn_budget or '—'} · "
                f"tokens {snapshot.tokens_used}/{budget.token_budget or '—'} · "
                f"time {snapshot.wall_clock_ms}/{budget.wall_clock_budget_ms or '—'}ms"
            )
        queued = self.format_queue()
        if snapshot.status is GoalStatus.COMPLETE and self._queue.peek_next() is not None:
            lines.append("Use /goal resume to start the next queued goal.")
        if queued != "No upcoming goals.":
            lines.append("")
            lines.append(queued)
        return "\n".join(lines)

    def _set_status(self, status: GoalStatus, reason: str | None, actor: GoalActor) -> GoalSnapshot:
        state = self._require()
        if actor is GoalActor.USER:
            self.control_epoch += 1
        self._state = apply_status(state, status, reason=reason)
        snapshot = self._state.snapshot()
        self._emit(snapshot, GoalChange(GoalChangeKind.LIFECYCLE, status, reason, actor))
        return snapshot

    def _block_if_budget_reached(
        self,
        *,
        actor: GoalActor,
        include_turn: bool = True,
    ) -> GoalSnapshot | None:
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            return None
        report = compute_budget_report(
            state.budget_limits,
            state.tokens_used,
            state.turns_used,
            state.live_wall_clock_ms(),
        )
        if report.turn_budget_reached and not include_turn:
            report = replace(
                report,
                turn_budget_reached=False,
                over_budget=(report.token_budget_reached or report.wall_clock_budget_reached),
            )
        reason = budget_block_reason(report)
        if reason is None:
            return None
        return self._set_status(GoalStatus.BUDGET_LIMITED, reason, actor)

    def _clear(self, actor: GoalActor, *, emit: bool) -> None:
        self._state = None
        self._turn_counted = False
        self._last_promoted = None
        if emit:
            self._emit(None, GoalChange(GoalChangeKind.CLEARED, actor=actor))

    def _require(self) -> GoalState:
        if self._state is None:
            raise GoalError("not_found", "No current goal")
        return self._state

    def _emit(self, snapshot: GoalSnapshot | None, change: GoalChange) -> None:
        self.changed.set()
        if self._on_update is not None:
            self._on_update(snapshot, change)
