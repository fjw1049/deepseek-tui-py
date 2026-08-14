"""Integration tests for Subagent / Task wiring through real managers."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, FeatureConfig, ProviderConfig
from deepseek_tui.tools.runtime import build_subagent_manager, create_tool_runtime
from deepseek_tui.tools.subagent import (
    Mailbox,
    MailboxMessageKind,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentType,
)
from deepseek_tui.tools.task import NewTaskRequest


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

    @pytest.mark.asyncio
    async def test_task_default_model_follows_provider(self, tmp_path: Path):
        """Cron/tasks with model=None must use the active provider model."""
        cfg = Config(
            provider="volcengine-ark",
            features=FeatureConfig(tasks=True, subagents=False, mcp=False),
            providers={
                "volcengine-ark": ProviderConfig(
                    api_key="test-key",
                    model="glm-5.2",
                    base_url="https://ark.example/api/coding/v3",
                )
            },
        )
        runtime = await create_tool_runtime(
            config=cfg,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "tasks",
        )
        assert runtime.task_manager is not None
        task = await runtime.task_manager.add_task(
            NewTaskRequest(prompt="cron report", model=None)
        )
        assert task.model == "glm-5.2"
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_subagent_default_model_follows_provider(self, tmp_path: Path):
        """Subagent spawn with no model must use provider model."""
        cfg = Config(
            provider="volcengine-ark",
            features=FeatureConfig(tasks=False, subagents=True, mcp=False),
            providers={
                "volcengine-ark": ProviderConfig(
                    api_key="test-key",
                    model="glm-5.2",
                    base_url="https://ark.example/api/coding/v3",
                )
            },
        )
        manager, mailbox = build_subagent_manager(
            cfg, tmp_path, state_path=tmp_path / "subagents.json"
        )
        assert manager is not None
        assert mailbox is not None
        assert manager.default_model == "glm-5.2"
        spawned = await manager.spawn(
            SpawnRequest(
                prompt="explore",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(objective="explore"),
                model=None,
            )
        )
        agent = manager._agents[spawned.agent_id]  # noqa: SLF001
        assert agent.model == "glm-5.2"
