"""SubAgent handle and executor plumbing."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.tools.subagent.completion import AgentRunOutput
from deepseek_tui.tools.subagent.mailbox import Mailbox
from deepseek_tui.tools.subagent.types import (
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentType,
    _epoch_ms,
)

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent.manager import SubAgentRuntime


# Executor signature — takes a SubAgent handle plus cancel token.
# Forward reference — AgentRunOutput defined later in this file
SubAgentExecutor = Callable  # type: ignore[assignment]


async def _stub_executor(agent: SubAgent, cancel: asyncio.Event) -> AgentRunOutput:
    """Placeholder executor — sleeps briefly, returns synthetic summary."""
    try:
        await asyncio.wait_for(cancel.wait(), timeout=0.05)
    except asyncio.TimeoutError:
        agent.steps_taken += 1
        text = f"[stub] agent {agent.id} completed prompt '{agent.prompt[:80]}'"
        return AgentRunOutput(text=text, structured=None)
    raise asyncio.CancelledError


def get_real_subagent_executor() -> SubAgentExecutor:
    """Return the real sub-agent executor that drives Engine turn loops."""
    from deepseek_tui.engine.dispatch import real_subagent_executor

    return real_subagent_executor


class SubAgent:
    """Single sub-agent handle."""

    def __init__(
        self,
        agent_type: SubAgentType,
        prompt: str,
        assignment: SubAgentAssignment,
        model: str,
        nickname: str | None,
        allowed_tools: list[str] | None,
        session_boot_id: str,
        workspace: Path | None = None,
        spawn_depth: int = 0,
        fork_messages: list[dict[str, Any]] | None = None,
        parent_cancel: asyncio.Event | None = None,
        mailbox: Mailbox | None = None,
        loop_runtime: SubAgentRuntime | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> None:
        self.id: str = f"agent_{uuid.uuid4().hex[:8]}"
        self.agent_type = agent_type
        self.prompt = prompt
        self.assignment = assignment
        self.model = model
        self.nickname = nickname
        self.status: SubAgentStatus = SubAgentStatus.running()
        self.result: str | None = None
        self.structured_result: Any | None = None
        self.output_schema = output_schema
        self.steps_taken: int = 0
        self.started_at_ms: int = _epoch_ms()
        self.allowed_tools = allowed_tools
        self.session_boot_id = session_boot_id
        self.workspace = workspace or Path.cwd()
        self.spawn_depth = spawn_depth
        self.fork_messages = fork_messages
        self.parent_cancel = parent_cancel
        self.mailbox = mailbox
        self.loop_runtime = loop_runtime
        self.cancel_token: asyncio.Event = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.input_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    def snapshot(self) -> SubAgentResult:
        duration_ms = max(0, _epoch_ms() - self.started_at_ms)
        return SubAgentResult(
            agent_id=self.id,
            agent_type=self.agent_type,
            assignment=self.assignment,
            model=self.model,
            nickname=self.nickname,
            status=self.status,
            result=self.result,
            steps_taken=self.steps_taken,
            duration_ms=duration_ms,
            from_prior_session=False,
            structured=self.structured_result,
        )
