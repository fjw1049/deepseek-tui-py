"""Task lifecycle — tools and persistence manager.

Consolidates task_tools.py and task_manager.py.
"""

from __future__ import annotations



# Durable task tools — thin wrappers over :class:`TaskManager`.
#
# Mirrors Rust `crates/tui/src/tools/tasks.rs` (1,012 lines). All 11 tools
# delegate to ``context.task_manager`` which provides the durable TaskManager
# implementation.
#
import asyncio
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext

_MAX_SUMMARY_CHARS = 900


class TaskCreateTool(ToolSpec):
    def name(self) -> str:
        return "task_create"

    def description(self) -> str:
        return (
            "Create/enqueue a durable, restart-aware background task that runs "
            "DETACHED from this conversation. Fire-and-forget: returns a task id "
            "immediately, runs in a background worker, and its result lands in the "
            "TASKS panel (read later via task_read) — it does NOT come back into "
            "this turn. Use ONLY for long-running work the user will not wait for "
            "here. If you need to WAIT for the result, AGGREGATE several results, "
            "or report back in this reply (e.g. 'benchmark X and Y and summarize'), "
            "use sub-agents instead (agent_spawn + agent_wait, or delegate_to_agent). "
            "Never split one combined-report request into multiple tasks — they run "
            "independently and are never aggregated."
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
        origin_thread = context.metadata.get("runtime_thread_id")
        req = NewTaskRequest(
            prompt=prompt,
            model=_optional_string(input_data, "model"),
            workspace=_optional_string(input_data, "workspace"),
            mode=_optional_string(input_data, "mode"),
            allow_shell=_optional_bool(input_data, "allow_shell"),
            trust_mode=_optional_bool(input_data, "trust_mode"),
            auto_approve=_optional_bool(input_data, "auto_approve"),
            thread_id=origin_thread if isinstance(origin_thread, str) else None,
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
        from deepseek_tui.tools.shell import ExecShellTool

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
            TaskTimelineEntry(
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
        from deepseek_tui.tools.shell import ExecShellWaitTool

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

            task.artifacts.append(
                TaskArtifactRef(
                    label=f"shell[{process_id[:8]}]",
                    path=f"memory://shell/{process_id}",
                    summary=(wait_result.content or "")[:400],
                    created_at=now,
                )
            )
            task.timeline.append(
                TaskTimelineEntry(
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
            TaskTimelineEntry(
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
    manager = context.task_manager or context.metadata.get("task_manager")
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


# Durable task manager.
#
# Mirrors `crates/tui/src/task_manager.rs` (1,845 lines). Persists each task as
# its own JSON file under ``./.deepseek/tasks/`` and maintains a queue in
# ``queue.json`` so tasks survive process restarts.
#
import asyncio
import json
import os
import tempfile
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

CURRENT_TASK_SCHEMA_VERSION = 2
TIMELINE_SUMMARY_LIMIT = 240
ARTIFACT_THRESHOLD = 1200
MAX_WORKERS = 4
_MAX_TERMINAL_IN_MEMORY = 50
# Running tasks older than this at recovery are failed instead of re-queued.
STALE_RUNNING_TASK_SECONDS = 300
CRON_PROMPT_MARKER = "[cron:"
STALE_RESTART_ERROR = "Task interrupted (stale after restart)"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

    def is_terminal(self) -> bool:
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED)


class TaskToolStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(slots=True)
class TaskTimelineEntry:
    timestamp: str
    kind: str
    summary: str
    detail_path: str | None = None


@dataclass(slots=True)
class TaskToolCallSummary:
    id: str
    name: str
    status: TaskToolStatus
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    detail_path: str | None = None
    patch_ref: str | None = None


@dataclass(slots=True)
class TaskChecklistItem:
    id: int
    content: str
    status: str


@dataclass(slots=True)
class TaskChecklistState:
    items: list[TaskChecklistItem] = field(default_factory=list)
    completion_pct: int = 0
    in_progress_id: int | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class TaskGateRecord:
    id: str
    gate: str
    command: str
    cwd: str
    exit_code: int | None
    status: str
    classification: str
    duration_ms: int
    summary: str
    recorded_at: str
    log_path: str | None = None


@dataclass(slots=True)
class TaskAttemptRecord:
    id: str
    attempt_group_id: str
    attempt_index: int
    attempt_count: int
    summary: str
    changed_files: list[str]
    verification: list[str]
    selected: bool
    recorded_at: str
    base_ref: str | None = None
    base_sha: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    patch_path: str | None = None


@dataclass(slots=True)
class TaskArtifactRef:
    label: str
    path: str
    summary: str
    created_at: str


@dataclass(slots=True)
class TaskGithubEvent:
    id: str
    action: str
    target: str
    number: int
    summary: str
    recorded_at: str
    url: str | None = None


@dataclass(slots=True)
class TaskRecord:
    schema_version: int
    id: str
    prompt: str
    model: str
    workspace: str
    mode: str
    allow_shell: bool
    trust_mode: bool
    auto_approve: bool
    status: TaskStatus
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    result_summary: str | None = None
    result_detail_path: str | None = None
    error: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    runtime_event_count: int = 0
    checklist: TaskChecklistState = field(default_factory=TaskChecklistState)
    gates: list[TaskGateRecord] = field(default_factory=list)
    attempts: list[TaskAttemptRecord] = field(default_factory=list)
    artifacts: list[TaskArtifactRef] = field(default_factory=list)
    github_events: list[TaskGithubEvent] = field(default_factory=list)
    tool_calls: list[TaskToolCallSummary] = field(default_factory=list)
    timeline: list[TaskTimelineEntry] = field(default_factory=list)

    def summary(self) -> TaskSummary:
        return TaskSummary(
            id=self.id,
            status=self.status,
            prompt_summary=_summarize_text(self.prompt, TIMELINE_SUMMARY_LIMIT),
            model=self.model,
            mode=self.mode,
            created_at=self.created_at,
            started_at=self.started_at,
            ended_at=self.ended_at,
            duration_ms=self.duration_ms,
            error=self.error,
            thread_id=self.thread_id,
            turn_id=self.turn_id,
        )


@dataclass(slots=True)
class TaskSummary:
    id: str
    status: TaskStatus
    prompt_summary: str
    model: str
    mode: str
    created_at: str
    started_at: str | None
    ended_at: str | None
    duration_ms: int | None
    error: str | None
    thread_id: str | None
    turn_id: str | None


@dataclass(slots=True)
class TaskCounts:
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    canceled: int = 0


@dataclass(slots=True)
class NewTaskRequest:
    prompt: str
    model: str | None = None
    workspace: str | None = None
    mode: str | None = None
    allow_shell: bool | None = None
    trust_mode: bool | None = None
    auto_approve: bool | None = None
    thread_id: str | None = None


@dataclass(slots=True)
class TaskManagerConfig:
    data_dir: Path
    default_workspace: Path
    default_model: str = "deepseek-chat"
    default_mode: str = "agent"
    allow_shell: bool = False
    trust_mode: bool = False
    worker_count: int = 1
    max_subagents: int = 4


@dataclass(slots=True)
class ExecutionTask:
    id: str
    prompt: str
    model: str
    workspace: str
    mode_label: str
    allow_shell: bool
    trust_mode: bool
    auto_approve: bool
    # Back-reference to the owning TaskManager, populated by
    # ``TaskManager._pop_next_task``. Executors propagate it to the
    # spawned Engine's ``ToolContext.metadata`` so tools like
    # ``checklist_write`` can forward their snapshots to the durable
    # task record via :meth:`TaskManager.record_tool_metadata`.
    # Typed as ``Any`` to avoid a forward reference / circular type.
    task_manager: Any = None


@dataclass(slots=True)
class TaskExecutionResult:
    summary: str
    detail: str | None = None
    error: str | None = None


ExecutorFunc = Callable[[ExecutionTask, asyncio.Event], Awaitable[TaskExecutionResult]]


def default_tasks_dir() -> Path:
    """``~/.deepseek/tasks/`` — cross-project task queue.

    Mirrors Rust ``default_tasks_dir`` (task_manager.rs:1629). User-level so
    background tasks survive across project switches. ``DEEPSEEK_TASKS_DIR``
    env var overrides.
    """
    from deepseek_tui.config.paths import user_tasks_dir

    return user_tasks_dir()


async def _stub_executor(
    task: ExecutionTask, cancel: asyncio.Event
) -> TaskExecutionResult:
    """Placeholder executor: sleeps briefly, returns synthetic result.

    Integration debt: Stage 3.1.simplified: real TaskExecutor not wired.
    Use ``real_task_executor`` from ``engine.executors`` for production.
    """
    try:
        await asyncio.wait_for(cancel.wait(), timeout=0.05)
    except asyncio.TimeoutError:
        return TaskExecutionResult(
            summary=f"[stub] task '{task.prompt[:60]}' completed without real executor",
            detail=None,
            error=None,
        )
    return TaskExecutionResult(summary="", error="canceled")


def get_real_task_executor() -> ExecutorFunc:
    """Return the real task executor that drives Engine turn loops."""
    from deepseek_tui.engine.dispatch import real_task_executor

    return real_task_executor


class TaskManager:
    """Durable task manager.

    Mirrors Rust `TaskManager` (task_manager.rs:702-1472).
    """

    def __init__(
        self,
        cfg: TaskManagerConfig,
        executor: ExecutorFunc | None = None,
    ) -> None:
        self._cfg = cfg
        self._executor: ExecutorFunc = executor or _stub_executor
        self._tasks_dir = cfg.data_dir / "tasks"
        self._artifacts_dir = cfg.data_dir / "artifacts"
        self._queue_path = cfg.data_dir / "queue.json"
        self._tasks: dict[str, TaskRecord] = {}
        self._queue: deque[str] = deque()
        self._running_cancel: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._notify = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._worker_tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Initialize directories, load prior state, spawn workers."""
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

        tasks, queue = _load_state(self._tasks_dir, self._queue_path)
        self._tasks = tasks
        self._queue = queue

        async with self._lock:
            self._persist_all_locked()

        workers = max(1, min(self._cfg.worker_count, MAX_WORKERS))
        for _ in range(workers):
            self._worker_tasks.append(asyncio.create_task(self._worker_loop()))

    async def shutdown(self) -> None:
        self._shutdown.set()
        self._notify.set()
        for token in self._running_cancel.values():
            token.set()
        for task in self._worker_tasks:
            task.cancel()
        for task in self._worker_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._worker_tasks.clear()

    def is_shutdown(self) -> bool:
        return self._shutdown.is_set()

    def running_count(self) -> int:
        """Count queued + running durable tasks (for session activity UI)."""
        return sum(
            1
            for t in self._tasks.values()
            if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)
        )

    def data_dir(self) -> Path:
        return self._cfg.data_dir

    def artifact_absolute_path(self, patch_ref: str) -> Path:
        """Resolve a recorded artifact reference to an absolute path.

        Mirrors Rust ``TaskManager::artifact_absolute_path``.
        """
        p = Path(patch_ref)
        if p.is_absolute():
            return p
        return self._cfg.data_dir / p

    def write_task_artifact(
        self, task_id: str, label: str, content: str
    ) -> Path:
        """Write a durable task artifact and return the persisted relative path."""
        artifact_dir = self._artifacts_dir / task_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        stamp = _utc_now_iso().replace(":", "").replace("-", "")
        safe_label = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
        if not safe_label:
            safe_label = "artifact"
        filename = f"{stamp}_{safe_label}.txt"
        absolute = artifact_dir / filename
        absolute.write_text(content, encoding="utf-8")
        try:
            return absolute.relative_to(self._cfg.data_dir)
        except ValueError:
            return absolute

    async def add_task(self, req: NewTaskRequest) -> TaskRecord:
        prompt = req.prompt.strip()
        if not prompt:
            raise ValueError("Task prompt cannot be empty")

        now = _utc_now_iso()
        task = TaskRecord(
            schema_version=CURRENT_TASK_SCHEMA_VERSION,
            id=f"task_{uuid.uuid4().hex[:8]}",
            prompt=prompt,
            model=req.model or self._cfg.default_model,
            workspace=str(
                Path(req.workspace) if req.workspace else self._cfg.default_workspace
            ),
            mode=req.mode or self._cfg.default_mode,
            allow_shell=(
                req.allow_shell if req.allow_shell is not None else self._cfg.allow_shell
            ),
            trust_mode=(
                req.trust_mode if req.trust_mode is not None else self._cfg.trust_mode
            ),
            auto_approve=req.auto_approve if req.auto_approve is not None else False,
            status=TaskStatus.QUEUED,
            created_at=now,
            thread_id=req.thread_id,
            timeline=[
                TaskTimelineEntry(
                    timestamp=now, kind="queued", summary="Task queued"
                )
            ],
        )

        async with self._lock:
            self._queue.append(task.id)
            self._tasks[task.id] = task
            self._persist_all_locked()
        self._notify.set()
        return task

    async def list_tasks(
        self,
        limit: int | None = None,
        *,
        since: str | None = None,
    ) -> list[TaskSummary]:
        """List durable tasks (newest first).

        ``since`` is an ISO-8601 timestamp; tasks with ``created_at <
        since`` are filtered out. Callers like the right info-sidebar
        use this to avoid surfacing stale `failed` records from prior
        TUI sessions every time the user opens a fresh chat (issue
        triaged 2026-05-12 — fresh "hello" was lighting up the panel
        with last week's pytest-failed tasks).
        """
        async with self._lock:
            items = [record.summary() for record in self._tasks.values()]
        if since is not None:
            items = [s for s in items if s.created_at >= since]
        items.sort(key=lambda s: s.created_at, reverse=True)
        if limit is not None:
            items = items[:limit]
        return items

    async def get_task(self, id_or_prefix: str) -> TaskRecord:
        async with self._lock:
            try:
                task_id = _resolve_task_id(self._tasks, id_or_prefix)
                return self._tasks[task_id]
            except KeyError:
                pass
            task = self._reload_task_from_disk(id_or_prefix)
            if task is not None:
                return task
            raise KeyError(f"Task not found: {id_or_prefix}")

    def _reload_task_from_disk(self, id_or_prefix: str) -> TaskRecord | None:
        for path in self._tasks_dir.glob("*.json"):
            tid = path.stem
            if tid == id_or_prefix or tid.startswith(id_or_prefix):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    task = _task_record_from_dict(data)
                    self._tasks[task.id] = task
                    return task
                except (OSError, json.JSONDecodeError, KeyError):
                    continue
        return None

    async def cancel_task(self, id_or_prefix: str) -> TaskRecord:
        now = _utc_now_iso()
        token_to_cancel: asyncio.Event | None = None
        async with self._lock:
            task_id = _resolve_task_id(self._tasks, id_or_prefix)
            task = self._tasks[task_id]
            if task.status is TaskStatus.QUEUED:
                task.status = TaskStatus.CANCELED
                task.ended_at = now
                task.duration_ms = 0
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="canceled",
                        summary="Task canceled before execution",
                    )
                )
                self._queue = deque(q for q in self._queue if q != task_id)
            elif task.status is TaskStatus.RUNNING:
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="cancel_requested",
                        summary="Cancellation requested",
                    )
                )
                token_to_cancel = self._running_cancel.get(task_id)

            self._persist_all_locked()
            result = self._tasks[task_id]

        if token_to_cancel is not None:
            token_to_cancel.set()
        return result

    async def record_tool_metadata(
        self, id_or_prefix: str, metadata: dict[str, Any]
    ) -> TaskRecord | None:
        """Apply ``task_updates`` from a tool's result metadata to the task.

        Mirrors Rust ``TaskManager::record_tool_metadata``
        (``task_manager.rs:985-1003``). Currently honors the
        ``task_updates.checklist`` key — see
        :meth:`_apply_task_update_metadata` for details. Returns the
        updated record, or ``None`` if the task no longer exists (e.g.
        was cancelled and removed between events).

        Tools call this via the side-channel set up by
        :class:`real_task_executor`: ``ToolContext.metadata`` carries a
        ``task_manager`` reference + ``task_id``; the checklist tools
        invoke ``manager.record_tool_metadata(task_id, metadata)`` after
        every successful write. Quiet no-op when ``task_updates`` is
        missing so non-checklist tools don't have to opt out.
        """
        if not isinstance(metadata, dict):
            return None
        if "task_updates" not in metadata:
            return None
        async with self._lock:
            try:
                task_id = _resolve_task_id(self._tasks, id_or_prefix)
            except KeyError:
                return None
            task = self._tasks.get(task_id)
            if task is None:
                return None
            self._apply_task_update_metadata(task, metadata)
            self._persist_task_locked(task)
            return task

    def _apply_task_update_metadata(
        self, task: TaskRecord, metadata: dict[str, Any]
    ) -> None:
        """Translate ``task_updates`` payload into ``TaskRecord`` mutations."""
        updates = metadata.get("task_updates")
        if not isinstance(updates, dict):
            return
        now = _utc_now_iso()

        checklist_payload = updates.get("checklist")
        if isinstance(checklist_payload, dict):
            items_raw = checklist_payload.get("items", [])
            items: list[TaskChecklistItem] = []
            if isinstance(items_raw, list):
                for entry in items_raw:
                    if not isinstance(entry, dict):
                        continue
                    raw_id = entry.get("id")
                    try:
                        item_id = int(raw_id) if raw_id is not None else 0
                    except (TypeError, ValueError):
                        continue
                    items.append(
                        TaskChecklistItem(
                            id=item_id,
                            content=str(entry.get("content", "")),
                            status=str(entry.get("status", "pending")),
                        )
                    )
            try:
                completion_pct = int(checklist_payload.get("completion_pct", 0))
            except (TypeError, ValueError):
                completion_pct = 0
            in_progress_raw = checklist_payload.get("in_progress_id")
            in_progress_id = (
                int(in_progress_raw)
                if isinstance(in_progress_raw, int)
                else None
            )
            task.checklist = TaskChecklistState(
                items=items,
                completion_pct=completion_pct,
                in_progress_id=in_progress_id,
                updated_at=now,
            )
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=now,
                    kind="checklist",
                    summary=(
                        f"Checklist updated: {len(items)} item(s), "
                        f"{completion_pct}% complete"
                    ),
                )
            )

        gate_payload = updates.get("gate")
        if isinstance(gate_payload, dict):
            gate = TaskGateRecord(
                id=str(gate_payload.get("id", f"gate_{uuid.uuid4().hex[:8]}")),
                gate=str(gate_payload.get("gate", "custom")),
                command=str(gate_payload.get("command", "")),
                cwd=str(gate_payload.get("cwd", task.workspace)),
                exit_code=gate_payload.get("exit_code"),
                status=str(gate_payload.get("status", "unknown")),
                classification=str(gate_payload.get("classification", "unknown")),
                duration_ms=int(gate_payload.get("duration_ms") or 0),
                summary=str(gate_payload.get("summary", "")),
                recorded_at=str(gate_payload.get("recorded_at") or now),
                log_path=gate_payload.get("log_path"),
            )
            task.gates = [g for g in task.gates if g.id != gate.id] + [gate]
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=now,
                    kind="gate",
                    summary=_summarize_text(
                        f"Gate {gate.gate} {gate.status}: {gate.summary}",
                        TIMELINE_SUMMARY_LIMIT,
                    ),
                    detail_path=str(gate.log_path) if gate.log_path else None,
                )
            )

        attempt_payload = updates.get("attempt")
        if isinstance(attempt_payload, dict):
            attempt = TaskAttemptRecord(
                id=str(attempt_payload.get("id", f"attempt_{uuid.uuid4().hex[:8]}")),
                attempt_group_id=str(
                    attempt_payload.get("attempt_group_id", "group_unknown")
                ),
                attempt_index=int(attempt_payload.get("attempt_index") or 1),
                attempt_count=int(attempt_payload.get("attempt_count") or 1),
                summary=str(attempt_payload.get("summary", "")),
                changed_files=list(attempt_payload.get("changed_files") or []),
                verification=list(attempt_payload.get("verification") or []),
                selected=bool(attempt_payload.get("selected", False)),
                recorded_at=str(attempt_payload.get("recorded_at") or now),
                base_ref=attempt_payload.get("base_ref"),
                base_sha=attempt_payload.get("base_sha"),
                head_ref=attempt_payload.get("head_ref"),
                head_sha=attempt_payload.get("head_sha"),
                patch_path=attempt_payload.get("patch_path"),
            )
            task.attempts = [
                a for a in task.attempts if a.id != attempt.id
            ] + [attempt]
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=now,
                    kind="pr_attempt",
                    summary=(
                        f"Attempt {attempt.attempt_index}/{attempt.attempt_count} "
                        f"recorded"
                    ),
                    detail_path=str(attempt.patch_path) if attempt.patch_path else None,
                )
            )

        artifacts_payload = updates.get("artifacts")
        if isinstance(artifacts_payload, list):
            for item in artifacts_payload:
                if not isinstance(item, dict):
                    continue
                artifact = TaskArtifactRef(
                    label=str(item.get("label", "artifact")),
                    path=str(item.get("path", "")),
                    summary=str(item.get("summary", "")),
                    created_at=str(item.get("created_at") or now),
                )
                task.artifacts.append(artifact)
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="artifact",
                        summary=f"{artifact.label}: {artifact.summary}",
                        detail_path=artifact.path,
                    )
                )

        github_payload = updates.get("github_event")
        if isinstance(github_payload, dict):
            event = TaskGithubEvent(
                id=str(github_payload.get("id", f"github_{uuid.uuid4().hex[:8]}")),
                action=str(github_payload.get("action", "")),
                target=str(github_payload.get("target", "")),
                number=int(github_payload.get("number") or 0),
                summary=str(github_payload.get("summary", "")),
                recorded_at=str(github_payload.get("recorded_at") or now),
                url=github_payload.get("url"),
            )
            task.github_events.append(event)
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=now,
                    kind="github",
                    summary=(
                        f"{event.action} {event.target}#{event.number}: "
                        f"{event.summary}"
                    ),
                )
            )

    async def record_tool_timeline(
        self, task_id: str, kind: str, summary: str
    ) -> None:
        """Append a live progress entry for an in-flight task and persist it.

        Called by the background executor for each tool call start/finish so the
        UI can poll ``timeline`` and show what a running task is currently doing.
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=_utc_now_iso(),
                    kind=kind,
                    summary=_summarize_text(summary, TIMELINE_SUMMARY_LIMIT),
                )
            )
            self._persist_task_locked(task)

    async def counts(self) -> TaskCounts:
        async with self._lock:
            counts = TaskCounts()
            for task in self._tasks.values():
                if task.status is TaskStatus.QUEUED:
                    counts.queued += 1
                elif task.status is TaskStatus.RUNNING:
                    counts.running += 1
                elif task.status is TaskStatus.COMPLETED:
                    counts.completed += 1
                elif task.status is TaskStatus.FAILED:
                    counts.failed += 1
                elif task.status is TaskStatus.CANCELED:
                    counts.canceled += 1
            return counts

    def _count_running_cron_tasks_locked(self) -> int:
        return sum(
            1
            for task in self._tasks.values()
            if task.status is TaskStatus.RUNNING
            and task.prompt.lstrip().startswith(CRON_PROMPT_MARKER)
        )

    async def _worker_loop(self) -> None:
        while not self._shutdown.is_set():
            next_run = await self._pop_next_task()
            if next_run is None:
                try:
                    await asyncio.wait_for(self._notify.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                finally:
                    self._notify.clear()
                continue
            await self._run_task(*next_run)

    async def _pop_next_task(self) -> tuple[str, ExecutionTask, asyncio.Event] | None:
        async with self._lock:
            attempts = len(self._queue)
            while attempts > 0 and self._queue:
                attempts -= 1
                task_id = self._queue.popleft()
                task = self._tasks.get(task_id)
                if task is None or task.status is not TaskStatus.QUEUED:
                    self._persist_queue_locked()
                    continue
                if (
                    task.prompt.lstrip().startswith(CRON_PROMPT_MARKER)
                    and self._count_running_cron_tasks_locked() >= 1
                ):
                    self._queue.append(task_id)
                    self._persist_queue_locked()
                    continue
                now = _utc_now_iso()
                task.status = TaskStatus.RUNNING
                task.started_at = now
                task.ended_at = None
                task.duration_ms = None
                task.error = None
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now, kind="running", summary="Task started"
                    )
                )
                request = ExecutionTask(
                    id=task.id,
                    prompt=task.prompt,
                    model=task.model,
                    workspace=task.workspace,
                    mode_label=task.mode,
                    allow_shell=task.allow_shell,
                    trust_mode=task.trust_mode,
                    auto_approve=task.auto_approve,
                    task_manager=self,
                )
                cancel = asyncio.Event()
                self._running_cancel[task_id] = cancel
                self._persist_all_locked()
                return task_id, request, cancel
        return None

    async def _run_task(
        self, task_id: str, request: ExecutionTask, cancel: asyncio.Event
    ) -> None:
        result: TaskExecutionResult
        try:
            result = await self._executor(request, cancel)
        except Exception as exc:  # noqa: BLE001 -- translate all errors into task state
            result = TaskExecutionResult(summary="", error=str(exc))

        async with self._lock:
            self._running_cancel.pop(task_id, None)
            task = self._tasks.get(task_id)
            if task is None:
                return
            now = _utc_now_iso()
            task.ended_at = now
            if task.started_at is not None:
                task.duration_ms = _duration_ms(task.started_at, now)
            if cancel.is_set() and task.status is not TaskStatus.CANCELED:
                task.status = TaskStatus.CANCELED
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="canceled",
                        summary="Task canceled mid-run",
                    )
                )
            elif result.error:
                task.status = TaskStatus.FAILED
                task.error = result.error
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="failed",
                        summary=_summarize_text(result.error, TIMELINE_SUMMARY_LIMIT),
                    )
                )
            else:
                task.status = TaskStatus.COMPLETED
                task.result_summary = result.summary
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="completed",
                        summary=_summarize_text(result.summary, TIMELINE_SUMMARY_LIMIT),
                    )
                )
            self._persist_all_locked()
            self._evict_terminal_tasks_locked()

    def _evict_terminal_tasks_locked(self) -> None:
        terminal = [
            (tid, t) for tid, t in self._tasks.items() if t.status.is_terminal()
        ]
        if len(terminal) <= _MAX_TERMINAL_IN_MEMORY:
            return
        terminal.sort(key=lambda x: x[1].ended_at or "")
        to_remove = len(terminal) - _MAX_TERMINAL_IN_MEMORY
        for tid, _ in terminal[:to_remove]:
            del self._tasks[tid]

    def _persist_all_locked(self) -> None:
        self._persist_queue_locked()
        for task in self._tasks.values():
            self._persist_task_locked(task)

    def _persist_queue_locked(self) -> None:
        _write_json_atomic(self._queue_path, {"queue": list(self._queue)})

    def _persist_task_locked(self, task: TaskRecord) -> None:
        path = self._tasks_dir / f"{task.id}.json"
        _write_json_atomic(path, _task_record_to_dict(task))


