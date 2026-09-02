"""Automation — tools, manager, and scheduler.

Consolidates automation_tools.py, automation_manager.py, automation_scheduler.py.
"""

from __future__ import annotations



# Model-visible cron tools backed by :class:`AutomationManager`.
#
# Three tools (Claude Code CronCreate / CronList / CronDelete shape):
#
# ================ ==================================================
# ``cron_create``  create a durable scheduled job (REQUIRES_APPROVAL);
#                  ``run_now=true`` also fires it immediately
# ``cron_list``    list jobs; with ``automation_id`` shows one job's
#                  details + recent run history
# ``cron_delete``  delete (also wipes the job's run history)
# ================ ==================================================
#
# There is deliberately no update/pause/resume/run tool: editing means
# delete + recreate, and manual runs fold into ``cron_create(run_now)``.
# The old ``automation_*`` names are retired from the schema; create /
# list / read / delete keep working at the execution layer via
# ``engine.dispatch.normalize_legacy_tool_call``.
#
# The ``AutomationManager`` lives on ``ToolContext.metadata`` under the
# key :data:`AUTOMATION_MANAGER_KEY`, set by ``Engine.create`` when the
# feature flag is enabled. If no manager is attached (feature flag off),
# each tool returns a clean error so the LLM can fall back gracefully.
#
from typing import Any, cast

from deepseek_tui.utils import optional_text as _opt_str_value
from deepseek_tui.utils import utc_now_iso as _utc_now_iso
from deepseek_tui.utils import write_json_atomic
from deepseek_tui.tools.utils.validation import optional_string as _optional_string
from deepseek_tui.tools.utils.validation import require_string as _require_string
from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo
import asyncio

__all__ = [
    "AUTOMATION_MANAGER_KEY",
    "CronCreateTool",
    "CronDeleteTool",
    "CronListTool",
]


AUTOMATION_MANAGER_KEY = "automation_manager"


# ── helpers ─────────────────────────────────────────────────────────


def _get_manager(context: ToolContext) -> AutomationManager:
    """Pull the ``AutomationManager`` off the context, or raise."""
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
        f"{record.id[:8]} | {record.status.value:<9} | "
        f"next={next_run} | last={last_run} | {record.name}"
    )


# ── tool implementations ────────────────────────────────────────────


def _allowed_delivery_targets(mode: str) -> list[str]:
    """Configured recipients the model is allowed to deliver to."""
    if mode == "feishu":
        from deepseek_tui.automation.inbox import default_feishu_chat_id_from_config

        value = default_feishu_chat_id_from_config()
        return [value] if value else []
    if mode == "email":
        from deepseek_tui.automation.inbox import default_mail_to_from_config

        value = default_mail_to_from_config()
        return [value] if value else []
    if mode == "wecom":
        from deepseek_tui.automation.inbox import default_wecom_webhook_key_from_config

        value = default_wecom_webhook_key_from_config()
        return [value] if value else []
    return []


def _delivery_target_allowed(mode: str, target: str, allowed: list[str]) -> bool:
    if mode == "email":
        return any(target.lower() == item.lower() for item in allowed)
    if mode == "wecom":
        from deepseek_tui.automation.inbox import _parse_wecom_webhook_key

        parsed = _parse_wecom_webhook_key(target) or target
        return any(
            parsed == (_parse_wecom_webhook_key(item) or item) for item in allowed
        )
    return target in allowed


