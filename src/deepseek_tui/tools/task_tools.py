"""Durable task tools — thin wrappers over :class:`TaskManager`.

Mirrors Rust `crates/tui/src/tools/tasks.rs` (1,012 lines). All 11 tools
delegate to ``context.task_manager`` which provides the durable TaskManager
implementation.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from pathlib import Path
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
from deepseek_tui.tools.task_manager import (
    TaskTimelineEntry as _TimelineEntryFactory,
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
            "properties": {
                "task_id": {"type": "string", "description": "Task id (alias: id)"},
                "id": {"type": "string", "description": "Task id (alias for task_id)"},
            },
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _task_id_from_input(input_data, context)
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
            "properties": {
                "task_id": {"type": "string", "description": "Task id (alias: id)"},
                "id": {"type": "string", "description": "Task id (alias for task_id)"},
            },
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
        task_id = _task_id_from_input(input_data, context)
        try:
            task = await manager.cancel_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return _task_result("task_cancel", task)


class TaskGateRunTool(ToolSpec):
    """Execute a verification gate command and record the result.

    Mirrors Rust ``TaskGateRunTool`` (tasks.rs:287-420). Runs the command,
    captures exit_code/stdout/stderr, computes duration, classifies failure,
    and persists a TaskGateRecord on the task.
    """

    _DEFAULT_TIMEOUT_MS = 120_000
    _MAX_TIMEOUT_MS = 600_000

    def name(self) -> str:
        return "task_gate_run"

    def description(self) -> str:
        return (
            "Execute a verification gate (fmt/check/clippy/test/custom) "
            "against a durable task and record the result."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task id; defaults to active task when inside one.",
                },
                "id": {"type": "string", "description": "Alias for task_id"},
                "gate": {
                    "type": "string",
                    "description": "Gate type: fmt, check, clippy, test, custom",
                },
                "command": {"type": "string", "description": "Shell command to run"},
                "cwd": {"type": "string", "description": "Working directory override"},
                "timeout_ms": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 600000,
                    "description": "Timeout in ms (default 120000)",
                },
            },
            "required": ["gate", "command"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        import time as _time

        manager = _require_manager(context)
        task_id = _optional_task_id_from_input(input_data, context)
        gate = _require_string(input_data, "gate")
        command = _require_string(input_data, "command")
        cwd = _optional_string(input_data, "cwd") or str(context.working_directory)
        timeout_ms = _optional_int(input_data, "timeout_ms") or self._DEFAULT_TIMEOUT_MS
        timeout_ms = min(timeout_ms, self._MAX_TIMEOUT_MS)

        # Execute the command
        start = _time.monotonic()
        timed_out = False
        spawn_error: str | None = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_ms / 1000
            )
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            timed_out = True
            exit_code = None
            stdout_bytes = b""
            stderr_bytes = b"Gate timed out"
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except (OSError, ProcessLookupError):
                pass
        except OSError as exc:
            spawn_error = str(exc)
            exit_code = None
            stdout_bytes = b""
            stderr_bytes = b""
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Failed to run gate command: {exc}") from exc

        duration_ms = int((_time.monotonic() - start) * 1000)
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if timed_out:
            status = "timeout"
        elif spawn_error is not None:
            status = "failed"
        elif exit_code == 0:
            status = "passed"
        else:
            status = "failed"

        classification = _classify_gate_failure(
            gate,
            exit_code if exit_code is not None else -1,
            stdout,
            stderr,
        )

        summary_source = stderr.strip() or stdout.strip() or spawn_error or "(no output)"
        summary = summary_source[-_MAX_SUMMARY_CHARS:]

        full_log = (
            f"$ {command}\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\n"
            + (f"\n[spawn_error]\n{spawn_error}\n" if spawn_error else "")
        )

        from deepseek_tui.tools.task_manager import TaskGateRecord

        gate_id = f"gate_{uuid.uuid4().hex[:8]}"
        log_path: str | None = None
        if task_id is not None:
            rel = manager.write_task_artifact(task_id, f"gate_{gate}", full_log)
            log_path = str(rel)

        gate_record = TaskGateRecord(
            id=gate_id,
            gate=gate,
            command=command,
            cwd=cwd,
            exit_code=exit_code,
            status=status,
            classification=classification,
            duration_ms=duration_ms,
            summary=summary,
            recorded_at=_utc_now_iso(),
            log_path=log_path,
        )

        metadata: dict[str, Any] = {
            "command": command,
            "cwd": cwd,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "gate": asdict(gate_record),
        }
        if log_path is not None:
            metadata["artifact_path"] = log_path
        if task_id is not None:
            artifacts = [
                {
                    "label": "gate_log",
                    "path": log_path or "",
                    "summary": summary[:400],
                }
            ]
            metadata["task_updates"] = {
                "gate": asdict(gate_record),
                "artifacts": artifacts,
            }

        result = ToolResult(
            success=status == "passed",
            content=(
                f"Gate {gate} {'PASSED' if status == 'passed' else status.upper()} "
                f"(rc={exit_code}, {duration_ms}ms)"
            ),
            metadata=metadata,
        )
        if task_id is not None:
            context.active_task_id = task_id
            _forward_to_task_manager(context, metadata)
        return result


class TaskShellStartTool(ToolSpec):
    def name(self) -> str:
        return "task_shell_start"

    def description(self) -> str:
        return (
            "Start a background shell job attached to a durable task. "
            "Uses PTY by default so interactive commands (REPL, ssh) work. "
            "Returns a process_id for task_shell_wait."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task id (alias: id)"},
                "id": {"type": "string", "description": "Alias for task_id"},
                "command": {"type": "string"},
                "pty": {"type": "boolean"},
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        from deepseek_tui.tools.shell_tools import ExecShellTool

        manager = _require_manager(context)
        task_id = _task_id_from_input(input_data, context)
        command = _require_string(input_data, "command")
        use_pty = bool(input_data.get("pty", True))

        # Ensure task exists (raises if not)
        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc

        # Launch background shell via ExecShellTool — reuse its pty logic
        shell_result = await ExecShellTool().execute(
            {"command": command, "background": True, "pty": use_pty},
            context,
        )
        process_id = shell_result.content  # uuid string returned as content
        now = _utc_now_iso()
        task.timeline.append(
            _TimelineEntryFactory(
                timestamp=now,
                kind="shell_started",
                summary=f"bg shell: {command[:120]}",
            )
        )
        # Track mapping task_id → process_id list via context metadata.
        shell_map: dict[str, list[str]] = context.metadata.setdefault(
            "task_shell_process_ids", {}
        )
        shell_map.setdefault(task_id, []).append(process_id)
        async with manager._lock:  # noqa: SLF001
            manager._persist_task_locked(task)  # noqa: SLF001
        return ToolResult(
            success=True,
            content=process_id,
            metadata={
                "task_id": task_id,
                "process_id": process_id,
                "pty": use_pty,
                "command": command,
            },
        )


class TaskShellWaitTool(ToolSpec):
    def name(self) -> str:
        return "task_shell_wait"

    def description(self) -> str:
        return (
            "Wait for a task-attached background shell job to finish and "
            "record its output as a task artifact."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "process_id": {"type": "string"},
                "task_id": {"type": "string"},
            },
            "required": ["process_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        from deepseek_tui.tools.shell_tools import ExecShellWaitTool

        process_id = _require_string(input_data, "process_id")
        task_id_opt = _optional_task_id_from_input(input_data, context)

        # Delegate to ExecShellWaitTool — it handles pty and pipe cases.
        wait_result = await ExecShellWaitTool().execute(
            {"process_id": process_id}, context
        )

        # Record artifact on the task if we know which one.
        if task_id_opt is not None:
            manager = _require_manager(context)
            try:
                task = await manager.get_task(task_id_opt)
            except KeyError as exc:
                raise ToolError(str(exc)) from exc
            now = _utc_now_iso()
            from deepseek_tui.tools.task_manager import TaskArtifactRef

            task.artifacts.append(
                TaskArtifactRef(
                    label=f"shell[{process_id[:8]}]",
                    path=f"memory://shell/{process_id}",
                    summary=(wait_result.content or "")[:400],
                    created_at=now,
                )
            )
            task.timeline.append(
                _TimelineEntryFactory(
                    timestamp=now,
                    kind="shell_completed",
                    summary=f"rc={wait_result.metadata.get('returncode')}",
                )
            )
            async with manager._lock:  # noqa: SLF001
                manager._persist_task_locked(task)  # noqa: SLF001

        merged_meta = dict(wait_result.metadata)
        merged_meta["process_id"] = process_id
        if task_id_opt is not None:
            merged_meta["task_id"] = task_id_opt
        return ToolResult(
            success=wait_result.success,
            content=wait_result.content,
            metadata=merged_meta,
        )


class PrAttemptRecordTool(ToolSpec):
    """Capture a PR attempt with git diff --binary and record it.

    Mirrors Rust ``PrAttemptRecordTool`` (tasks.rs:505-706). Automatically
    runs ``git diff --binary`` to capture the current working tree diff,
    extracts changed_files, computes base/head refs, and writes the patch
    as a durable artifact on the task.
    """

    def name(self) -> str:
        return "pr_attempt_record"

    def description(self) -> str:
        return (
            "Record a PR attempt on a durable task. Automatically captures "
            "git diff --binary as a durable patch artifact."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task id; defaults to active task.",
                },
                "id": {"type": "string", "description": "Alias for task_id"},
                "summary": {"type": "string", "description": "One-line description of the attempt"},
                "attempt_group_id": {"type": "string"},
                "attempt_index": {"type": "integer", "minimum": 1},
                "attempt_count": {"type": "integer", "minimum": 1},
                "verification": {"type": "array", "items": {"type": "string"}},
                "selected": {"type": "boolean"},
            },
            "required": ["summary"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _task_id_from_input(input_data, context)
        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc

        workspace = context.working_directory

        # Capture git state
        base_sha = await _git_output(["git", "rev-parse", "HEAD"], workspace)
        base_ref = await _git_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], workspace
        )

        # Capture binary diff (staged + unstaged)
        diff_bytes = await _git_output_bytes(
            ["git", "diff", "--binary", "HEAD"], workspace
        )
        if not diff_bytes.strip():
            # Try staged only
            diff_bytes = await _git_output_bytes(
                ["git", "diff", "--binary", "--cached"], workspace
            )
        if not diff_bytes.strip():
            raise ToolError("No changes to record (git diff is empty)")

        # Extract changed files from diff
        changed_files = await _git_changed_files(workspace)

        # Write patch artifact
        attempt_id = f"attempt_{uuid.uuid4().hex[:8]}"
        patch_rel_path = f"patches/{task.id}/{attempt_id}.patch"
        patch_abs = manager.data_dir() / patch_rel_path
        patch_abs.parent.mkdir(parents=True, exist_ok=True)
        patch_abs.write_bytes(diff_bytes)

        attempt_index = _optional_int(input_data, "attempt_index") or (
            len(task.attempts) + 1
        )
        attempt_count = _optional_int(input_data, "attempt_count") or attempt_index

        attempt = TaskAttemptRecord(
            id=attempt_id,
            attempt_group_id=_optional_string(input_data, "attempt_group_id")
            or f"group_{uuid.uuid4().hex[:8]}",
            attempt_index=attempt_index,
            attempt_count=attempt_count,
            summary=_require_string(input_data, "summary"),
            changed_files=changed_files,
            verification=[
                str(v) for v in input_data.get("verification", []) if isinstance(v, str)
            ],
            selected=bool(input_data.get("selected", False)),
            recorded_at=_utc_now_iso(),
            base_ref=base_ref,
            base_sha=base_sha,
            head_ref=base_ref,
            head_sha=base_sha,
            patch_path=patch_rel_path,
        )
        task.attempts.append(attempt)
        task.timeline.append(
            _TimelineEntryFactory(
                timestamp=_utc_now_iso(),
                kind="pr_attempt",
                summary=f"attempt #{attempt_index}: {changed_files[:3]}",
            )
        )
        async with manager._lock:  # noqa: SLF001
            manager._persist_task_locked(task)  # noqa: SLF001
        return ToolResult(
            success=True,
            content=(
                f"Recorded PR attempt {attempt.id} on {task.id} "
                f"({len(changed_files)} file(s), patch: {patch_rel_path})"
            ),
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
            "properties": {
                "task_id": {"type": "string", "description": "Task id (alias: id)"},
                "id": {"type": "string", "description": "Task id (alias for task_id)"},
            },
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _task_id_from_input(input_data, context)
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
                "task_id": {
                    "type": "string",
                    "description": "Task id; defaults to active task.",
                },
                "id": {"type": "string", "description": "Alias for task_id"},
                "attempt_id": {"type": "string"},
            },
            "required": ["attempt_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        task_id = _task_id_from_input(input_data, context)
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
    """Run ``git apply --check`` for a recorded attempt patch.

    Mirrors Rust ``PrAttemptPreflightTool`` (crates/tui/src/tools/tasks.rs:707-771).
    No-mutation preflight; actual apply remains explicit and approval-gated
    elsewhere.
    """

    _MAX_SUMMARY_CHARS = 4096

    def name(self) -> str:
        return "pr_attempt_preflight"

    def description(self) -> str:
        return (
            "Run `git apply --check` for a recorded attempt patch. This is "
            "a no-mutation preflight; actual apply remains explicit and "
            "approval-gated elsewhere."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Task id; defaults to active task.",
                },
                "attempt_id": {"type": "string"},
            },
            "required": ["attempt_id"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        attempt_id = _require_string(input_data, "attempt_id")
        task_id = _task_id_from_input(input_data, context)
        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc

        attempt = None
        for a in task.attempts:
            if a.id == attempt_id or a.id.startswith(attempt_id):
                attempt = a
                break
        if attempt is None:
            raise ToolError(f"Attempt not found: {attempt_id}")
        if not attempt.patch_path:
            raise ToolError("Attempt has no patch artifact")

        patch_path = manager.artifact_absolute_path(attempt.patch_path)
        workspace = (
            getattr(context, "workspace", None)
            or getattr(context, "working_directory", None)
            or Path.cwd()
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "apply",
                "--check",
                str(patch_path),
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
        except FileNotFoundError as exc:
            raise ToolError(f"git apply --check failed: {exc}") from exc
        except OSError as exc:
            raise ToolError(f"git apply --check failed: {exc}") from exc

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode
        would_apply = exit_code == 0

        return ToolResult(
            success=True,
            content=(
                f"Preflight {'OK' if would_apply else 'FAILED'} on {task.id} "
                f"attempt {attempt.id}"
            ),
            metadata={
                "task_id": task.id,
                "attempt_id": attempt.id,
                "patch_path": attempt.patch_path,
                "would_apply": would_apply,
                "exit_code": exit_code,
                "stdout_summary": _summarize(stdout, self._MAX_SUMMARY_CHARS),
                "stderr_summary": _summarize(stderr, self._MAX_SUMMARY_CHARS),
                "mutated_worktree": False,
            },
        )


# --- helpers -----------------------------------------------------------


def _summarize(text: str, limit: int) -> str:
    """Mirror of Rust ``summarize`` (tools/tasks.rs:947-965).

    Drops control characters (except ``\\n`` / ``\\t``), truncates to
    ``limit`` chars with a trailing ``...`` marker. Empty result becomes
    ``"(no output)"``.
    """
    out: list[str] = []
    cap = max(limit - 3, 0)
    for idx, ch in enumerate(text):
        if idx >= cap:
            out.append("...")
            break
        if ch in ("\n", "\t") or (ch.isprintable() and not _is_control(ch)):
            out.append(ch)
    result = "".join(out)
    if not result.strip():
        return "(no output)"
    return result


def _is_control(ch: str) -> bool:
    return ord(ch) < 0x20 or ord(ch) == 0x7F


async def _git_output(cmd: list[str], cwd: Path) -> str:
    """Run a git command and return stripped stdout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode("utf-8", errors="replace").strip()


