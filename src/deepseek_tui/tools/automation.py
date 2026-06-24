"""Automation — tools, manager, and scheduler.

Consolidates automation_tools.py, automation_manager.py, automation_scheduler.py.
"""

from __future__ import annotations



# Model-visible automation tools backed by :class:`AutomationManager`.
#
# Mirrors Rust ``crates/tui/src/tools/automation.rs`` (382 LOC).
#
# Eight tools:
#
# ================== ================================================
# ``automation_create``    create a durable scheduled automation (REQUIRES_APPROVAL)
# ``automation_list``      list automations with status / next_run / last_run
# ``automation_read``      detailed view of one automation + recent runs
# ``automation_update``    edit name / prompt / rrule / cwds / status
# ``automation_pause``     pause an active automation
# ``automation_resume``    resume a paused automation
# ``automation_delete``    delete (also wipes the automation's run history)
# ``automation_run``       enqueue a one-off run right now
# ================== ================================================
#
# The ``AutomationManager`` lives on ``ToolContext.metadata`` under the
# key :data:`AUTOMATION_MANAGER_KEY`, set by ``Engine.create`` when the
# feature flag is enabled. If no manager is attached (feature flag off),
# each tool returns a clean error so the LLM can fall back gracefully.
#
from dataclasses import asdict
from typing import Any, cast

from deepseek_tui.tools.validation import optional_string as _optional_string
from deepseek_tui.tools.validation import require_string as _require_string
from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext

__all__ = [
    "AUTOMATION_MANAGER_KEY",
    "AutomationCreateTool",
    "AutomationDeleteTool",
    "AutomationListTool",
    "AutomationPauseTool",
    "AutomationReadTool",
    "AutomationResumeTool",
    "AutomationRunTool",
    "AutomationUpdateTool",
]


AUTOMATION_MANAGER_KEY = "automation_manager"


# ── helpers ─────────────────────────────────────────────────────────


def _get_manager(context: ToolContext) -> AutomationManager:
    """Pull the ``AutomationManager`` off the context, or raise.

    Mirrors Rust ``context.runtime.automations`` ``ok_or_else``
    (automation.rs:62-66).
    """
    raw = context.metadata.get(AUTOMATION_MANAGER_KEY)
    if raw is None:
        raise ToolError(
            "AutomationManager is not attached "
            "(set features.automations=true in config)"
        )
    if not isinstance(raw, AutomationManager):
        raise ToolError("automation manager attached on context is invalid")
    return raw