def _resolve_delivery(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fill default ``to`` from config; reject model-chosen strangers."""
    if raw is None:
        return None
    delivery = dict(raw)
    mode = str(delivery.get("mode", "silent")).strip().lower()
    if mode in ("silent", "notify", ""):
        return delivery
    to_val = delivery.get("to") or delivery.get("chat_id")
    allowed = _allowed_delivery_targets(mode)
    if isinstance(to_val, str) and to_val.strip():
        target = to_val.strip()
        if not allowed or not _delivery_target_allowed(mode, target, allowed):
            raise ToolError(
                f"delivery.to must be a configured {mode} recipient; "
                "unknown targets are not allowed"
            )
        delivery["to"] = target
        return delivery
    if allowed:
        delivery["to"] = allowed[0]
    return delivery


class CronCreateTool(ToolSpec):
    """Create a durable scheduled job (requires approval)."""

    def name(self) -> str:
        return "cron_create"

    def description(self) -> str:
        return (
            "Create a durable scheduled job (cron) that enqueues an agent "
            "task on a schedule. Relative times ('in 10 minutes', 'tomorrow "
            "morning') resolve against the `today: YYYY-MM-DD` date and "
            "user timezone in the system prompt (prefer that over shell date). "
            "Recurring jobs set schedule to a standard 5-field cron "
            "expression ('0 9 * * *' = every day 09:00, '30 8 * * MON,FRI', "
            "'0 */2 * * *' = every 2 hours on the hour). One-shot jobs set "
            "run_at (ISO8601) and omit schedule — they fire once and are "
            "then marked completed. Optional "
            "delivery sends the task summary to feishu, email, or wecom after "
            "completion. For feishu include delivery.mode=feishu and "
            "delivery.to (open_chat_id); for wecom use delivery.mode=wecom "
            "(webhook key comes from config when to is omitted). Set "
            "run_now=true to also trigger the job immediately after creation "
            "— this only applies at create time and cannot fire an "
            "already-existing job (use the Workbench Automations UI to run "
            "an existing job once). "
            "When the job fires it may use: web_search, fetch_url, read_file, "
            "grep_files, file_search, exec_shell, load_skill, and installed "
            "MCP tools; delivery is handled by the system (do not ask the job "
            "prompt to send Feishu/email itself). "
            "After creating, tell the user they can view, pause, or delete "
            "the job in the Workbench sidebar Automations page. "
            "To change an existing job, delete it with cron_delete and "
            "recreate it (deleting wipes the job's run history). "
            "Creation requires approval."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Short human-readable job name shown in the "
                        "Automations UI, in the user's language."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "The task the job runs on each fire, written as a "
                        "self-contained instruction (the job has no "
                        "conversation context). Do not include delivery "
                        "instructions — delivery is configured separately."
                    ),
                },
                "schedule": {
                    "type": "string",
                    "description": (
                        "5-field cron expression: minute hour day-of-month "
                        "month day-of-week. Examples: '0 9 * * *' (daily "
                        "09:00), '30 8 * * MON,FRI', '0 */2 * * *' (every "
                        "2 hours). Omit for a one-shot job."
                    ),
                },
                "run_at": {
                    "type": "string",
                    "description": (
                        "ISO8601 timestamp. Alone it makes a one-shot job; "
                        "combined with schedule it pins the first run "
                        "(delayed start). A timestamp without an offset is "
                        "read in the job's timezone."
                    ),
                },
                "timezone": {
                    "type": "string",
                    "description": (
                        "IANA timezone the schedule is evaluated in, e.g. "
                        "'Asia/Shanghai'. Defaults to the host timezone."
                    ),
                },
                "cwds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Working directories the job runs in (absolute "
                        "paths). Defaults to the current workspace."
                    ),
                },
                "delivery": {
                    "type": "object",
                    "description": (
                        "Optional post-run delivery (feishu, email, or wecom)."
                    ),
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": [
                                "feishu",
                                "email",
                                "wecom",
                                "silent",
                                "notify",
                            ],
                        },
                        "to": {
                            "type": "string",
                            "description": (
                                "Recipient: must match the configured default "
                                "(automation.feishu_chat_id / mail_to / "
                                "wecom.webhook_key). Omit to use that default."
                            ),
                        },
                        "best_effort": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "paused": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Create the job in a paused state (it will not "
                        "fire until resumed in the Automations UI)."
                    ),
                },
                "run_now": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Also trigger the job immediately after creation."
                    ),
                },
            },
            "required": ["name", "prompt"],
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
        schedule = _optional_string(input_data, "schedule")
        run_at = _optional_string(input_data, "run_at")
        tz_name = _optional_string(input_data, "timezone")
        cwds = _optional_string_list(input_data, "cwds") or []
        delivery = _resolve_delivery(_optional_object(input_data, "delivery"))
        paused = bool(input_data.get("paused", False))
        run_now = bool(input_data.get("run_now", False))
        status = AutomationStatus.PAUSED if paused else AutomationStatus.ACTIVE
        try:
            record = manager.create_automation(
                CreateAutomationRequest(
                    name=name,
                    prompt=prompt,
                    schedule=schedule,
                    timezone=tz_name,
                    run_at=run_at,
                    cwds=cwds,
                    status=status,
                    delivery=delivery,
                )
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        metadata: dict[str, Any] = {"automation": _automation_to_payload(record)}
        content = record.id
        if run_now:
            run = await _run_now(manager, record.id, context)
            content = f"{content}\nqueued run {run.id[:8]} (task_id={run.task_id or '—'})"
            metadata["run"] = run.to_dict()
        return ToolResult(success=True, content=content, metadata=metadata)


async def _run_now(
    manager: AutomationManager, automation_id: str, context: ToolContext
) -> AutomationRunRecord:
    """Fire one run right now — shared by ``cron_create(run_now=true)``."""
    # The run_now path requires a TaskManager — pick it up off the
    # context (``runtime.task_manager``).
    from deepseek_tui.tools.task import TaskManager

    task_manager_raw = context.metadata.get("task_manager")
    if not isinstance(task_manager_raw, TaskManager):
        raise ToolError(
            "TaskManager is not attached "
            "(set features.tasks=true to enable run_now)"
        )

    try:
        return await manager.run_now(automation_id, task_manager_raw)
    except KeyError as exc:
        raise ToolError(str(exc)) from exc


class CronListTool(ToolSpec):
    def name(self) -> str:
        return "cron_list"

    def description(self) -> str:
        return (
            "List durable scheduled jobs (cron) with status, next run, and "
            "last run timestamps. Pass automation_id to read one job's "
            "details and recent run history. For full management (pause, "
            "run history UI), point the user to the Workbench sidebar "
            "Automations page."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "automation_id": {
                    "type": "string",
                    "description": (
                        "When set, return this job's details and recent "
                        "runs instead of the full list."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50,
                    "description": "Maximum jobs to list.",
                },
                "runs_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": (
                        "Recent runs to include when automation_id is set "
                        "(default 10)."
                    ),
                },
            },
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        manager = _get_manager(context)
        automation_id = _optional_string(input_data, "automation_id")
        if automation_id is not None:
            runs_limit = _optional_int(input_data, "runs_limit") or 10
            try:
                record = manager.get_automation(automation_id)
            except KeyError as exc:
                raise ToolError(str(exc)) from exc
            runs = manager.list_runs(automation_id, limit=runs_limit)
            lines = [
                _format_summary_line(record),
                f"prompt:   {record.prompt}",
                f"schedule: {record.schedule or 'one-shot'} ({record.timezone})",
                f"cwds:     {record.cwds}",
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


class CronDeleteTool(ToolSpec):
    def name(self) -> str:
        return "cron_delete"

    def description(self) -> str:
        return (
            "Delete a scheduled job (cron) and wipe its run history. "
            "Requires approval. After deleting, tell the user the job is "
            "gone; remaining jobs are in the Workbench sidebar Automations "
            "page."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "automation_id": {
                    "type": "string",
                    "description": (
                        "Id of the job to delete (from cron_list). "
                        "Deletion also wipes the job's run history."
                    ),
                },
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
        try:
            record = manager.delete_automation(automation_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content="deleted",
            metadata={"automation_id": record.id},
        )


# Durable automation records and scheduler-supporting manager.
#
# Automations are local-first recurring jobs that **enqueue standard
# durable tasks**. This module stores automation definitions and run
# history under ``~/.deepseek/automations/`` (or
# ``DEEPSEEK_AUTOMATIONS_DIR`` override).
#
# Layout::
#
#     <root>/   (= ``~/.deepseek/automations``)
#       <id>.json                              ← one AutomationRecord
#       runs/<automation_id>/<run_id>.json     ← one AutomationRunRecord per fire
#
# The scheduler tick (see ``automation_scheduler.run_scheduler_loop``)
# calls :meth:`AutomationManager.scheduler_tick` and
# :meth:`AutomationManager.reconcile_run_statuses` on a fixed cadence.
#
# Every disk write goes through ``write_json_atomic`` (tmp file + rename)
# so partially-written records cannot survive a crash.
#
# Schedules are standard 5-field cron expressions evaluated in the
# record's IANA timezone (``0 9 * * *`` fires at the user's 09:00, not
# UTC). A record with ``schedule=None`` is a one-shot: it fires once at
# ``next_run_at`` and then moves to ``AutomationStatus.COMPLETED``.
#

if TYPE_CHECKING:
    from deepseek_tui.tools.task import TaskManager

__all__ = [
    "CURRENT_AUTOMATION_SCHEMA_VERSION",
    "CURRENT_RUN_SCHEMA_VERSION",
    "MISFIRE_GRACE_SECS",
    "default_timezone",
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

CURRENT_AUTOMATION_SCHEMA_VERSION = 2
CURRENT_RUN_SCHEMA_VERSION = 1

# How stale a due slot may be and still fire. Slots missed while the app
# was closed (weekend downtime, laptop asleep) are dropped rather than
# replayed one-per-tick.
MISFIRE_GRACE_SECS = 30 * 60

class AutomationStatus(str, Enum):
    """Automation status (snake_case on the wire)."""

    ACTIVE = "active"
    PAUSED = "paused"
    # One-shot jobs land here once their single run has been enqueued.
    COMPLETED = "completed"


class AutomationRunStatus(str, Enum):
    """Automation run status."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


# ─────────────────────────────────────────────────────────────────────
# Cron schedules
# ─────────────────────────────────────────────────────────────────────


def default_timezone() -> str:
    """The host's IANA timezone name (``Asia/Shanghai``), or ``UTC``.

    There is no stdlib API for this, so probe ``$TZ`` then the
    ``/etc/localtime`` symlink. Windows has neither and falls back to
    UTC — set the timezone explicitly there.
    """
    env = os.environ.get("TZ", "").strip()
    if env:
        try:
            ZoneInfo(env)
            return env
        except Exception:  # noqa: BLE001 — bad $TZ, keep probing
            pass
    try:
        parts = Path("/etc/localtime").resolve().parts
        if "zoneinfo" in parts:
            name = "/".join(parts[parts.index("zoneinfo") + 1 :])
            ZoneInfo(name)
            return name
    except Exception:  # noqa: BLE001
        pass
    return "UTC"


class AutomationSchedule:
    """A 5-field cron expression evaluated in a fixed IANA timezone.

    Date arithmetic is delegated to ``croniter`` so that DST transitions,
    month lengths, and wall-clock anchoring behave like every other cron
    implementation. ``next_after`` takes and returns aware UTC datetimes.
    """

    __slots__ = ("_expr", "_tz", "_tz_name")

    def __init__(self, expr: str, tz_name: str) -> None:
        self._expr = expr
        self._tz_name = tz_name
        self._tz = ZoneInfo(tz_name)

    @property
    def expr(self) -> str:
        return self._expr

    @property
    def timezone_name(self) -> str:
        return self._tz_name

    @classmethod
    def parse(cls, expr: str, tz_name: str) -> AutomationSchedule:
        """Validate a cron expression + timezone. Raises :class:`ValueError`."""
        from croniter import croniter

        cleaned = " ".join(expr.strip().split())
        if not cleaned:
            raise ValueError("cron expression is required")
        if not croniter.is_valid(cleaned):
            raise ValueError(
                f"Invalid cron expression '{expr}'. Expected 5 fields: "
                "minute hour day-of-month month day-of-week (e.g. '0 9 * * *')"
            )
        try:
            ZoneInfo(tz_name)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"Unknown timezone '{tz_name}'. Use an IANA name such as "
                "'Asia/Shanghai'."
            ) from exc
        return cls(cleaned, tz_name)

    def next_after(self, after: datetime) -> datetime:
        """The next fire time strictly after ``after`` (aware UTC in and out).

        Note: on the autumn DST fallback the local wall clock repeats an
        hour, so a schedule inside that hour legitimately yields two
        instants. Zones without DST (e.g. Asia/Shanghai) never see this.
        """
        from croniter import croniter

        if after.tzinfo is None:
            raise ValueError("after must be timezone-aware")
        local_after = after.astimezone(self._tz)
        nxt: datetime = croniter(self._expr, local_after).get_next(datetime)
        return nxt.astimezone(timezone.utc)


