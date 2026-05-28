"""Model-visible automation tools backed by :class:`AutomationManager`.

Mirrors Rust ``crates/tui/src/tools/automation.rs`` (382 LOC).

Eight tools:

================== ================================================
``automation_create``    create a durable scheduled automation (REQUIRES_APPROVAL)
``automation_list``      list automations with status / next_run / last_run
``automation_read``      detailed view of one automation + recent runs
``automation_update``    edit name / prompt / rrule / cwds / status
``automation_pause``     pause an active automation
``automation_resume``    resume a paused automation
``automation_delete``    delete (also wipes the automation's run history)
``automation_run``       enqueue a one-off run right now
================== ================================================

The ``AutomationManager`` lives on ``ToolContext.metadata`` under the
key :data:`AUTOMATION_MANAGER_KEY`, set by ``Engine.create`` when the
feature flag is enabled. If no manager is attached (feature flag off),
each tool returns a clean error so the LLM can fall back gracefully.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from deepseek_tui.tools._validators import optional_string as _optional_string
from deepseek_tui.tools._validators import require_string as _require_string
from deepseek_tui.tools.automation_manager import (
    AutomationManager,
    AutomationStatus,
    CreateAutomationRequest,
    UpdateAutomationRequest,
)
from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext

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
        from deepseek_tui.tools.task_manager import TaskManager

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
