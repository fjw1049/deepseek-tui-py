"""DeepSeek SubAgentManager adapter for workflow steps."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from deepseek_tui.tools.subagent.manager import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentStatusKind,
    SubAgentType,
)
from deepseek_tui.workflow.constants import ANALYSIS_ONLY_TOOLS, WAIT_TIMEOUT_MS
from deepseek_tui.workflow.models import StepOutput, WorkflowAbortedError, WorkflowPolicy
from deepseek_tui.workflow.template import make_step_output


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
    ) -> None:
        self._manager = manager
        self._base_runtime = base_runtime
        self._parent_depth = parent_depth
        self._register_spawned = register_spawned

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
    ) -> StepOutput | None:
        if cancel_event is not None and cancel_event.is_set():
            raise WorkflowAbortedError("workflow cancelled")
        parsed = SubAgentType.parse(agent_type) or SubAgentType.GENERAL
        auto_approve: bool | None = None
        if policy.approval_mode == "trusted_workflow":
            auto_approve = True
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
        )
        snap = await self._manager.spawn(request)
        if on_agent_id is not None:
            on_agent_id(snap.agent_id)
        if self._register_spawned is not None:
            self._register_spawned(snap.agent_id)

        timeout_s = WAIT_TIMEOUT_MS / 1000
        deadline = time.monotonic() + timeout_s
        final = snap
        async def _try_cancel() -> None:
            try:
                await self._manager.cancel(snap.agent_id)
            except KeyError:
                pass

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