# ─────────────────────────────────────────────────────────────────────
# Records
# ─────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class AutomationRecord:
    """A scheduled job.

    ``schedule`` is a 5-field cron expression interpreted in
    ``timezone``; ``schedule=None`` marks a one-shot job that fires once
    at ``next_run_at`` and then goes to
    :attr:`AutomationStatus.COMPLETED`. ``cwds`` is a list of strings
    (Path-like) so it round-trips through JSON without a custom encoder.
    """

    id: str
    name: str
    prompt: str
    schedule: str | None
    timezone: str
    status: AutomationStatus
    created_at: str  # ISO 8601 UTC string
    updated_at: str
    cwds: list[str] = field(default_factory=list)
    next_run_at: str | None = None
    last_run_at: str | None = None
    delivery: dict[str, Any] | None = None
    digest: dict[str, Any] | None = None
    schema_version: int = CURRENT_AUTOMATION_SCHEMA_VERSION

    @property
    def is_one_shot(self) -> bool:
        return self.schedule is None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "schedule": self.schedule,
            "timezone": self.timezone,
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
            schema_version=CURRENT_AUTOMATION_SCHEMA_VERSION,
            id=str(raw["id"]),
            name=str(raw["name"]),
            prompt=str(raw["prompt"]),
            schedule=_opt_str_value(raw.get("schedule")),
            timezone=_opt_str_value(raw.get("timezone")) or default_timezone(),
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
    """A single automation run record."""

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
    delivery_attempts: int = 0
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
            "delivery_attempts": self.delivery_attempts,
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
            delivery_attempts=int(raw.get("delivery_attempts", 0)),
        )


