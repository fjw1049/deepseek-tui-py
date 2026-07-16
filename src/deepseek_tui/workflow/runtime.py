"""Workflow runtime and agent runner.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

_LOG = logging.getLogger(__name__)

from deepseek_tui.tools.subagent import SubAgentManager
from deepseek_tui.workflow.models import (
    ANALYSIS_ONLY_TOOLS,
    StepOutput,
    WAIT_TIMEOUT_MS,
    WorkflowAbortedError,
    WorkflowFailedError,
    WorkflowPolicy,
    WorkflowRunContext,
    WorkflowRunResult,
    WorkflowSnapshot,
)
from deepseek_tui.workflow.scheduler import schedule_workflow

__all__ = [
    "DeepSeekAgentRunner",
    "WorkflowAbortedError",
    "WorkflowFailedError",
    "WorkflowRunner",
    "render_workflow_text",
    "run_workflow",
]


def _recompute_snapshot(snapshot: WorkflowSnapshot) -> WorkflowSnapshot:
    running = sum(1 for a in snapshot.agents if a.status == "running")
    done = sum(1 for a in snapshot.agents if a.status == "done")
    errors = sum(1 for a in snapshot.agents if a.status == "error")
    return replace(
        snapshot,
        agent_count=len(snapshot.agents),
        running_count=running,
        done_count=done,
        error_count=errors,
    )


async def run_workflow(
    spec: Any,
    *,
    runner: WorkflowRunner,
    cancel_event: asyncio.Event | None = None,
    manager: SubAgentManager | None = None,
    on_log: Callable[[str], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
    on_progress: Callable[[WorkflowSnapshot], None] | None = None,
    on_checkpoint: Callable[[WorkflowRunContext, WorkflowSnapshot, list[str]], None]
    | None = None,
    task: str = "",
    initial_outputs: dict[str, StepOutput] | None = None,
    skip_step_ids: set[str] | None = None,
    cwd: Path | None = None,
    initial_graph: Any | None = None,
    run_id: str | None = None,
) -> WorkflowRunResult:
    """Run a workflow via the DAG ready-set scheduler (v1 phases compile to DAG)."""
    return await schedule_workflow(
        spec,
        runner=runner,
        cancel_event=cancel_event,
        manager=manager,
        on_log=on_log,
        on_phase=on_phase,
        on_progress=on_progress,
        on_checkpoint=on_checkpoint,
        task=task,
        initial_outputs=initial_outputs,
        skip_step_ids=skip_step_ids,
        cwd=cwd,
        initial_graph=initial_graph,
        run_id=run_id,
    )


def render_workflow_text(snapshot: WorkflowSnapshot, *, completed: bool = False) -> str:
    header = "Workflow completed" if completed else "Workflow running"
    state = ""
    if snapshot.error_count:
        state = f", {snapshot.error_count} errors"
    elif snapshot.running_count:
        state = f", {snapshot.running_count} running"
    lines = [
        header,
        f"◆ Workflow: {snapshot.name} ({snapshot.done_count}/{snapshot.agent_count} done{state})",
    ]
    if snapshot.nodes:
        for node in snapshot.nodes[-12:]:
            icon = {
                "running": "●",
                "done": "✓",
                "error": "✗",
                "skipped": "-",
                "queued": "○",
            }.get(node.status, "○")
            gen = " *" if node.generated else ""
            lines.append(f"  {icon} {node.id} ({node.type}){gen}")
    else:
        for phase_id in snapshot.phases:
            agents = [a for a in snapshot.agents if a.phase_id == phase_id]
            if not agents:
                continue
            done = sum(1 for a in agents if a.status == "done")
            lines.append(f"  ✓ {phase_id} {done}/{len(agents)}")
            for agent in agents[-6:]:
                icon = {
                    "running": "●",
                    "done": "✓",
                    "error": "✗",
                    "skipped": "-",
                }.get(agent.status, "○")
                lines.append(f"    {icon} {agent.label}")
    for log in snapshot.logs[-2:]:
        lines.append(f"  log: {log}")
    return "\n".join(lines)


from deepseek_tui.tools.subagent import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentRuntime,
    SubAgentStatusKind,
    SubAgentType,
)
from deepseek_tui.workflow.models import WorkflowAbortedError, make_step_output


class WorkflowRunner(Protocol):
    async def run(
        self,
        *,
        prompt: str,
        label: str,
        agent_type: str,
        model: str | None,
        allowed_tools: list[str] | None,
        output_schema: dict[str, Any] | None,
        policy: WorkflowPolicy,
        cancel_event: asyncio.Event | None,
        on_agent_id: Any,
        timeout_seconds: float | None = None,
    ) -> StepOutput | None:
        ...


class DeepSeekAgentRunner:
    def __init__(
        self,
        manager: SubAgentManager,
        base_runtime: SubAgentRuntime,
        *,
        parent_depth: int = 0,
        register_spawned: Any = None,
        workspace: Path | None = None,
    ) -> None:
        self._manager = manager
        self._base_runtime = base_runtime
        self._parent_depth = parent_depth
        self._register_spawned = register_spawned
        self._workspace = workspace

    def _allowed_tools(
        self, policy: WorkflowPolicy, allowed: list[str] | None
    ) -> list[str] | None:
        if policy.approval_mode == "analysis_only":
            return sorted(ANALYSIS_ONLY_TOOLS)
        return allowed

    async def run(
        self,
        *,
        prompt: str,
        label: str,
        agent_type: str,
        model: str | None,
        allowed_tools: list[str] | None,
        output_schema: dict[str, Any] | None,
        policy: WorkflowPolicy,
        cancel_event: asyncio.Event | None,
        on_agent_id: Any = None,
        timeout_seconds: float | None = None,
    ) -> StepOutput | None:
        if cancel_event is not None and cancel_event.is_set():
            raise WorkflowAbortedError("workflow cancelled")
        parsed = SubAgentType.parse(agent_type) or SubAgentType.GENERAL
        if policy.approval_mode == "trusted_workflow":
            auto_approve: bool | None = True
        elif policy.approval_mode == "strict":
            auto_approve = False
        else:
            auto_approve = True

        request = SpawnRequest(
            prompt=prompt,
            agent_type=parsed,
            assignment=SubAgentAssignment(objective=prompt, role=label),
            allowed_tools=self._allowed_tools(policy, allowed_tools),
            model=model,
            nickname=label,
            parent_depth=self._parent_depth,
            output_schema=output_schema,
            auto_approve=auto_approve,
            workspace=self._workspace,
        )
        snap = await self._manager.spawn(request)
        if on_agent_id is not None:
            on_agent_id(snap.agent_id)
        if self._register_spawned is not None:
            self._register_spawned(snap.agent_id)

        timeout_s = (
            timeout_seconds if timeout_seconds is not None else WAIT_TIMEOUT_MS / 1000
        )
        deadline = time.monotonic() + timeout_s
        final = snap

        async def _try_cancel() -> None:
            try:
                await self._manager.cancel(snap.agent_id)
            except KeyError:
                pass

        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    await _try_cancel()
                    raise WorkflowAbortedError("workflow cancelled")
                try:
                    final = await self._manager.get_result(snap.agent_id)
                except KeyError:
                    return None
                except Exception:
                    await _try_cancel()
                    return None
                if final.status.kind is not SubAgentStatusKind.RUNNING:
                    break
                if time.monotonic() >= deadline:
                    await _try_cancel()
                    return None
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # fail-fast / gather cancel_pending cancels this Task — still
            # tell the SubAgentManager so the backend worker stops.
            await _try_cancel()
            raise

        if final.status.kind in (
            SubAgentStatusKind.FAILED,
            SubAgentStatusKind.CANCELLED,
            SubAgentStatusKind.INTERRUPTED,
        ):
            if cancel_event is not None and cancel_event.is_set():
                raise WorkflowAbortedError("workflow cancelled")
            return None
        text = final.result or ""
        structured = final.structured
        return make_step_output(text, structured)