def _optional_string_list(
    input_data: dict[str, object], key: str
) -> list[str] | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ToolError(f"{key} must be an array of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ToolError(f"{key} entries must be strings")
        out.append(item)
    return out


def _optional_int(input_data: dict[str, object], key: str) -> int | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolError(f"{key} must be an integer")
    return value


def _optional_object(
    input_data: dict[str, object], key: str
) -> dict[str, Any] | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ToolError(f"{key} must be an object")
    return cast(dict[str, Any], value)


def _automation_to_payload(record: Any) -> dict[str, Any]:
    """Serialize an ``AutomationRecord`` for tool metadata."""
    return record.to_dict()


def _format_summary_line(record: Any) -> str:
    next_run = record.next_run_at or "—"
    last_run = record.last_run_at or "—"
    return (
        f"{record.id[:8]} | {record.status.value:<8} | "
        f"next={next_run} | last={last_run} | {record.name}"
    )


# ── tool implementations ────────────────────────────────────────────


def _resolve_delivery(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fill default Feishu ``to`` from config when the model omits it."""
    if raw is None:
        return None
    delivery = dict(raw)
    mode = str(delivery.get("mode", "silent")).strip().lower()
    if mode == "feishu":
        to_val = delivery.get("to") or delivery.get("chat_id")
        if not (isinstance(to_val, str) and to_val.strip()):
            from deepseek_tui.automation.inbox import default_feishu_chat_id_from_config

            default = default_feishu_chat_id_from_config()
            if default:
                delivery["to"] = default
    return delivery


class AutomationCreateTool(ToolSpec):
    """Create a durable scheduled automation (requires approval)."""

    def name(self) -> str:
        return "automation_create"

    def description(self) -> str:
        return (
            "Create a durable scheduled automation that enqueues an agent "
            "task on a schedule. Call current_time first when the user uses "
            "relative times ('in 10 minutes', 'tomorrow morning'). "
            "Recurring jobs use rrule (FREQ=HOURLY;INTERVAL=N or "
            "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=30). One-shot or "
            "delayed runs set next_run_at (ISO8601) and may use a far-future "
            "placeholder rrule such as FREQ=HOURLY;INTERVAL=8760. Optional "
            "delivery sends the task summary to feishu or email after "
            "completion. For feishu include delivery.mode=feishu and "
            "delivery.to (open_chat_id). Creation requires approval."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "prompt": {"type": "string"},
                "rrule": {
                    "type": "string",
                    "description": (
                        "Supported: FREQ=HOURLY;INTERVAL=N[;BYDAY=MO,TU] "
                        "or FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=30"
                    ),
                },
                "next_run_at": {
                    "type": "string",
                    "description": (
                        "Optional ISO8601 timestamp for the first run "
                        "(one-shot or delayed start)."
                    ),
                },
                "cwds": {"type": "array", "items": {"type": "string"}},
                "delivery": {
                    "type": "object",
                    "description": (
                        "Optional post-run delivery (feishu or email)."
                    ),
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["feishu", "email", "silent", "notify"],
                        },
                        "to": {
                            "type": "string",
                            "description": (
                                "Recipient: Feishu open_chat_id or email address. "
                                "Required when mode is feishu or email."
                            ),
                        },
                        "best_effort": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "paused": {"type": "boolean", "default": False},
            },
            "required": ["name", "prompt", "rrule"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        manager = _get_manager(context)
        name = _require_string(input_data, "name")
        prompt = _require_string(input_data, "prompt")
        rrule = _require_string(input_data, "rrule")
        next_run_at = _optional_string(input_data, "next_run_at")
        cwds = _optional_string_list(input_data, "cwds") or []
        delivery = _resolve_delivery(_optional_object(input_data, "delivery"))
        paused = bool(input_data.get("paused", False))
        status = AutomationStatus.PAUSED if paused else AutomationStatus.ACTIVE
        try:
            record = manager.create_automation(
                CreateAutomationRequest(
                    name=name,
                    prompt=prompt,
                    rrule=rrule,
                    cwds=cwds,
                    status=status,
                    delivery=delivery,
                    next_run_at=next_run_at,
                )
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content=record.id,
            metadata={"automation": _automation_to_payload(record)},
        )


class AutomationListTool(ToolSpec):
    def name(self) -> str:
        return "automation_list"

    def description(self) -> str:
        return (
            "List durable automations with status, next run, and last run "
            "timestamps."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50,
                }
            },
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        manager = _get_manager(context)
        limit = _optional_int(input_data, "limit") or 50
        records = manager.list_automations()[:limit]
        lines = [_format_summary_line(r) for r in records]
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "automations": [_automation_to_payload(r) for r in records],
                "count": len(records),
            },
        )


class AutomationReadTool(ToolSpec):
    def name(self) -> str:
        return "automation_read"

    def description(self) -> str:
        return (
            "Read details of an automation including its recent run "
            "history."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "automation_id": {"type": "string"},
                "runs_limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["automation_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        manager = _get_manager(context)
        automation_id = _require_string(input_data, "automation_id")
        runs_limit = _optional_int(input_data, "runs_limit") or 10
        try:
            record = manager.get_automation(automation_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        runs = manager.list_runs(automation_id, limit=runs_limit)
        lines = [
            _format_summary_line(record),
            f"prompt: {record.prompt}",
            f"rrule:  {record.rrule}",
            f"cwds:   {record.cwds}",
            f"runs ({len(runs)}):",
        ]
        for run in runs:
            lines.append(
                f"  {run.id[:8]} | {run.status.value:<10} | "
                f"scheduled={run.scheduled_for} | task={run.task_id or '—'}"
            )
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "automation": _automation_to_payload(record),
                "runs": [r.to_dict() for r in runs],
            },
        )


class AutomationUpdateTool(ToolSpec):
    def name(self) -> str:
        return "automation_update"

    def description(self) -> str:
        return "Update an automation's name, prompt, rrule, cwds, or status."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "automation_id": {"type": "string"},
                "name": {"type": "string"},
                "prompt": {"type": "string"},
                "rrule": {"type": "string"},
                "cwds": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": ["active", "paused"]},
            },
            "required": ["automation_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        manager = _get_manager(context)
        automation_id = _require_string(input_data, "automation_id")
        status_raw = _optional_string(input_data, "status")
        status: AutomationStatus | None = None
        if status_raw is not None:
            try:
                status = AutomationStatus(status_raw)
            except ValueError as exc:
                raise ToolError(
                    f"status must be 'active' or 'paused' (got {status_raw!r})"
                ) from exc
        req = UpdateAutomationRequest(
            name=_optional_string(input_data, "name"),
            prompt=_optional_string(input_data, "prompt"),
            rrule=_optional_string(input_data, "rrule"),
            cwds=_optional_string_list(input_data, "cwds"),
            status=status,
        )
        try:
            record = manager.update_automation(automation_id, req)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content="updated",
            metadata={"automation": _automation_to_payload(record)},
        )


class AutomationPauseTool(ToolSpec):
    def name(self) -> str:
        return "automation_pause"

    def description(self) -> str:
        return "Pause an active automation."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"automation_id": {"type": "string"}},
            "required": ["automation_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        manager = _get_manager(context)
        automation_id = _require_string(input_data, "automation_id")
        try:
            record = manager.pause_automation(automation_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content="paused",
            metadata={"automation": _automation_to_payload(record)},
        )


class AutomationResumeTool(ToolSpec):
    def name(self) -> str:
        return "automation_resume"

    def description(self) -> str:
        return "Resume a paused automation."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"automation_id": {"type": "string"}},
            "required": ["automation_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        manager = _get_manager(context)
        automation_id = _require_string(input_data, "automation_id")
        try:
            record = manager.resume_automation(automation_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content="resumed",
            metadata={"automation": _automation_to_payload(record)},
        )


class AutomationDeleteTool(ToolSpec):
    def name(self) -> str:
        return "automation_delete"

    def description(self) -> str:
        return (
            "Delete an automation and wipe its run history. Requires "
            "approval."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"automation_id": {"type": "string"}},
            "required": ["automation_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        manager = _get_manager(context)
        automation_id = _require_string(input_data, "automation_id")
        try:
            record = manager.delete_automation(automation_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content="deleted",
            metadata={"automation_id": record.id},
        )


class AutomationRunTool(ToolSpec):
    """Manually fire an automation right now (one-off run)."""

    def name(self) -> str:
        return "automation_run"

    def description(self) -> str:
        return (
            "Manually trigger an automation immediately. Requires approval. "
            "The triggered run is enqueued as a normal durable task."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"automation_id": {"type": "string"}},
            "required": ["automation_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        manager = _get_manager(context)
        automation_id = _require_string(input_data, "automation_id")

        # The run_now path requires a TaskManager — pick it up off the
        # context the same way Rust does (``runtime.task_manager``).
        from deepseek_tui.tools.task import TaskManager

        task_manager_raw = context.metadata.get("task_manager")
        if not isinstance(task_manager_raw, TaskManager):
            raise ToolError(
                "TaskManager is not attached "
                "(set features.tasks=true to enable run_now)"
            )
        task_manager = cast(TaskManager, task_manager_raw)

        try:
            run = await manager.run_now(automation_id, task_manager)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content=f"queued run {run.id[:8]} (task_id={run.task_id or '—'})",
            metadata={"run": run.to_dict()},
        )


# ``asdict`` is no longer used directly here, but kept importable for
# downstream tests that referenced it on the prior implementation.
_ = asdict


# Durable automation records and scheduler-supporting manager.
#
# Mirrors Rust ``crates/tui/src/automation_manager.rs`` (937 LOC).
#
# Automations are local-first recurring jobs that **enqueue standard
# durable tasks**. This module stores automation definitions and run
# history under ``~/.deepseek/automations/`` (or
# ``DEEPSEEK_AUTOMATIONS_DIR`` override).
#
# Layout::
#
#     <root>/
#       automations/<id>.json          ← one AutomationRecord
#       runs/<automation_id>/<run_id>.json  ← one AutomationRunRecord per fire
#
# The scheduler tick (see ``automation_scheduler.run_scheduler_loop``)
# calls :meth:`AutomationManager.scheduler_tick` and
# :meth:`AutomationManager.reconcile_run_statuses` on a fixed cadence.
#
# Every disk write goes through ``write_json_atomic`` (tmp file + rename)
# so partially-written records cannot survive a crash.
#
# RRULE subset matches Rust :class:`AutomationSchedule`:
#
# * ``FREQ=HOURLY;INTERVAL=N[;BYDAY=MO,TU]``
# * ``FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=9;BYMINUTE=30``
#
# Times in ``next_after`` are computed in **local time** (matches Rust
# ``with_timezone(&Local)`` at automation_manager.rs:223) so a user with
# a 9am rule fires at their local 9am, not UTC 9am.
#
import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepseek_tui.tools.task import TaskManager

__all__ = [
    "CURRENT_AUTOMATION_SCHEMA_VERSION",
    "CURRENT_RUN_SCHEMA_VERSION",
    "AutomationManager",
    "AutomationRecord",
    "AutomationRunRecord",
    "AutomationRunStatus",
    "AutomationSchedule",
    "AutomationStatus",
    "CreateAutomationRequest",
    "UpdateAutomationRequest",
    "default_automations_dir",
    "validate_name_and_prompt",
]

logger = logging.getLogger(__name__)

CURRENT_AUTOMATION_SCHEMA_VERSION = 1
CURRENT_RUN_SCHEMA_VERSION = 1

# Mapping the Rust ``Weekday`` enum (Mon=0…Sun=6) to Python ``datetime``
# weekday integers. Python ``datetime.weekday()`` already uses the same
# 0..6 Monday-first convention so the mapping is the identity, but we
# keep an explicit table so ``parse_byday`` round-trips cleanly with the
# string forms Rust accepts.
_WEEKDAY_BY_TOKEN: dict[str, int] = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}


class AutomationStatus(str, Enum):
    """Mirrors Rust ``AutomationStatus`` (snake_case on the wire)."""

    ACTIVE = "active"
    PAUSED = "paused"


class AutomationRunStatus(str, Enum):
    """Mirrors Rust ``AutomationRunStatus``."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


# ─────────────────────────────────────────────────────────────────────
# RRULE parsing — Rust automation_manager.rs:120-296
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Hourly:
    interval_hours: int
    byday: tuple[int, ...] | None  # weekday ints; None = all days


@dataclass(frozen=True, slots=True)
class _Weekly:
    byday: tuple[int, ...]  # non-empty
    byhour: int
    byminute: int


class AutomationSchedule:
    """Parsed RRULE for an automation.

    Wraps a ``_Hourly | _Weekly`` payload. Constructed via
    :meth:`parse_rrule`. The ``next_after`` method computes the next UTC
    fire time strictly after ``after``.
    """

    __slots__ = ("_payload",)

    def __init__(self, payload: _Hourly | _Weekly) -> None:
        self._payload = payload

    @property
    def is_hourly(self) -> bool:
        return isinstance(self._payload, _Hourly)

    @property
    def is_weekly(self) -> bool:
        return isinstance(self._payload, _Weekly)

    @property
    def payload(self) -> _Hourly | _Weekly:
        return self._payload

    @classmethod
    def parse_rrule(cls, rrule: str) -> AutomationSchedule:
        """Parse an RRULE string. Raises :class:`ValueError` on bad input.

        Mirrors Rust ``AutomationSchedule::parse_rrule`` (132-220).
        """
        parts: dict[str, str] = {}
        for raw in rrule.split(";"):
            item = raw.strip()
            if not item:
                continue
            if "=" not in item:
                raise ValueError(f"Invalid RRULE segment '{item}'")
            k, v = item.split("=", 1)
            parts[k.strip().upper()] = v.strip().upper()

        freq = parts.get("FREQ")
        if freq is None:
            raise ValueError("RRULE must include FREQ")

        if freq == "HOURLY":
            for key in parts:
                if key not in ("FREQ", "INTERVAL", "BYDAY"):
                    raise ValueError(
                        f"Unsupported RRULE field '{key}' for HOURLY. "
                        "Allowed: FREQ,INTERVAL,BYDAY"
                    )
            try:
                interval_hours = int(parts.get("INTERVAL", "1"))
            except ValueError as exc:
                raise ValueError("Failed to parse INTERVAL") from exc
            if interval_hours < 1:
                raise ValueError("INTERVAL must be >= 1 for HOURLY schedules")
            byday_raw = parts.get("BYDAY")
            byday = tuple(_parse_byday(byday_raw)) if byday_raw is not None else None
            return cls(_Hourly(interval_hours=interval_hours, byday=byday))

        if freq == "WEEKLY":
            for key in parts:
                if key not in ("FREQ", "BYDAY", "BYHOUR", "BYMINUTE"):
                    raise ValueError(
                        f"Unsupported RRULE field '{key}' for WEEKLY. "
                        "Allowed: FREQ,BYDAY,BYHOUR,BYMINUTE"
                    )
            byday_raw = parts.get("BYDAY")
            if byday_raw is None:
                raise ValueError("WEEKLY schedules require BYDAY")
            byday_list = _parse_byday(byday_raw)
            if not byday_list:
                raise ValueError("BYDAY cannot be empty for WEEKLY schedules")
            byhour_raw = parts.get("BYHOUR")
            byminute_raw = parts.get("BYMINUTE")
            if byhour_raw is None:
                raise ValueError("WEEKLY schedules require BYHOUR")
            if byminute_raw is None:
                raise ValueError("WEEKLY schedules require BYMINUTE")
            try:
                byhour = int(byhour_raw)
            except ValueError as exc:
                raise ValueError("Failed to parse BYHOUR") from exc
            try:
                byminute = int(byminute_raw)
            except ValueError as exc:
                raise ValueError("Failed to parse BYMINUTE") from exc
            if byhour > 23:
                raise ValueError("BYHOUR must be between 0 and 23")
            if byminute > 59:
                raise ValueError("BYMINUTE must be between 0 and 59")
            return cls(_Weekly(byday=tuple(byday_list), byhour=byhour, byminute=byminute))

        raise ValueError(
            f"Unsupported RRULE FREQ '{freq}'. Supported: HOURLY and WEEKLY"
        )

    def next_after(self, after: datetime) -> datetime:
        """Compute the next fire time strictly after ``after``.

        Both input and output are timezone-aware UTC ``datetime``s.
        Internally we convert to local time so weekly BYHOUR=9 fires at
        the user's 9am, mirroring Rust automation_manager.rs:223.
        """
        if after.tzinfo is None:
            raise ValueError("after must be timezone-aware")
        local_after = after.astimezone()  # local timezone
        payload = self._payload

        if isinstance(payload, _Hourly):
            # Strip seconds + microseconds, advance by INTERVAL hours.
            candidate = (
                local_after + timedelta(hours=payload.interval_hours)
            ).replace(second=0, microsecond=0)
            if payload.byday is not None:
                # Search up to 21 days ahead in INTERVAL-hour steps;
                # matches the Rust ``24 * 21`` cap (line 234).
                for _ in range(24 * 21):
                    if candidate.weekday() in payload.byday:
                        return candidate.astimezone(timezone.utc)
                    candidate += timedelta(hours=payload.interval_hours)
                raise ValueError(
                    "Unable to compute next HOURLY run for BYDAY filter"
                )
            return candidate.astimezone(timezone.utc)

        if isinstance(payload, _Weekly):
            for day_offset in range(15):
                date = (local_after + timedelta(days=day_offset)).date()
                if date.weekday() not in payload.byday:
                    continue
                candidate = local_after.replace(
                    year=date.year,
                    month=date.month,
                    day=date.day,
                    hour=payload.byhour,
                    minute=payload.byminute,
                    second=0,
                    microsecond=0,
                )
                if candidate > local_after:
                    return candidate.astimezone(timezone.utc)
            raise ValueError("Unable to compute next WEEKLY run")

        raise AssertionError("unreachable")


def _parse_byday(value: str) -> list[int]:
    """Mirrors Rust ``parse_byday`` (278-296)."""
    days: list[int] = []
    for token in value.split(","):
        key = token.strip().upper()
        if key not in _WEEKDAY_BY_TOKEN:
            raise ValueError(f"Invalid BYDAY value '{key}'")
        weekday = _WEEKDAY_BY_TOKEN[key]
        if weekday not in days:
            days.append(weekday)
    return days


# ─────────────────────────────────────────────────────────────────────
# Records
# ─────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class AutomationRecord:
    """Mirrors Rust ``AutomationRecord``. ``cwds`` is a list of strings
    (Path-like) so it round-trips through JSON without needing a custom
    encoder."""

    id: str
    name: str
    prompt: str
    rrule: str
    status: AutomationStatus
    created_at: str  # ISO 8601 UTC string
    updated_at: str
    cwds: list[str] = field(default_factory=list)
    next_run_at: str | None = None
    last_run_at: str | None = None
    delivery: dict[str, Any] | None = None
    digest: dict[str, Any] | None = None
    schema_version: int = CURRENT_AUTOMATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "rrule": self.rrule,
            "cwds": list(self.cwds),
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
        }
        if self.delivery is not None:
            out["delivery"] = dict(self.delivery)
        if self.digest is not None:
            out["digest"] = dict(self.digest)
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AutomationRecord:
        schema_version = int(raw.get("schema_version", CURRENT_AUTOMATION_SCHEMA_VERSION))
        if schema_version > CURRENT_AUTOMATION_SCHEMA_VERSION:
            raise ValueError(
                f"Automation schema v{schema_version} is newer than "
                f"supported v{CURRENT_AUTOMATION_SCHEMA_VERSION}"
            )
        return cls(
            schema_version=schema_version,
            id=str(raw["id"]),
            name=str(raw["name"]),
            prompt=str(raw["prompt"]),
            rrule=str(raw["rrule"]),
            cwds=[str(p) for p in raw.get("cwds", [])],
            status=AutomationStatus(raw["status"]),
            created_at=str(raw["created_at"]),
            updated_at=str(raw["updated_at"]),
            next_run_at=raw.get("next_run_at"),
            last_run_at=raw.get("last_run_at"),
            delivery=(
                dict(raw["delivery"])
                if isinstance(raw.get("delivery"), dict)
                else None
            ),
            digest=(
                dict(raw["digest"]) if isinstance(raw.get("digest"), dict) else None
            ),
        )


@dataclass(slots=True)
class AutomationRunRecord:
    """Mirrors Rust ``AutomationRunRecord``."""

    id: str
    automation_id: str
    scheduled_for: str
    status: AutomationRunStatus
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    task_id: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    error: str | None = None
    delivery_done: bool = False
    schema_version: int = CURRENT_RUN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "automation_id": self.automation_id,
            "scheduled_for": self.scheduled_for,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "error": self.error,
            "delivery_done": self.delivery_done,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AutomationRunRecord:
        schema_version = int(raw.get("schema_version", CURRENT_RUN_SCHEMA_VERSION))
        if schema_version > CURRENT_RUN_SCHEMA_VERSION:
            raise ValueError(
                f"Automation run schema v{schema_version} is newer than "
                f"supported v{CURRENT_RUN_SCHEMA_VERSION}"
            )
        return cls(
            schema_version=schema_version,
            id=str(raw["id"]),
            automation_id=str(raw["automation_id"]),
            scheduled_for=str(raw["scheduled_for"]),
            status=AutomationRunStatus(raw["status"]),
            created_at=str(raw["created_at"]),
            started_at=raw.get("started_at"),
            ended_at=raw.get("ended_at"),
            task_id=raw.get("task_id"),
            thread_id=raw.get("thread_id"),
            turn_id=raw.get("turn_id"),
            error=raw.get("error"),
            delivery_done=bool(raw.get("delivery_done", False)),
        )


@dataclass(slots=True)
class CreateAutomationRequest:
    name: str
    prompt: str
    rrule: str
    cwds: list[str] = field(default_factory=list)
    status: AutomationStatus | None = None
    delivery: dict[str, Any] | None = None
    digest: dict[str, Any] | None = None
    next_run_at: str | None = None


@dataclass(slots=True)
class UpdateAutomationRequest:
    name: str | None = None
    prompt: str | None = None
    rrule: str | None = None
    cwds: list[str] | None = None
    status: AutomationStatus | None = None
    delivery: dict[str, Any] | None = None
    digest: dict[str, Any] | None = None


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string back into an aware ``datetime``."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def validate_name_and_prompt(name: str, prompt: str) -> None:
    """Mirrors Rust ``validate_name_and_prompt`` (762-770)."""
    if not name.strip():
        raise ValueError("Automation name is required")
    if not prompt.strip():
        raise ValueError("Automation prompt is required")


def write_json_atomic(path: Path, value: Any) -> None:
    """Tmp file + ``os.replace`` — Rust ``write_json_atomic`` (772-788)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def default_automations_dir() -> Path:
    """``$DEEPSEEK_AUTOMATIONS_DIR`` or ``~/.deepseek/automations``.

    Mirrors Rust ``default_automations_dir`` (790-800).
    """
    override = os.environ.get("DEEPSEEK_AUTOMATIONS_DIR", "").strip()
    if override:
        return Path(override)
    home = Path.home()
    return home / ".deepseek" / "automations"


# ─────────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────────


class AutomationManager:
    """In-process automation registry.

    Mirrors Rust ``AutomationManager`` (299-760). All disk IO is
    synchronous (the records are tiny JSON files); the ``async`` methods
    only exist where they need to ``await`` ``TaskManager`` calls.

    By design (Q6=B), this manager is **not** internally locked. The
    scheduler loop runs on the same asyncio event loop as the tool
    dispatcher, and every disk write goes through ``write_json_atomic``,
    so concurrent state corruption is impossible without preemption.
    """

    def __init__(self, root: Path) -> None:
        self._automations_dir = root / "automations"
        self._runs_dir = root / "runs"
        self._automations_dir.mkdir(parents=True, exist_ok=True)
        self._runs_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def open(cls, root: Path) -> AutomationManager:
        return cls(root)

    @classmethod
    def default_location(cls) -> AutomationManager:
        return cls.open(default_automations_dir())

    # ── path helpers ──

    @property
    def automations_dir(self) -> Path:
        return self._automations_dir

    @property
    def runs_dir(self) -> Path:
        return self._runs_dir

    def _automation_path(self, automation_id: str) -> Path:
        return self._automations_dir / f"{automation_id}.json"

    def _runs_dir_for(self, automation_id: str) -> Path:
        return self._runs_dir / automation_id

    def _run_path(self, automation_id: str, run_id: str) -> Path:
        return self._runs_dir_for(automation_id) / f"{run_id}.json"

    # ── CRUD ──

    def create_automation(self, req: CreateAutomationRequest) -> AutomationRecord:
        """Mirrors Rust ``create_automation`` (335-362)."""
        validate_name_and_prompt(req.name, req.prompt)
        schedule = AutomationSchedule.parse_rrule(req.rrule)
        now = _utc_now()
        status = req.status or AutomationStatus.ACTIVE
        if req.next_run_at and str(req.next_run_at).strip():
            next_run_at = str(req.next_run_at).strip()
        elif status is AutomationStatus.ACTIVE:
            next_run_at = schedule.next_after(now).isoformat()
        else:
            next_run_at = None
        record = AutomationRecord(
            id=uuid.uuid4().hex,
            name=req.name.strip(),
            prompt=req.prompt.strip(),
            rrule=req.rrule.strip().upper(),
            cwds=list(req.cwds),
            status=status,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            next_run_at=next_run_at,
            last_run_at=None,
            delivery=dict(req.delivery) if req.delivery else None,
            digest=dict(req.digest) if req.digest else None,
        )
        self.save_automation(record)
        return record

    def get_automation(self, automation_id: str) -> AutomationRecord:
        path = self._automation_path(automation_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise KeyError(f"Automation {automation_id} not found") from exc
        return AutomationRecord.from_dict(json.loads(raw))

    def save_automation(self, record: AutomationRecord) -> None:
        write_json_atomic(self._automation_path(record.id), record.to_dict())

    def list_automations(self) -> list[AutomationRecord]:
        out: list[AutomationRecord] = []
        for entry in self._automations_dir.iterdir():
            if entry.suffix != ".json":
                continue
            try:
                raw = entry.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            out.append(AutomationRecord.from_dict(json.loads(raw)))
        out.sort(key=lambda r: r.updated_at, reverse=True)
        return out

    def update_automation(
        self, automation_id: str, req: UpdateAutomationRequest
    ) -> AutomationRecord:
        """Mirrors Rust ``update_automation`` (411-455)."""
        existing = self.get_automation(automation_id)

        if req.name is not None:
            if not req.name.strip():
                raise ValueError("Automation name cannot be empty")
            existing.name = req.name.strip()
        if req.prompt is not None:
            if not req.prompt.strip():
                raise ValueError("Automation prompt cannot be empty")
            existing.prompt = req.prompt.strip()
        if req.rrule is not None:
            normalized = req.rrule.strip().upper()
            AutomationSchedule.parse_rrule(normalized)
            existing.rrule = normalized
            if existing.status is AutomationStatus.ACTIVE:
                schedule = AutomationSchedule.parse_rrule(existing.rrule)
                existing.next_run_at = schedule.next_after(_utc_now()).isoformat()
        if req.cwds is not None:
            existing.cwds = list(req.cwds)
        if req.status is not None:
            existing.status = req.status
            if req.status is AutomationStatus.PAUSED:
                existing.next_run_at = None
            else:
                schedule = AutomationSchedule.parse_rrule(existing.rrule)
                existing.next_run_at = schedule.next_after(_utc_now()).isoformat()
        if req.delivery is not None:
            existing.delivery = dict(req.delivery)
        if req.digest is not None:
            existing.digest = dict(req.digest)

        existing.updated_at = _utc_now_iso()
        self.save_automation(existing)
        return existing

    def pause_automation(self, automation_id: str) -> AutomationRecord:
        return self.update_automation(
            automation_id, UpdateAutomationRequest(status=AutomationStatus.PAUSED)
        )

    def resume_automation(self, automation_id: str) -> AutomationRecord:
        return self.update_automation(
            automation_id, UpdateAutomationRequest(status=AutomationStatus.ACTIVE)
        )

    def delete_automation(self, automation_id: str) -> AutomationRecord:
        existing = self.get_automation(automation_id)
        path = self._automation_path(automation_id)
        path.unlink()
        runs_dir = self._runs_dir_for(automation_id)
        if runs_dir.exists():
            shutil.rmtree(runs_dir)
        return existing

    # ── runs ──

    def list_runs(
        self, automation_id: str, limit: int | None = None
    ) -> list[AutomationRunRecord]:
        dir_path = self._runs_dir_for(automation_id)
        if not dir_path.exists():
            return []
        out: list[AutomationRunRecord] = []
        for entry in dir_path.iterdir():
            if entry.suffix != ".json":
                continue
            try:
                raw = entry.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            out.append(AutomationRunRecord.from_dict(json.loads(raw)))
        out.sort(key=lambda r: r.created_at, reverse=True)
        if limit is not None:
            out = out[:limit]
        return out

    def save_run(self, run: AutomationRunRecord) -> None:
        self._runs_dir_for(run.automation_id).mkdir(parents=True, exist_ok=True)
        write_json_atomic(self._run_path(run.automation_id, run.id), run.to_dict())

    async def _enqueue_run_task(
        self,
        automation: AutomationRecord,
        run: AutomationRunRecord,
        task_manager: TaskManager,
    ) -> None:
        """Mirrors Rust ``enqueue_run_task`` (539-574) via ``automation.pipeline``."""
        from deepseek_tui.automation.pipeline import enqueue_automation_task

        await enqueue_automation_task(automation, run, task_manager)

    async def run_now(
        self, automation_id: str, task_manager: TaskManager
    ) -> AutomationRunRecord:
        """Mirrors Rust ``run_now`` (576-614)."""
        automation = self.get_automation(automation_id)
        now = _utc_now_iso()
        run = AutomationRunRecord(
            id=uuid.uuid4().hex,
            automation_id=automation.id,
            scheduled_for=now,
            status=AutomationRunStatus.QUEUED,
            created_at=now,
        )
        await self._enqueue_run_task(automation, run, task_manager)
        self.save_run(run)
        if run.status is AutomationRunStatus.FAILED:
            from deepseek_tui.automation.pipeline import try_deliver_completed_run

            if await try_deliver_completed_run(automation, run, task_manager):
                self.save_run(run)

        automation.updated_at = _utc_now_iso()
        if run.status in (
            AutomationRunStatus.COMPLETED,
            AutomationRunStatus.FAILED,
            AutomationRunStatus.CANCELED,
        ):
            automation.last_run_at = run.ended_at or _utc_now_iso()
        self.save_automation(automation)
        return run

    # ── scheduler ──

    async def scheduler_tick(self, task_manager: TaskManager) -> None:
        """Mirrors Rust ``scheduler_tick`` (616-677).

        Iterates all active automations, fires due ones (idempotent on
        ``scheduled_for == due_at``), and advances ``next_run_at`` for
        each.
        """
        now = _utc_now()
        automations = self.list_automations()

        for automation in automations:
            if automation.status is not AutomationStatus.ACTIVE:
                continue

            schedule = AutomationSchedule.parse_rrule(automation.rrule)

            if automation.next_run_at is None:
                automation.next_run_at = schedule.next_after(now).isoformat()
                automation.updated_at = now.isoformat()
                self.save_automation(automation)
                continue

            due_at = _parse_iso(automation.next_run_at)
            if due_at > now:
                continue

            # Idempotency guard: don't re-fire the same scheduled slot if
            # we already wrote a run for it. Mirrors Rust 640-650.
            existing_for_slot = any(
                run.scheduled_for == automation.next_run_at
                for run in self.list_runs(automation.id, limit=25)
            )
            if existing_for_slot:
                automation.next_run_at = schedule.next_after(due_at).isoformat()
                automation.updated_at = now.isoformat()
                self.save_automation(automation)
                continue

            run = AutomationRunRecord(
                id=uuid.uuid4().hex,
                automation_id=automation.id,
                scheduled_for=automation.next_run_at,
                status=AutomationRunStatus.QUEUED,
                created_at=now.isoformat(),
            )
            await self._enqueue_run_task(automation, run, task_manager)
            self.save_run(run)
            if run.status is AutomationRunStatus.FAILED:
                from deepseek_tui.automation.pipeline import try_deliver_completed_run

                if await try_deliver_completed_run(automation, run, task_manager):
                    self.save_run(run)

            automation.updated_at = now.isoformat()
            automation.next_run_at = schedule.next_after(due_at).isoformat()
            self.save_automation(automation)

    async def reconcile_run_statuses(self, task_manager: TaskManager) -> None:
        """Mirrors Rust ``reconcile_run_statuses`` (679-759).

        Walks every Queued/Running run, looks up its linked Task, and
        propagates the Task status back into the Run.
        """
        from deepseek_tui.tools.task import TaskStatus

        for automation in self.list_automations():
            for run in self.list_runs(automation.id, limit=100):
                if run.status not in (
                    AutomationRunStatus.QUEUED,
                    AutomationRunStatus.RUNNING,
                ):
                    continue
                if run.task_id is None:
                    continue
                try:
                    task = await task_manager.get_task(run.task_id)
                except Exception:  # noqa: BLE001
                    continue

                run.thread_id = getattr(task, "thread_id", None)
                run.turn_id = getattr(task, "turn_id", None)
                changed = False

                if task.status is TaskStatus.QUEUED:
                    if run.status is not AutomationRunStatus.QUEUED:
                        run.status = AutomationRunStatus.QUEUED
                        changed = True
                elif task.status is TaskStatus.RUNNING:
                    if run.status is not AutomationRunStatus.RUNNING:
                        run.status = AutomationRunStatus.RUNNING
                        changed = True
                    if run.started_at is None:
                        run.started_at = (
                            getattr(task, "started_at", None) or _utc_now_iso()
                        )
                        changed = True
                elif task.status is TaskStatus.COMPLETED:
                    run.status = AutomationRunStatus.COMPLETED
                    run.started_at = run.started_at or getattr(task, "started_at", None)
                    run.ended_at = (
                        getattr(task, "ended_at", None) or _utc_now_iso()
                    )
                    run.error = None
                    changed = True
                elif task.status is TaskStatus.FAILED:
                    run.status = AutomationRunStatus.FAILED
                    run.started_at = run.started_at or getattr(task, "started_at", None)
                    run.ended_at = (
                        getattr(task, "ended_at", None) or _utc_now_iso()
                    )
                    run.error = getattr(task, "error", None)
                    changed = True
                elif task.status is TaskStatus.CANCELED:
                    run.status = AutomationRunStatus.CANCELED
                    run.started_at = run.started_at or getattr(task, "started_at", None)
                    run.ended_at = (
                        getattr(task, "ended_at", None) or _utc_now_iso()
                    )
                    changed = True

                if changed:
                    self.save_run(run)
                    if run.status in (
                        AutomationRunStatus.COMPLETED,
                        AutomationRunStatus.FAILED,
                        AutomationRunStatus.CANCELED,
                    ):
                        latest = self.get_automation(automation.id)
                        latest.last_run_at = run.ended_at or _utc_now_iso()
                        latest.updated_at = _utc_now_iso()
                        self.save_automation(latest)
                    if run.status in (
                        AutomationRunStatus.COMPLETED,
                        AutomationRunStatus.FAILED,
                    ):
                        from deepseek_tui.automation.pipeline import (
                            try_deliver_completed_run,
                        )

                        if await try_deliver_completed_run(
                            automation, run, task_manager
                        ):
                            self.save_run(run)


# Background scheduler for :class:`AutomationManager`.
#
# Mirrors Rust ``automation_manager.rs::spawn_scheduler`` (817-850).
#
# The loop ticks the manager + reconciles run statuses on a fixed
# cadence. Failures inside a single tick are logged and swallowed so a
# transient error never kills the scheduler — the next tick gets a fresh
# chance.
#
# Q1 decision (Engine-level): one scheduler task per ``Engine`` instance,
# started in ``Engine.create`` and cancelled in ``Engine.shutdown``.
#
# Q2 decision: tick interval defaults to 15 s (matches Rust
# ``AutomationSchedulerConfig::default``), with a 5-second floor for
# sanity. Tests can pass ``tick_interval_secs=1`` for fast iteration.
#
import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.tools.task import TaskManager

__all__ = [
    "AutomationSchedulerConfig",
    "run_scheduler_loop",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AutomationSchedulerConfig:
    """Mirrors Rust ``AutomationSchedulerConfig`` (805-815).

    The ``tick_interval_secs`` floor of 5 matches the Rust ``.max(5)``
    clamp at line 827.
    """

    tick_interval_secs: float = 15.0


async def run_scheduler_loop(
    manager: AutomationManager,
    task_manager: TaskManager,
    cancel: asyncio.Event,
    config: AutomationSchedulerConfig | None = None,
) -> None:
    """Run the automation scheduler until ``cancel`` is set.

    Each iteration:

    1. ``manager.scheduler_tick(task_manager)`` — fire any due automations.
    2. ``manager.reconcile_run_statuses(task_manager)`` — copy task
       statuses back into runs.
    3. Sleep up to ``tick_interval_secs`` or wake early on cancel.

    Exceptions in tick/reconcile are logged at warning level and
    swallowed (Rust does the same with ``tracing::warn!`` — see
    automation_manager.rs:836, 839).
    """
    cfg = config or AutomationSchedulerConfig()
    interval = max(5.0, float(cfg.tick_interval_secs))

    logger.info(
        "automation_scheduler_start interval_secs=%.1f", interval
    )

    while not cancel.is_set():
        try:
            await manager.scheduler_tick(task_manager)
        except Exception as exc:  # noqa: BLE001 — never kill the loop
            logger.warning("automation_scheduler_tick_failed: %s", exc)

        try:
            await manager.reconcile_run_statuses(task_manager)
        except Exception as exc:  # noqa: BLE001
            logger.warning("automation_scheduler_reconcile_failed: %s", exc)

        # Sleep until the next tick OR until cancel fires, whichever is
        # first. ``asyncio.wait`` here mirrors Rust ``tokio::select!``
        # at line 843.
        try:
            await asyncio.wait_for(cancel.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    logger.info("automation_scheduler_stop")