# --- module-level helpers ------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_stale_running_task(task: TaskRecord) -> bool:
    started = _parse_iso_utc(task.started_at)
    if started is None:
        return False
    age = (datetime.now(timezone.utc) - started).total_seconds()
    return age > STALE_RUNNING_TASK_SECONDS


def _duration_ms(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    delta = end - start
    millis = int(delta.total_seconds() * 1000)
    return max(0, millis)


def _summarize_text(text: str, limit: int) -> str:
    take = max(0, limit - 3)
    out: list[str] = []
    count = 0
    for ch in text:
        if count >= take:
            out.append("...")
            return "".join(out)
        if ch.isprintable() is False and ch not in ("\n", "\t"):
            continue
        out.append(ch)
        count += 1
    return "".join(out)


def _resolve_task_id(tasks: dict[str, TaskRecord], id_or_prefix: str) -> str:
    """Resolve a task id or unique prefix to a full id.

    Mirrors Rust `resolve_task_id()` (task_manager.rs:1545-1563).
    """
    if id_or_prefix in tasks:
        return id_or_prefix
    matches = [tid for tid in tasks if tid.startswith(id_or_prefix)]
    if len(matches) == 0:
        raise KeyError(f"Task not found: {id_or_prefix}")
    if len(matches) > 1:
        raise KeyError(
            f"Ambiguous task prefix '{id_or_prefix}': matches {len(matches)} tasks"
        )
    return matches[0]


def _task_record_to_dict(task: TaskRecord) -> dict[str, Any]:
    data = asdict(task)
    data["status"] = task.status.value
    for call in data.get("tool_calls", []):
        if isinstance(call.get("status"), TaskToolStatus):
            call["status"] = call["status"].value
    return data


def _task_record_from_dict(data: dict[str, Any]) -> TaskRecord:
    status = TaskStatus(data["status"])
    checklist_data = data.get("checklist") or {}
    checklist_items_raw = checklist_data.get("items", [])
    checklist = TaskChecklistState(
        items=[TaskChecklistItem(**item) for item in checklist_items_raw],
        completion_pct=checklist_data.get("completion_pct", 0),
        in_progress_id=checklist_data.get("in_progress_id"),
        updated_at=checklist_data.get("updated_at"),
    )
    gates = [TaskGateRecord(**g) for g in data.get("gates", [])]
    attempts = [TaskAttemptRecord(**a) for a in data.get("attempts", [])]
    artifacts = [TaskArtifactRef(**a) for a in data.get("artifacts", [])]
    github_events = [TaskGithubEvent(**e) for e in data.get("github_events", [])]
    tool_calls_raw = data.get("tool_calls", [])
    tool_calls = []
    for item in tool_calls_raw:
        status_val = item["status"]
        if isinstance(status_val, str):
            item = {**item, "status": TaskToolStatus(status_val)}
        tool_calls.append(TaskToolCallSummary(**item))
    timeline = [TaskTimelineEntry(**entry) for entry in data.get("timeline", [])]

    return TaskRecord(
        schema_version=data.get("schema_version", CURRENT_TASK_SCHEMA_VERSION),
        id=data["id"],
        prompt=data["prompt"],
        model=data["model"],
        workspace=data["workspace"],
        mode=data["mode"],
        allow_shell=data["allow_shell"],
        trust_mode=data["trust_mode"],
        auto_approve=data.get("auto_approve", False),
        status=status,
        created_at=data["created_at"],
        started_at=data.get("started_at"),
        ended_at=data.get("ended_at"),
        duration_ms=data.get("duration_ms"),
        result_summary=data.get("result_summary"),
        result_detail_path=data.get("result_detail_path"),
        error=data.get("error"),
        thread_id=data.get("thread_id"),
        turn_id=data.get("turn_id"),
        runtime_event_count=data.get("runtime_event_count", 0),
        checklist=checklist,
        gates=gates,
        attempts=attempts,
        artifacts=artifacts,
        github_events=github_events,
        tool_calls=tool_calls,
        timeline=timeline,
    )


def _load_state(
    tasks_dir: Path, queue_path: Path
) -> tuple[dict[str, TaskRecord], deque[str]]:
    """Load persisted tasks + queue, converting Running → Queued on recovery.

    Mirrors Rust `load_state()` (task_manager.rs:1474-1543).
    """
    tasks: dict[str, TaskRecord] = {}
    if tasks_dir.exists():
        for path in sorted(tasks_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            task = _task_record_from_dict(data)
            if task.schema_version > CURRENT_TASK_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Task schema v{task.schema_version} is newer than supported"
                    f" v{CURRENT_TASK_SCHEMA_VERSION}"
                )
            if task.status is TaskStatus.RUNNING:
                if _is_stale_running_task(task):
                    now = _utc_now_iso()
                    task.status = TaskStatus.FAILED
                    task.started_at = task.started_at
                    task.ended_at = now
                    task.error = STALE_RESTART_ERROR
                    task.timeline.append(
                        TaskTimelineEntry(
                            timestamp=now,
                            kind="failed",
                            summary="Stale running task marked failed on recovery",
                        )
                    )
                else:
                    task.status = TaskStatus.QUEUED
                    task.started_at = None
                    task.ended_at = None
                    task.duration_ms = None
                    task.timeline.append(
                        TaskTimelineEntry(
                            timestamp=_utc_now_iso(),
                            kind="recovered",
                            summary="Recovered from restart and re-queued",
                        )
                    )
            # Safety: if a queued task points at a workspace that no longer
            # exists on disk (common with pytest temp dirs or moved
            # projects), fail it immediately instead of looping forever on
            # restart. Without this guard, zombie tasks from old test runs
            # spawn an Engine per worker tick and starve the event loop.
            if task.status is TaskStatus.QUEUED:
                ws = task.workspace
                if ws and not Path(ws).exists():
                    now = _utc_now_iso()
                    task.status = TaskStatus.FAILED
                    task.error = f"workspace not found: {ws}"
                    task.ended_at = now
                    task.timeline.append(
                        TaskTimelineEntry(
                            timestamp=now,
                            kind="failed",
                            summary=f"workspace not found: {ws}",
                        )
                    )
            tasks[task.id] = task

    queue: deque[str] = deque()
    if queue_path.exists():
        with queue_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        queue = deque(data.get("queue", []))

    queue = deque(
        tid for tid in queue if tid in tasks and tasks[tid].status is TaskStatus.QUEUED
    )
    known = set(queue)
    missing = sorted(
        tid
        for tid, task in tasks.items()
        if task.status is TaskStatus.QUEUED and tid not in known
    )
    for tid in missing:
        queue.append(tid)
    return tasks, queue


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, sort_keys=False, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