async def _git_output_bytes(cmd: list[str], cwd: Path) -> bytes:
    """Run a git command and return raw stdout bytes."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout


async def _git_changed_files(cwd: Path) -> list[str]:
    """Get list of changed files (staged + unstaged) relative to HEAD."""
    raw = await _git_output(["git", "diff", "--name-only", "HEAD"], cwd)
    if not raw:
        raw = await _git_output(["git", "diff", "--name-only", "--cached"], cwd)
    return [f for f in raw.splitlines() if f.strip()]


def _classify_gate_failure(
    gate: str, exit_code: int, stdout: str, stderr: str
) -> str:
    """Heuristic failure classification mirroring Rust classify_gate_failure().

    Scans output for common error patterns to categorize why a gate failed.
    """
    if exit_code == 0:
        return "pass"
    combined = (stdout + "\n" + stderr).lower()
    if "address already in use" in combined or "port" in combined and "bind" in combined:
        return "port_conflict"
    if gate in ("check", "clippy") or "error[e" in combined:
        return "compile_error"
    if gate == "test" or "test result:" in combined or "failures:" in combined:
        return "test_failure"
    if gate == "fmt" or "diff" in combined and "formatting" in combined:
        return "format_error"
    if "permission denied" in combined:
        return "permission_error"
    if exit_code == -1:
        return "timeout"
    return "unknown"


def _optional_task_id_from_input(
    data: dict[str, Any], context: ToolContext
) -> str | None:
    value = _optional_string(data, "task_id") or _optional_string(data, "id")
    if value is None:
        value = context.active_task_id
    return value


def _forward_to_task_manager(context: ToolContext, metadata: dict[str, Any]) -> None:
    """Persist ``task_updates`` from tool metadata onto the active task."""
    task_id = context.active_task_id or context.metadata.get("task_id")
    manager = _task_manager_from_context(context)
    if not isinstance(task_id, str) or manager is None:
        return
    if not hasattr(manager, "record_tool_metadata"):
        return
    if "task_updates" not in metadata:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(manager.record_tool_metadata(task_id, metadata))


def _task_id_from_input(
    data: dict[str, Any], context: ToolContext, *, required: bool = True
) -> str:
    value = _optional_string(data, "task_id") or _optional_string(data, "id")
    if value is None and context.active_task_id:
        value = context.active_task_id
    if value is None and required:
        raise ToolError("task_id (or id) is required when no active task is set")
    if value is None:
        raise ToolError("task_id is required")
    return value


def _task_manager_from_context(context: ToolContext) -> TaskManager | None:
    manager = context.task_manager
    if manager is None:
        manager = context.services.optional(TaskManager)
    if manager is None:
        raw = context.services.optional_named("task_manager")
        if isinstance(raw, TaskManager):
            manager = raw
    if manager is None:
        raw = context.metadata.get("task_manager")
        if isinstance(raw, TaskManager):
            manager = raw
    return manager


def _require_manager(context: ToolContext) -> TaskManager:
    manager = _task_manager_from_context(context)
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