@dataclass(slots=True)
class CreateAutomationRequest:
    """``schedule`` (cron) or ``run_at`` (one-shot) — at least one required.

    Passing both makes a recurring job whose first fire is pinned to
    ``run_at`` (a delayed start).
    """

    name: str
    prompt: str
    schedule: str | None = None
    timezone: str | None = None
    run_at: str | None = None
    cwds: list[str] = field(default_factory=list)
    status: AutomationStatus | None = None
    delivery: dict[str, Any] | None = None
    digest: dict[str, Any] | None = None


@dataclass(slots=True)
class UpdateAutomationRequest:
    name: str | None = None
    prompt: str | None = None
    schedule: str | None = None
    timezone: str | None = None
    cwds: list[str] | None = None
    status: AutomationStatus | None = None
    delivery: dict[str, Any] | None = None
    digest: dict[str, Any] | None = None


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string back into an aware ``datetime``."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_run_at(value: str, tz_name: str) -> str:
    """Normalize a caller-supplied timestamp to an aware UTC ISO string.

    A naive timestamp is read in the automation's own timezone — that is
    what a user writing "2026-08-05T09:00" means.
    """
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid ISO 8601 timestamp '{value}'") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(timezone.utc).isoformat()


def _next_run_after_now(record: AutomationRecord) -> str | None:
    """The next fire time for ``record``, or ``None`` when nothing is left.

    A one-shot keeps its pinned target: there is no "next" to compute, and
    recomputing would silently move the time the user asked for.
    """
    if record.schedule is None:
        return record.next_run_at
    schedule = AutomationSchedule.parse(record.schedule, record.timezone)
    return schedule.next_after(_utc_now()).isoformat()


