"""Durable task tools — thin wrappers over :class:`TaskManager`.

The task surface is four tools that together manage all three kinds of
background entities:

- ``task_create`` — enqueue a durable task (or resume one via ``resume=``).
- ``task_list``   — aggregate snapshot: durable tasks + sub-agents +
  background shell processes.
- ``task_output`` — unified read: task record/artifacts, sub-agent result
  (blocking or not), background process output.
- ``task_stop``   — unified stop: cancel a task, a sub-agent, or a
  background process.

Retired names (``task_read`` / ``task_cancel`` / ``task_resume`` /
``task_shell_start`` / ``task_shell_wait``) are forwarded at the execution
layer — see ``engine.dispatch.normalize_legacy_tool_call``. The gate-failure
classification heuristic stays in :mod:`.helpers` (implementation layer,
decision D3) but is no longer exposed as a tool.
"""

from __future__ import annotations

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
    _enforce_max_task_nest_depth,
    _optional_int,
    _optional_string,
    _require_manager,
    _require_string,
    _task_result,
)
from deepseek_tui.tools.task.models import (
    NewTaskRequest,
    TaskArtifactRef,
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
            "TASKS panel (read later via task_output) — it does NOT come back into "
            "this turn. Use ONLY for long-running work the user will not wait for "
            "here. If you need to WAIT for the result, AGGREGATE several results, "
            "or report back in this reply (e.g. 'benchmark X and Y and summarize'), "
            "use sub-agents instead (agent tool: action=\"spawn\" + action=\"wait\"). "
            "Never split one combined-report request into multiple tasks — they run "
            "independently and are never aggregated. Cannot be called from inside "
            "another running task (max_task_nest_depth=1); use sub-agents instead. "
            "Alternatively, pass 'resume' with a task id (and no 'prompt' — the "
            "two are mutually exclusive) to re-queue a cancelled, timed_out, or "
            "failed task from its transcript checkpoint, keeping the same task "
            "id — do not create a duplicate."
        )

    def input_schema(self) -> dict[str, Any]:
        # trust_mode / auto_approve / mode / allow_shell are intentionally
        # omitted: the model must not self-escalate privileges. Automation /
        # runtime code can still set them via NewTaskRequest when enqueueing
        # tasks programmatically.
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "The task instruction, written self-contained: the "
                        "durable task starts with no conversation context, "
                        "so include goal, relevant paths, and success "
                        "criteria."
                    ),
                },
                "resume": {
                    "type": "string",
                    "description": (
                        "Resume a cancelled/timed_out/failed task by id from "
                        "its transcript checkpoint. Mutually exclusive with "
                        "'prompt' — pass only one."
                    ),
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Model id for the task; omit to use the session's "
                        "current model."
                    ),
                },
                "workspace": {
                    "type": "string",
                    "description": (
                        "Workspace directory the task runs in (absolute "
                        "path). Defaults to the current workspace."
                    ),
                },
            },
            # 'prompt' stays effectively required, but 'resume' is the
            # alternative — enforced in execute(), not the schema.
            "required": [],
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
        resume_id = _optional_string(input_data, "resume")
        if resume_id is not None:
            if _optional_string(input_data, "prompt") is not None:
                raise ToolError(
                    "'resume' is mutually exclusive with 'prompt' — pass only one"
                )
            try:
                task = await manager.resume_task(resume_id)
            except KeyError as exc:
                raise ToolError(str(exc)) from exc
            except RuntimeError as exc:
                raise ToolError(str(exc)) from exc
            return _task_result("task_create", task)
        _enforce_max_task_nest_depth(context)
        prompt = _require_string(input_data, "prompt")
        origin_thread = context.metadata.get("runtime_thread_id")
        workspace = self._resolve_workspace(input_data, context)
        # Tasks inherit the session's live auto-approve flag (written by the
        # engine per turn; the Workbench thread manager writes it too). When
        # the session is not auto-approving, the task must not silently gain
        # it: the executor bridges tool approvals onto the origin thread, or
        # denies them when no bridge is wired.
        session_auto = context.metadata.get("session_auto_approve")
        auto_approve = session_auto if isinstance(session_auto, bool) else False
        req = NewTaskRequest(
            prompt=prompt,
            model=_optional_string(input_data, "model"),
            workspace=workspace,
            # mode / allow_shell are deliberately NOT taken from model input
            # (they are not in the schema): the task inherits the manager's
            # defaults instead of model-chosen privilege escalation.
            trust_mode=False,
            auto_approve=auto_approve,
            thread_id=origin_thread if isinstance(origin_thread, str) else None,
        )
        try:
            task = await manager.add_task(req)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return _task_result("task_create", task)

    @staticmethod
    def _resolve_workspace(
        input_data: dict[str, Any], context: ToolContext
    ) -> str | None:
        """Resolve the ``workspace`` argument against the session workspace.

        A detached task runs with the given path as its working directory,
        so the model must not point it outside the current session
        workspace. Relative paths are treated as workspace-relative; the
        session workspace itself is allowed.
        """
        raw = _optional_string(input_data, "workspace")
        if raw is None:
            return None
        base = context.working_directory.resolve()
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            raise ToolError(
                "workspace must be inside the current session workspace "
                f"({base}); got {resolved}"
            ) from None
        return str(resolved)


