"""PR-attempt tools — record/list/read/preflight PR attempts on a task."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from deepseek_tui.tools.registry import (
    ToolCapability,
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.task.helpers import (
    _git_changed_files,
    _git_output,
    _git_output_bytes,
    _optional_int,
    _optional_string,
    _require_manager,
    _require_string,
    _summarize,
    _task_id_from_input,
)
from deepseek_tui.tools.task.models import TaskAttemptRecord, TaskTimelineEntry
from deepseek_tui.tools.task.store import _utc_now_iso


class PrAttemptRecordTool(ToolSpec):
    """Capture a PR attempt with git diff --binary and record it.

    Automatically
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