def validate_name_and_prompt(name: str, prompt: str) -> None:
    if not name.strip():
        raise ValueError("Automation name is required")
    if not prompt.strip():
        raise ValueError("Automation prompt is required")


def default_automations_dir() -> Path:
    """``$DEEPSEEK_AUTOMATIONS_DIR`` or ``~/.deepseek/automations``."""
    override = os.environ.get("DEEPSEEK_AUTOMATIONS_DIR", "").strip()
    if override:
        return Path(override)
    from deepseek_tui.config.paths import user_automations_dir

    return user_automations_dir()


# ─────────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────────


class AutomationManager:
    """In-process automation registry.

    All disk IO is
    synchronous (the records are tiny JSON files); the ``async`` methods
    only exist where they need to ``await`` ``TaskManager`` calls.

    By design (Q6=B), this manager is **not** internally locked. The
    scheduler loop runs on the same asyncio event loop as the tool
    dispatcher, and every disk write goes through ``write_json_atomic``,
    so concurrent state corruption is impossible without preemption.
    """

    def __init__(self, root: Path) -> None:
        # Defs live as ``root/*.json``; run history under ``root/runs/``.
        # Legacy nested ``root/automations/*.json`` is flattened on open.
        self._root = root
        self._automations_dir = root
        self._runs_dir = root / "runs"
        self._automations_dir.mkdir(parents=True, exist_ok=True)
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._flatten_legacy_defs()
        # Optional RuntimeThreadManager, injected by the server layer after
        # construction so ``delivery.mode=notify`` can append a thread notice.
        # Kept as an opaque ``Any`` so the tools layer never imports server
        # types. ``None`` on the scheduler path means notify falls back to a
        # log line only (which is the pre-fix behaviour).
        self.thread_manager: Any = None

    @classmethod
    def open(cls, root: Path) -> AutomationManager:
        return cls(root)

    @classmethod
    def default_location(cls) -> AutomationManager:
        return cls.open(default_automations_dir())

    def _flatten_legacy_defs(self) -> None:
        nested = self._root / "automations"
        if not nested.is_dir():
            return
        for entry in list(nested.iterdir()):
            if entry.suffix != ".json" or not entry.is_file():
                continue
            dest = self._root / entry.name
            if not dest.exists():
                entry.replace(dest)
            else:
                entry.unlink(missing_ok=True)
        try:
            if nested.is_dir() and not any(nested.iterdir()):
                nested.rmdir()
        except OSError:
            pass

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
        validate_name_and_prompt(req.name, req.prompt)
        tz_name = _opt_str_value(req.timezone) or default_timezone()
        cron_expr = _opt_str_value(req.schedule)
        run_at = _opt_str_value(req.run_at)
        if cron_expr is None and run_at is None:
            raise ValueError(
                "Provide schedule (cron expression) for a recurring job, "
                "or run_at (ISO 8601) for a one-shot job"
            )

        now = _utc_now()
        status = req.status or AutomationStatus.ACTIVE
        if cron_expr is None:
            schedule = None
            ZoneInfo(tz_name)  # validate even without a cron expression
        else:
            schedule = AutomationSchedule.parse(cron_expr, tz_name)
            cron_expr = schedule.expr

        if run_at is not None:
            next_run_at = _normalize_run_at(run_at, tz_name)
        elif schedule is not None and status is AutomationStatus.ACTIVE:
            next_run_at = schedule.next_after(now).isoformat()
        else:
            next_run_at = None

        record = AutomationRecord(
            id=uuid.uuid4().hex,
            name=req.name.strip(),
            prompt=req.prompt.strip(),
            schedule=cron_expr,
            timezone=tz_name,
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
            if not entry.is_file() or entry.suffix != ".json":
                continue
            try:
                raw = entry.read_text(encoding="utf-8")
                out.append(AutomationRecord.from_dict(json.loads(raw)))
            except FileNotFoundError:
                continue
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                # One corrupt/half-written file must not stall the whole
                # tick — drop it and keep every other job scheduling.
                logger.warning(
                    "automation_record_skipped path=%s err=%s", entry, exc
                )
                continue
        out.sort(key=lambda r: r.updated_at, reverse=True)
        return out

    def update_automation(
        self, automation_id: str, req: UpdateAutomationRequest
    ) -> AutomationRecord:
        existing = self.get_automation(automation_id)

        if req.name is not None:
            if not req.name.strip():
                raise ValueError("Automation name cannot be empty")
            existing.name = req.name.strip()
        if req.prompt is not None:
            if not req.prompt.strip():
                raise ValueError("Automation prompt cannot be empty")
            existing.prompt = req.prompt.strip()
        if req.timezone is not None:
            existing.timezone = _opt_str_value(req.timezone) or default_timezone()
        if req.schedule is not None:
            schedule = AutomationSchedule.parse(req.schedule, existing.timezone)
            existing.schedule = schedule.expr
        if req.cwds is not None:
            existing.cwds = list(req.cwds)
        if req.status is not None:
            if req.status is AutomationStatus.ACTIVE:
                # Guard against resurrecting an exhausted one-shot into a
                # zombie ACTIVE that can never fire. Judge by "one-shot with
                # no future slot" rather than "status == COMPLETED": pause
                # overwrites COMPLETED with PAUSED, so status alone is not a
                # reliable signal of whether the job already ran. This runs
                # AFTER req.schedule is applied above, so resuming while
                # switching to a cron schedule is still allowed.
                if existing.schedule is None and not existing.next_run_at:
                    raise ValueError(
                        "This one-shot job already ran. Create a new job "
                        "instead of resuming it."
                    )
            existing.status = req.status

        # Re-arm whenever the timing changed or the job was resumed. Pausing
        # deliberately keeps next_run_at so the UI can still show it and a
        # one-shot does not lose its target time.
        if (
            req.schedule is not None or req.timezone is not None or req.status is not None
        ) and existing.status is AutomationStatus.ACTIVE:
            existing.next_run_at = _next_run_after_now(existing)
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
                out.append(AutomationRunRecord.from_dict(json.loads(raw)))
            except FileNotFoundError:
                continue
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                logger.warning(
                    "automation_run_skipped path=%s err=%s", entry, exc
                )
                continue
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
        from deepseek_tui.automation.pipeline import enqueue_automation_task

        await enqueue_automation_task(automation, run, task_manager)

    async def run_now(
        self, automation_id: str, task_manager: TaskManager
    ) -> AutomationRunRecord:
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

            if await try_deliver_completed_run(
                automation, run, task_manager,
                thread_manager=self.thread_manager,
            ):
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
        """Iterate all active automations.

        Fires due ones (idempotent on ``scheduled_for == due_at``) and
        re-arms ``next_run_at``.

        Misfire policy differs by job kind, and follows from the model
        rather than from a tunable: a recurring slot missed by more than
        :data:`MISFIRE_GRACE_SECS` is dropped, because the next occurrence
        supersedes it and replaying a backlog would spam the user. A
        one-shot always catches up however late, because nothing else will
        ever deliver it.
        """
        now = _utc_now()

        for automation in self.list_automations():
            if automation.status is not AutomationStatus.ACTIVE:
                continue

            if automation.next_run_at is None:
                if automation.schedule is None:
                    continue  # one-shot with nothing left to do
                automation.next_run_at = _next_run_after_now(automation)
                automation.updated_at = now.isoformat()
                self.save_automation(automation)
                continue

            due_at = _parse_iso(automation.next_run_at)
            if due_at > now:
                continue

            # Re-arm from *now*, never from the missed slot — otherwise a
            # backlog fires one slot per tick. One-shots have no next slot.
            upcoming = (
                None
                if automation.schedule is None
                else AutomationSchedule.parse(
                    automation.schedule, automation.timezone
                )
                .next_after(now)
                .isoformat()
            )

            if (
                automation.schedule is not None
                and (now - due_at).total_seconds() > MISFIRE_GRACE_SECS
            ):
                logger.info(
                    "automation_misfire_skipped id=%s due_at=%s next_run_at=%s",
                    automation.id,
                    automation.next_run_at,
                    upcoming,
                )
                automation.next_run_at = upcoming
                automation.updated_at = now.isoformat()
                self.save_automation(automation)
                continue

            # Idempotency guard: don't re-fire the same scheduled slot if
            # we already wrote a run for it.
            already_fired = any(
                run.scheduled_for == automation.next_run_at
                for run in self.list_runs(automation.id, limit=25)
            )
            if not already_fired:
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
                    from deepseek_tui.automation.pipeline import (
                        try_deliver_completed_run,
                    )

                    if await try_deliver_completed_run(
                        automation, run, task_manager,
                        thread_manager=self.thread_manager,
                    ):
                        self.save_run(run)

            automation.updated_at = now.isoformat()
            automation.next_run_at = upcoming
            if automation.schedule is None:
                automation.status = AutomationStatus.COMPLETED
            self.save_automation(automation)

    async def reconcile_run_statuses(self, task_manager: TaskManager) -> None:
        """Walk every Queued/Running run, looks up its linked Task, and
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
                elif task.status is TaskStatus.TIMED_OUT:
                    run.status = AutomationRunStatus.FAILED
                    run.started_at = run.started_at or getattr(task, "started_at", None)
                    run.ended_at = (
                        getattr(task, "ended_at", None) or _utc_now_iso()
                    )
                    run.error = getattr(task, "error", None) or "Task timed out"
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
                            automation, run, task_manager,
                            thread_manager=self.thread_manager,
                        ):
                            self.save_run(run)


# Background scheduler for :class:`AutomationManager`.
#
# The loop ticks the manager + reconciles run statuses on a fixed
# cadence. Failures inside a single tick are logged and swallowed so a
# transient error never kills the scheduler — the next tick gets a fresh
# chance.
#
# Q1 decision (Engine-level): one scheduler task per ``Engine`` instance,
# started in ``Engine.create`` and cancelled in ``Engine.shutdown``.
#
# Q2 decision: tick interval defaults to 15 s, with a 5-second floor for
# sanity. Tests can pass ``tick_interval_secs=1`` for fast iteration.
#

if TYPE_CHECKING:
    from deepseek_tui.tools.task import TaskManager

__all__ = [
    "AutomationSchedulerConfig",
    "run_scheduler_loop",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AutomationSchedulerConfig:
    """Scheduler configuration.

    The ``tick_interval_secs`` floor of 5 matches the ``.max(5)`` floor.
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
    swallowed.
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
        # first.
        try:
            await asyncio.wait_for(cancel.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    logger.info("automation_scheduler_stop")