_TASK_KINDS = ("task", "agent", "process")


class TaskListTool(ToolSpec):
    def name(self) -> str:
        return "task_list"

    def description(self) -> str:
        return (
            "List background work of all kinds: durable tasks (newest first), "
            "sub-agents, and background shell processes. Each entry carries a "
            "'kind' field (task | agent | process); pass 'kind' to restrict "
            "to one source and 'limit' to cap the durable-task count."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Maximum durable tasks to return (newest first); "
                        "omit for all."
                    ),
                },
                "kind": {
                    "type": "string",
                    "enum": list(_TASK_KINDS),
                    "description": (
                        "Filter by kind: 'task' = durable background "
                        "tasks, 'agent' = in-session sub-agents. Omit for "
                        "both."
                    ),
                },
            },
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        kind_filter = _optional_string(input_data, "kind")
        if kind_filter is not None and kind_filter not in _TASK_KINDS:
            raise ToolError(
                f"kind must be one of: {', '.join(_TASK_KINDS)}"
            )
        limit_val = input_data.get("limit")
        limit = int(limit_val) if isinstance(limit_val, int) else None

        # Source 1: durable tasks (newest first).
        task_payload: list[dict[str, Any]] = []
        if kind_filter in (None, "task"):
            manager = _require_manager(context)
            summaries = await manager.list_tasks(limit)
            task_payload = [
                asdict(s) | {"status": s.status.value, "kind": "task"}
                for s in summaries
            ]

        # Source 2: sub-agents (prior-session archived agents excluded,
        # matching the retired agent action="list" default).
        agent_payload: list[dict[str, Any]] = []
        if kind_filter in (None, "agent"):
            sub_manager = context.subagent_manager
            if sub_manager is not None:
                from deepseek_tui.tools.subagent.tools import _result_to_json

                agent_payload = [
                    _result_to_json(snap) | {"kind": "agent"}
                    for snap in sub_manager.list_filtered(include_archived=False)
                ]

        # Source 3: in-memory background shell processes.
        process_payload: list[dict[str, Any]] = []
        if kind_filter in (None, "process"):
            from deepseek_tui.tools.shell import list_background_processes

            process_payload = [
                proc | {"kind": "process"}
                for proc in list_background_processes(context)
            ]

        lines: list[str] = []
        if kind_filter in (None, "task"):
            lines.append(f"{len(task_payload)} task(s):")
            for item in task_payload:
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
        if kind_filter in (None, "agent"):
            lines.append(f"{len(agent_payload)} agent(s):")
            for item in agent_payload:
                status = item.get("status")
                kind = status.get("kind") if isinstance(status, dict) else status
                line = f"- {item.get('agent_id', '?')} [{kind or '?'}]"
                nickname = (item.get("nickname") or "").strip()
                if nickname:
                    line += f" nickname={nickname}"
                lines.append(line)
        if kind_filter in (None, "process"):
            lines.append(f"{len(process_payload)} process(es):")
            for item in process_payload:
                line = (
                    f"- {item.get('process_id', '?')} [{item.get('status', '?')}]"
                )
                command = (item.get("command") or "").strip()
                if command:
                    line += f" command={command[:120]}"
                lines.append(line)
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "tasks": task_payload,
                "agents": agent_payload,
                "processes": process_payload,
            },
        )


