"""Integration tests for Subagent / Task wiring through real managers."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.tools.runtime import create_tool_runtime
from deepseek_tui.tools.subagent import (
    Mailbox,
    MailboxMessageKind,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentType,
)


class TestSubagentMailboxIntegration:
    @pytest.mark.asyncio
    async def test_spawn_attaches_mailbox_to_agent(self, tmp_path: Path):
        mailbox = Mailbox()

        async def _executor(agent, cancel):  # noqa: ANN001
            assert agent.mailbox is mailbox
            return "done"

        manager = SubAgentManager(
            workspace=tmp_path,
            mailbox=mailbox,
            executor=_executor,
        )
        spawned = await manager.spawn(
            SpawnRequest(
                prompt="check mailbox",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(objective="check mailbox"),
            )
        )
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=5000)
        final = await manager.get_result(spawned.agent_id)
        assert final.status.kind.value == "completed"
        envelopes = await mailbox.drain_available()
        kinds = [e.message.kind for e in envelopes]
        assert MailboxMessageKind.STARTED in kinds
        assert MailboxMessageKind.COMPLETED in kinds


class TestToolRuntimeIntegration:
    @pytest.mark.asyncio
    async def test_create_tool_runtime_attaches_managers(self, tmp_path: Path):
        cfg = Config(features=FeatureConfig(tasks=True, subagents=True))
        runtime = await create_tool_runtime(
            config=cfg,
            working_directory=tmp_path,
        )
        assert runtime.task_manager is not None
        assert runtime.subagent_manager is not None
        assert runtime.context.task_manager is runtime.task_manager
        assert runtime.context.subagent_manager is runtime.subagent_manager
        await runtime.shutdown()
