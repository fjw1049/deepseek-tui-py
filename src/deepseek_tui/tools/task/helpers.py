"""Shared helpers for task/PR-attempt tools: input parsing, git probes, results."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.tools.registry import ToolContext, ToolError, ToolResult
from deepseek_tui.tools.task.models import TaskRecord, TaskStatus

if TYPE_CHECKING:
    from deepseek_tui.tools.task.manager import TaskManager

_MAX_SUMMARY_CHARS = 2000


def _summarize(text: str, limit: int) -> str:
    """Summarize output text for compact display.

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
    """Heuristic failure classification.

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


def _task_context_id(context: ToolContext) -> str | None:
    """Return the enclosing durable task id, if any."""
    if isinstance(context.active_task_id, str) and context.active_task_id.strip():
        return context.active_task_id.strip()
    raw = context.metadata.get("task_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _enforce_max_task_nest_depth(
    context: ToolContext, *, action: str = "task_create"
) -> None:
    """Refuse nested durable-task enqueue (max_task_nest_depth=1)."""
    if _task_context_id(context) is None:
        return
    raise ToolError(
        f"{action} is not allowed inside a running task "
        "(max_task_nest_depth=1). Use sub-agents for nested work instead."
    )


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


def _task_result_content(action: str, task: TaskRecord) -> str:
    """Build model-visible tool content for task CRUD tools.

    The orchestrator only injects ``ToolResult.content`` into the LLM
    transcript (metadata is for UI). Status-only stubs left the model
    unable to present completed task results on follow-up turns.
    """
    lines = [f"{action}: {task.id} [{task.status.value}]"]
    if task.duration_ms is not None:
        lines.append(f"duration_ms: {task.duration_ms}")
    if task.error:
        lines.append(f"error: {_summarize(task.error, _MAX_SUMMARY_CHARS)}")
    summary = (task.result_summary or "").strip()
    if summary:
        lines.append("result:")
        lines.append(_summarize(summary, _MAX_SUMMARY_CHARS))
    elif task.timeline:
        # Prefer the final assistant text; fall back to a short timeline
        # tail so tool-heavy tasks still expose something readable.
        tail = task.timeline[-8:]
        lines.append("timeline_tail:")
        for entry in tail:
            kind = getattr(entry, "kind", "") or ""
            entry_summary = getattr(entry, "summary", "") or ""
            if entry_summary:
                lines.append(f"- [{kind}] {_summarize(entry_summary, 240)}")
    else:
        lines.append("result: (no result yet)")
    return "\n".join(lines)


def _task_result(action: str, task: TaskRecord) -> ToolResult:
    summary = task.result_summary or task.error or ""
    return ToolResult(
        success=task.status is not TaskStatus.FAILED
        and task.status is not TaskStatus.TIMED_OUT,
        content=_task_result_content(action, task),
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
            "summary": summary,
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