class TaskOutputTool(ToolSpec):
    """Unified read for all three background-entity kinds.

    - ``task_id`` → durable task record + artifacts (in-memory miss falls
      back to the on-disk store via ``TaskManager.get_task``).
    - ``agent_id`` → sub-agent result; ``block=false`` is a non-blocking
      snapshot, ``block=true`` waits (default 180s, capped at 3600s).
    - ``process_id`` → background shell process output (peek/wait); when a
      ``task_id`` is also given the output is archived as a task artifact
      (the retired ``task_shell_wait`` behaviour).
    """

    def name(self) -> str:
        return "task_output"

    def description(self) -> str:
        return (
            "Read the output of background work: a durable task record via "
            "'task_id', a sub-agent result via 'agent_id', or a background "
            "shell process via 'process_id' (at least one required). For "
            "agents/processes, 'block': true waits for completion "
            "('timeout_ms', default 180000, max 3600000); the default "
            "non-blocking peek returns status: running for unfinished jobs, "
            "which is a status report, not the result. When collecting a "
            "finished/long-running job, pass block: true. With 'process_id' "
            "plus 'task_id', the collected output is also archived as a task "
            "artifact."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Durable task id"},
                "agent_id": {"type": "string", "description": "Sub-agent id"},
                "process_id": {
                    "type": "string",
                    "description": (
                        "Background shell process id (from exec_shell "
                        "background=true)."
                    ),
                },
                "block": {
                    "type": "boolean",
                    "description": "Block until complete (agent/process)",
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": "Wait timeout in milliseconds (agent/process)",
                },
            },
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        process_id = _optional_string(input_data, "process_id")
        agent_id = _optional_string(input_data, "agent_id")
        if process_id is not None and agent_id is not None:
            raise ToolError("pass either agent_id or process_id, not both")

        if process_id is not None:
            return await self._process_output(input_data, context, process_id)
        if agent_id is not None:
            # Sub-agent result fetch — same semantics as the retired
            # agent action="result" (block/timeout_ms clamping included).
            from deepseek_tui.tools.subagent.tools import _execute_result

            return await _execute_result(input_data, context)

        task_id = _optional_string(input_data, "task_id") or _optional_string(
            input_data, "id"
        )
        if task_id is None:
            task_id = context.active_task_id
        if task_id is None:
            raise ToolError(
                "task_output requires 'task_id', 'agent_id', or 'process_id'"
            )
        manager = _require_manager(context)
        try:
            task = await manager.get_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        result = _task_result("task_output", task)
        # Durable tasks are fire-and-forget — block cannot wait for them.
        if bool(input_data.get("block", False)):
            note = (
                "note: 'block' is ignored for durable tasks — they do not "
                "re-enter this turn. Re-call task_output later, or use "
                "task_list to check status."
            )
            meta = dict(result.metadata)
            meta["block_ignored"] = True
            return ToolResult(
                success=result.success,
                content=f"{result.content}\n{note}",
                metadata=meta,
            )
        return result

    async def _process_output(
        self,
        input_data: dict[str, Any],
        context: ToolContext,
        process_id: str,
    ) -> ToolResult:
        from deepseek_tui.tools.shell import (
            peek_background_process,
            wait_background_process,
        )
        from deepseek_tui.tools.subagent.types import (
            DEFAULT_RESULT_TIMEOUT_MS,
            MAX_RESULT_TIMEOUT_MS,
        )

        block = bool(input_data.get("block", False))
        timeout_ms = _optional_int(input_data, "timeout_ms")
        task_id = _optional_string(input_data, "task_id") or _optional_string(
            input_data, "id"
        )

        if block:
            clamped = max(
                1000,
                min(
                    MAX_RESULT_TIMEOUT_MS,
                    timeout_ms or DEFAULT_RESULT_TIMEOUT_MS,
                ),
            )
            wait_result = await wait_background_process(
                context, process_id, timeout_ms=clamped
            )
        else:
            wait_result = await peek_background_process(context, process_id)

        # Archive the collected output on the task when one is named — the
        # retired task_shell_wait behaviour.
        if task_id is not None:
            manager = _require_manager(context)
            try:
                task = await manager.get_task(task_id)
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
        if task_id is not None:
            merged_meta["task_id"] = task_id
        return ToolResult(
            success=wait_result.success,
            content=wait_result.content,
            metadata=merged_meta,
        )


class TaskStopTool(ToolSpec):
    """Unified stop for all three background-entity kinds.

    - ``task_id`` → cancel a queued/running durable task.
    - ``agent_id`` → cancel a sub-agent.
    - ``process_id`` → terminate a background shell process.
    """

    def name(self) -> str:
        return "task_stop"

    def description(self) -> str:
        return (
            "Stop background work: cancel a queued or running durable task "
            "via 'task_id', a sub-agent via 'agent_id', or a background "
            "shell process via 'process_id' (exactly one required)."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Durable task id"},
                "agent_id": {"type": "string", "description": "Sub-agent id"},
                "process_id": {
                    "type": "string",
                    "description": "Background shell process id",
                },
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
        process_id = _optional_string(input_data, "process_id")
        agent_id = _optional_string(input_data, "agent_id")
        if process_id is not None or agent_id is not None:
            # Sub-agent / background-process cancel — same semantics as the
            # retired agent action="cancel" (rejects ambiguous ids).
            from deepseek_tui.tools.subagent.tools import _execute_cancel

            return await _execute_cancel(input_data, context)

        # Require an explicit id — do not silently cancel context.active_task_id
        # (that made an empty task_stop() suicide the enclosing durable task).
        task_id = _optional_string(input_data, "task_id") or _optional_string(
            input_data, "id"
        )
        if task_id is None:
            raise ToolError(
                "task_stop requires exactly one of 'task_id', 'agent_id', "
                "or 'process_id'"
            )
        manager = _require_manager(context)
        try:
            task = await manager.cancel_task(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return _task_result("task_stop", task)
