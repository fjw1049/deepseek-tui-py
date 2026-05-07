"""Durable task tools — thin wrappers over :class:`TaskManager`.

Mirrors Rust `crates/tui/src/tools/tasks.rs` (1,012 lines). All 11 tools
delegate to ``context.task_manager`` which provides the durable TaskManager
implementation.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any

from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.task_manager import (
    NewTaskRequest,
    TaskAttemptRecord,
    TaskManager,
    TaskRecord,
    TaskStatus,
    _utc_now_iso,
)

_MAX_SUMMARY_CHARS = 900


class TaskCreateTool(ToolSpec):
    def name(self) -> str:
        return "task_create"

    def description(self) -> str:
        return (
            "Create/enqueue a durable background task through TaskManager. "
            "Durable tasks are restart-aware executable work, distinct from sub-agents."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string"},
                "workspace": {"type": "string"},
                "mode": {"type": "string", "enum": ["agent", "plan", "yolo"]},
                "allow_shell": {"type": "boolean"},
                "trust_mode": {"type": "boolean"},
                "auto_approve": {"type": "boolean"},
            },
            "required": ["prompt"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        prompt = _require_string(input_data, "prompt")
        req = NewTaskRequest(
            prompt=prompt,
            model=_optional_string(input_data, "model"),
            workspace=_optional_string(input_data, "workspace"),
            mode=_optional_string(input_data, "mode"),
            allow_shell=_optional_bool(input_data, "allow_shell"),
            trust_mode=_optional_bool(input_data, "trust_mode"),
            auto_approve=_optional_bool(input_data, "auto_approve"),
        )
        try:
            task = await manager.add_task(req)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return _task_result("task_create", task)


class TaskListTool(ToolSpec):
    def name(self) -> str:
        return "task_list"

    def description(self) -> str:
        return "List durable tasks (newest first)."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1}},
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        limit_val = input_data.get("limit")
        limit = int(limit_val) if isinstance(limit_val, int) else None
        summaries = await manager.list_tasks(limit)
        payload = [asdict(s) | {"status": s.status.value} for s in summaries]
        return ToolResult(
            success=True,
            content=f"{len(payload)} task(s)",
            metadata={"tasks": payload},
        )


class TaskReadTool(ToolSpec):
    def name(self) -> str:
        return "task_read"

    def description(self) -> str:
        return "Read a durable task by id or unique prefix."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _require_string(input_data, "id")
        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return _task_result("task_read", task)


class TaskCancelTool(ToolSpec):
    def name(self) -> str:
        return "task_cancel"

    def description(self) -> str:
        return "Cancel a queued or running durable task."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.SUGGEST

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _require_string(input_data, "id")
        try:
            task = await manager.cancel_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return _task_result("task_cancel", task)


class TaskGateRunTool(ToolSpec):
    def name(self) -> str:
        return "task_gate_run"

    def description(self) -> str:
        return (
            "Record a verification gate (tests/lint/type-check) against a durable task."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "gate": {"type": "string"},
                "command": {"type": "string"},
                "exit_code": {"type": "integer"},
                "status": {"type": "string"},
                "summary": {"type": "string"},
                "duration_ms": {"type": "integer"},
            },
            "required": ["id", "gate", "command", "status"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _require_string(input_data, "id")
        gate = _require_string(input_data, "gate")
        command = _require_string(input_data, "command")
        status = _require_string(input_data, "status")

        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc

        from deepseek_tui.tools.task_manager import TaskGateRecord

        record = TaskGateRecord(
            id=f"gate_{uuid.uuid4().hex[:8]}",
            gate=gate,
            command=command,
            cwd=str(context.working_directory),
            exit_code=_optional_int(input_data, "exit_code"),
            status=status,
            classification=status,
            duration_ms=_optional_int(input_data, "duration_ms") or 0,
            summary=_optional_string(input_data, "summary") or "",
            recorded_at=_utc_now_iso(),
        )
        task.gates.append(record)
        async with manager._lock:  # noqa: SLF001 -- test harness hook
            manager._persist_task_locked(task)  # noqa: SLF001
        return ToolResult(
            success=True,
            content=f"Recorded gate {gate} on {task.id}",
            metadata={"task_id": task.id, "gate": asdict(record)},
        )


class TaskShellStartTool(ToolSpec):
    def name(self) -> str:
        return "task_shell_start"

    def description(self) -> str:
        return (
            "[stub] Start a background shell job attached to a task. "
            "Full PTY implementation lands in Stage 3.4 (see integration debt)."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "command": {"type": "string"},
            },
            "required": ["id", "command"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        raise ToolError("task_shell_start not yet implemented; see Stage 3.4")


class TaskShellWaitTool(ToolSpec):
    def name(self) -> str:
        return "task_shell_wait"

    def description(self) -> str:
        return "[stub] Wait for a task-attached background shell job."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"process_id": {"type": "string"}},
            "required": ["process_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        raise ToolError("task_shell_wait not yet implemented; see Stage 3.4")


class PrAttemptRecordTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_record"

    def description(self) -> str:
        return "Record a PR attempt on a durable task."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "attempt_group_id": {"type": "string"},
                "attempt_index": {"type": "integer", "minimum": 1},
                "attempt_count": {"type": "integer", "minimum": 1},
                "summary": {"type": "string"},
                "changed_files": {"type": "array", "items": {"type": "string"}},
                "verification": {"type": "array", "items": {"type": "string"}},
                "base_ref": {"type": "string"},
                "base_sha": {"type": "string"},
                "head_ref": {"type": "string"},
                "head_sha": {"type": "string"},
                "patch_path": {"type": "string"},
                "selected": {"type": "boolean"},
            },
            "required": ["id", "summary"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _require_string(input_data, "id")
        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc

        attempt_index = _optional_int(input_data, "attempt_index") or (
            len(task.attempts) + 1
        )
        attempt_count = _optional_int(input_data, "attempt_count") or attempt_index
        attempt = TaskAttemptRecord(
            id=f"attempt_{uuid.uuid4().hex[:8]}",
            attempt_group_id=_optional_string(input_data, "attempt_group_id")
            or f"group_{uuid.uuid4().hex[:8]}",
            attempt_index=attempt_index,
            attempt_count=attempt_count,
            summary=_require_string(input_data, "summary"),
            changed_files=[
                str(p) for p in input_data.get("changed_files", []) if isinstance(p, str)
            ],
            verification=[
                str(v) for v in input_data.get("verification", []) if isinstance(v, str)
            ],
            selected=bool(input_data.get("selected", False)),
            recorded_at=_utc_now_iso(),
            base_ref=_optional_string(input_data, "base_ref"),
            base_sha=_optional_string(input_data, "base_sha"),
            head_ref=_optional_string(input_data, "head_ref"),
            head_sha=_optional_string(input_data, "head_sha"),
            patch_path=_optional_string(input_data, "patch_path"),
        )
        task.attempts.append(attempt)
        async with manager._lock:  # noqa: SLF001
            manager._persist_task_locked(task)  # noqa: SLF001
        return ToolResult(
            success=True,
            content=f"Recorded PR attempt {attempt.id} on {task.id}",
            metadata={"task_id": task.id, "attempt": asdict(attempt)},
        )


class PrAttemptListTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_list"

    def description(self) -> str:
        return "List PR attempts attached to a durable task."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _require_string(input_data, "id")
        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        attempts = [asdict(a) for a in task.attempts]
        return ToolResult(
            success=True,
            content=f"{len(attempts)} attempt(s) on {task.id}",
            metadata={"task_id": task.id, "attempts": attempts},
        )


class PrAttemptReadTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_read"

    def description(self) -> str:
        return "Read a specific PR attempt on a durable task."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "attempt_id": {"type": "string"},
            },
            "required": ["id", "attempt_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _require_string(input_data, "id")
        attempt_id = _require_string(input_data, "attempt_id")
        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        for attempt in task.attempts:
            if attempt.id == attempt_id or attempt.id.startswith(attempt_id):
                return ToolResult(
                    success=True,
                    content=f"Attempt {attempt.id} on {task.id}",
                    metadata={"task_id": task.id, "attempt": asdict(attempt)},
                )
        raise ToolError(f"Attempt not found: {attempt_id}")


class PrAttemptPreflightTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_preflight"

    def description(self) -> str:
        return (
            "Run preflight checks before recording a PR attempt "
            "(stub: returns a diagnostics summary)."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "base_ref": {"type": "string"},
                "head_ref": {"type": "string"},
            },
            "required": ["id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _require_string(input_data, "id")
        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        base_ref = _optional_string(input_data, "base_ref")
        head_ref = _optional_string(input_data, "head_ref")
        return ToolResult(
            success=True,
            content=f"Preflight OK on {task.id}",
            metadata={
                "task_id": task.id,
                "status": "ok",
                "base_ref": base_ref,
                "head_ref": head_ref,
                "existing_attempts": len(task.attempts),
            },
        )


# --- helpers -----------------------------------------------------------


def _require_manager(context: ToolContext) -> TaskManager:
    manager = context.task_manager
    if manager is None:
        raise ToolError("TaskManager is not attached to this context")
    return manager


def _task_result(action: str, task: TaskRecord) -> ToolResult:
    summary = task.result_summary or task.error or ""
    return ToolResult(
        success=task.status is not TaskStatus.FAILED,
        content=f"{action}: {task.id} [{task.status.value}]",
        metadata={
            "task_id": task.id,
            "status": task.status.value,
            "prompt_summary": task.prompt[:_MAX_SUMMARY_CHARS],
            "created_at": task.created_at,
            "started_at": task.started_at,
            "ended_at": task.ended_at,
            "duration_ms": task.duration_ms,
            "error": task.error,
            "result_summary": summary,
            "timeline_len": len(task.timeline),
            "gates_len": len(task.gates),
            "attempts_len": len(task.attempts),
        },
    )


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{key} must be a non-empty string")
    return value


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def _optional_bool(data: dict[str, Any], key: str) -> bool | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ToolError(f"{key} must be a boolean")
    return value


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
    return int(value)
