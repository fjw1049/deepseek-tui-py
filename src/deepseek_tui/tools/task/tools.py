"""Durable task tools — thin wrappers over :class:`TaskManager`.

All tools delegate to
``context.task_manager``.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.task.helpers import (
    _MAX_SUMMARY_CHARS,
    _classify_gate_failure,
    _enforce_max_task_nest_depth,
    _forward_to_task_manager,
    _optional_bool,
    _optional_int,
    _optional_string,
    _optional_task_id_from_input,
    _require_manager,
    _require_string,
    _task_id_from_input,
    _task_result,
)
from deepseek_tui.tools.task.models import (
    NewTaskRequest,
    TaskArtifactRef,
    TaskGateRecord,
    TaskTimelineEntry,
)
from deepseek_tui.tools.task.store import _utc_now_iso


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
            "independently and are never aggregated. Cannot be called from inside "
            "another running task (max_task_nest_depth=1); use sub-agents instead."
        )

    def input_schema(self) -> dict[str, Any]:
        # trust_mode / auto_approve are intentionally omitted: the model must
        # not self-escalate privileges. Automation / runtime code can still
        # set them via NewTaskRequest when enqueueing tasks programmatically.
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string"},
                "workspace": {"type": "string"},
                "mode": {"type": "string", "enum": ["agent", "plan", "yolo"]},
                "allow_shell": {"type": "boolean"},
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
        _enforce_max_task_nest_depth(context)
        manager = _require_manager(context)
        prompt = _require_string(input_data, "prompt")
        origin_thread = context.metadata.get("runtime_thread_id")
        req = NewTaskRequest(
            prompt=prompt,
            model=_optional_string(input_data, "model"),
            workspace=_optional_string(input_data, "workspace"),
            mode=_optional_string(input_data, "mode"),
            allow_shell=_optional_bool(input_data, "allow_shell"),
            trust_mode=False,
            auto_approve=False,
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
        lines = [f"{len(payload)} task(s):"]
        for item in payload:
            tid = item.get("id", "?")
            status = item.get("status", "?")
            prompt = (item.get("prompt_summary") or "").strip()
            result = (item.get("result_summary") or item.get("error") or "").strip()
            line = f"- {tid} [{status}]"
            if prompt:
                line += f" prompt={prompt}"
            if result:
                line += f" result={result}"
            lines.append(line)
        return ToolResult(
            success=True,
            content="\n".join(lines) if payload else "0 task(s)",
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
        # Persist durable stop for workflow-detach jobs so a crash mid-cancel
        # still prevents the next driver from continuing the run.
        try:
            from deepseek_tui.workflow.detach import parse_detach_prompt
            from deepseek_tui.workflow.store import write_stop_intent

            parsed = parse_detach_prompt(task.prompt)
            if parsed is not None:
                write_stop_intent(
                    parsed["run_id"],
                    workspace=Path(parsed["workspace"]),
                )
        except Exception:  # noqa: BLE001 — cancel already succeeded
            pass
        return _task_result("task_cancel", task)


class TaskResumeTool(ToolSpec):
    def name(self) -> str:
        return "task_resume"

    def description(self) -> str:
        return (
            "Resume a cancelled, timed_out, or failed durable task from its "
            "transcript checkpoint (or Workflow checkpoint for detach jobs). "
            "Re-queues the same task id — do not task_create a duplicate."
        )

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
            task = await manager.resume_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc
        return _task_result("task_resume", task)


class TaskGateRunTool(ToolSpec):
    """Execute a verification gate command and record the result.

    Runs the command,
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
        cwd_raw = _optional_string(input_data, "cwd")
        # Keep the working directory inside the workspace — resolve_path
        # raises on escape attempts (e.g. cwd="../..").
        cwd = str(context.resolve_path(cwd_raw)) if cwd_raw else str(
            context.working_directory
        )
        timeout_ms = _optional_int(input_data, "timeout_ms") or self._DEFAULT_TIMEOUT_MS
        timeout_ms = min(timeout_ms, self._MAX_TIMEOUT_MS)

        from deepseek_tui.tools.shell import check_command_policy, spawn_sandboxed_shell

        refusal = check_command_policy(command, context)
        if refusal is not None:
            return refusal

        # Execute the command (sandboxed, same path as ExecShellTool)
        start = _time.monotonic()
        timed_out = False
        spawn_error: str | None = None
        proc: asyncio.subprocess.Process | None = None
        try:
            proc, _exec_env = await spawn_sandboxed_shell(
                command, Path(cwd), context, timeout_ms
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
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
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
