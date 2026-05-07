"""Parity tests for sub-agent tools (Stage 3.2).

Covers all 10 sub-agent tools wired to a real SubAgentManager.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.subagent import Mailbox, SubAgentManager
from deepseek_tui.tools.subagent_tools import (
    AgentAssignTool,
    AgentCancelTool,
    AgentCloseTool,
    AgentListTool,
    AgentResultTool,
    AgentResumeTool,
    AgentSendInputTool,
    AgentSpawnTool,
    AgentWaitTool,
    DelegateToAgentTool,
)


async def _slow_executor(_agent, cancel):
    """Finishes after 1s unless cancelled, so tests can exercise cancel/wait."""
    try:
        await asyncio.wait_for(cancel.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        return f"done: {_agent.prompt}"
    raise asyncio.CancelledError


@pytest_asyncio.fixture
async def ctx(tmp_path: Path) -> AsyncIterator[ToolContext]:
    mb = Mailbox()
    mgr = SubAgentManager(
        workspace=tmp_path,
        state_path=tmp_path / "subagents.v1.json",
        mailbox=mb,
    )
    try:
        yield ToolContext(
            working_directory=tmp_path,
            subagent_manager=mgr,
        )
    finally:
        await mgr.shutdown()


class TestAgentSpawn:
    async def test_spawn_returns_agent_id(self, ctx: ToolContext) -> None:
        result = await AgentSpawnTool().execute(
            {"prompt": "explore", "type": "explore"}, ctx
        )
        assert result.metadata["agent_id"].startswith("agent_")
        assert result.metadata["agent_type"] == "explore"

    async def test_rejects_missing_prompt(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError, match="prompt"):
            await AgentSpawnTool().execute({}, ctx)

    async def test_rejects_unknown_type(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError, match="Unknown sub-agent type"):
            await AgentSpawnTool().execute({"prompt": "x", "type": "nonsense"}, ctx)

    async def test_custom_requires_allowed_tools(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError, match="Custom sub-agents"):
            await AgentSpawnTool().execute({"prompt": "x", "type": "custom"}, ctx)

    async def test_missing_manager(self, tmp_path: Path) -> None:
        bare = ToolContext(working_directory=tmp_path)
        with pytest.raises(ToolError, match="SubAgentManager is not attached"):
            await AgentSpawnTool().execute({"prompt": "x"}, bare)


class TestAgentResultAndWait:
    async def test_blocking_result_waits_for_terminal(self, ctx: ToolContext) -> None:
        spawn = await AgentSpawnTool().execute({"prompt": "quick"}, ctx)
        aid = spawn.metadata["agent_id"]
        result = await AgentResultTool().execute(
            {"agent_id": aid, "block": True, "timeout_ms": 5000}, ctx
        )
        assert result.metadata["status"]["kind"] == "completed"

    async def test_non_blocking_returns_current(self, ctx: ToolContext) -> None:
        spawn = await AgentSpawnTool().execute({"prompt": "x"}, ctx)
        aid = spawn.metadata["agent_id"]
        result = await AgentResultTool().execute({"agent_id": aid}, ctx)
        assert result.metadata["agent_id"] == aid

    async def test_wait_all(self, ctx: ToolContext) -> None:
        a = (await AgentSpawnTool().execute({"prompt": "a"}, ctx)).metadata["agent_id"]
        b = (await AgentSpawnTool().execute({"prompt": "b"}, ctx)).metadata["agent_id"]
        result = await AgentWaitTool().execute(
            {"agent_ids": [a, b], "mode": "all", "timeout_ms": 10000}, ctx
        )
        agents = result.metadata["agents"]
        assert len(agents) == 2
        assert all(a["status"]["kind"] != "running" for a in agents)


class TestAgentCancelClose:
    async def test_cancel_running(self, tmp_path: Path) -> None:
        mgr = SubAgentManager(workspace=tmp_path, executor=_slow_executor)
        ctx = ToolContext(working_directory=tmp_path, subagent_manager=mgr)
        try:
            spawn = await AgentSpawnTool().execute({"prompt": "cancelme"}, ctx)
            aid = spawn.metadata["agent_id"]
            await asyncio.sleep(0.02)
            cancelled = await AgentCancelTool().execute({"agent_id": aid}, ctx)
            assert cancelled.metadata["status"]["kind"] == "cancelled"
        finally:
            await mgr.shutdown()

    async def test_close_removes(self, ctx: ToolContext) -> None:
        spawn = await AgentSpawnTool().execute({"prompt": "x"}, ctx)
        aid = spawn.metadata["agent_id"]
        await AgentCloseTool().execute({"agent_id": aid}, ctx)
        listing = await AgentListTool().execute({}, ctx)
        assert all(a["agent_id"] != aid for a in listing.metadata["agents"])


class TestResumeAssignSendInput:
    async def test_resume_reruns(self, ctx: ToolContext) -> None:
        spawn = await AgentSpawnTool().execute({"prompt": "ran"}, ctx)
        aid = spawn.metadata["agent_id"]
        await AgentResultTool().execute(
            {"agent_id": aid, "block": True, "timeout_ms": 3000}, ctx
        )
        resumed = await AgentResumeTool().execute({"id": aid}, ctx)
        assert resumed.metadata["status"]["kind"] == "running"

    async def test_assign_updates_objective(self, ctx: ToolContext) -> None:
        spawn = await AgentSpawnTool().execute({"prompt": "orig"}, ctx)
        aid = spawn.metadata["agent_id"]
        updated = await AgentAssignTool().execute(
            {"agent_id": aid, "objective": "new objective", "role": "fixer"}, ctx
        )
        assert updated.metadata["assignment"]["objective"] == "new objective"
        assert updated.metadata["assignment"]["role"] == "fixer"

    async def test_send_input_to_running(self, tmp_path: Path) -> None:
        mgr = SubAgentManager(workspace=tmp_path, executor=_slow_executor)
        ctx = ToolContext(working_directory=tmp_path, subagent_manager=mgr)
        try:
            spawn = await AgentSpawnTool().execute({"prompt": "listen"}, ctx)
            aid = spawn.metadata["agent_id"]
            await AgentSendInputTool().execute(
                {"agent_id": aid, "input": "hello", "interrupt": True}, ctx
            )
            # No assertion on receipt — the stub doesn't drain the queue.
            # The test guarantees the method doesn't error.
        finally:
            await mgr.shutdown()


class TestDelegateToAgent:
    async def test_delegate_spawns_and_waits(self, ctx: ToolContext) -> None:
        result = await DelegateToAgentTool().execute(
            {"prompt": "do", "type": "general", "timeout_ms": 5000}, ctx
        )
        assert result.metadata["status"]["kind"] == "completed"
        assert result.metadata["result"] is not None
