"""Integration tests for RLM / Subagent / Task wiring through real managers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.rlm import RlmTool
from deepseek_tui.tools.runtime import create_tool_runtime
from deepseek_tui.tools.subagent import (
    Mailbox,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentType,
)
from deepseek_tui.tools.subagent import MailboxMessageKind
from deepseek_tui.tools.task import (
    NewTaskRequest,
    TaskManager,
    TaskManagerConfig,
)
from deepseek_tui.tools.task import TaskGateRunTool


class TestEngineRlmWiring:
    @pytest.mark.asyncio
    async def test_engine_create_wires_rlm_client(self, tmp_path: Path):
        cfg = Config(
            features=FeatureConfig(tasks=True, subagents=True),
            default_text_model="deepseek-v4-pro",
        )
        handle = EngineHandle()
        client = AsyncMock()
        engine = await Engine.create(
            handle=handle,
            client=client,
            config=cfg,
            working_directory=tmp_path,
            default_model="deepseek-v4-pro",
        )
        rlm = engine.tool_registry.get("rlm")
        assert isinstance(rlm, RlmTool)
        assert rlm._client is client
        assert rlm._root_model == "deepseek-v4-pro"
        if engine.tool_runtime is not None:
            await engine.tool_runtime.shutdown()


class TestTaskGateRunIntegration:
    @pytest.mark.asyncio
    async def test_gate_run_persists_via_record_tool_metadata(self, tmp_path: Path):
        async def _stub(task, cancel):  # noqa: ANN001
            from deepseek_tui.tools.task import TaskExecutionResult

            return TaskExecutionResult(summary="ok")

        cfg = TaskManagerConfig(data_dir=tmp_path, default_workspace=tmp_path)
        manager = TaskManager(cfg, executor=_stub)
        await manager.start()
        task = await manager.add_task(NewTaskRequest(prompt="verify build"))
        ctx = ToolContext(
            working_directory=tmp_path,
            task_manager=manager,
            active_task_id=task.id,
        )

        tool = TaskGateRunTool()
        result = await tool.execute(
            {"gate": "custom", "command": "echo gate_ok"},
            ctx,
        )
        assert result.success is True

        # record_tool_metadata runs fire-and-forget — give the loop a tick.
        await asyncio.sleep(0.05)
        updated = await manager.get_task(task.id)
        assert len(updated.gates) == 1
        assert updated.gates[0].status == "passed"
        assert "gate_ok" in (updated.gates[0].summary or "")
        assert len(updated.artifacts) >= 1
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_gate_run_without_task_id_still_executes(self, tmp_path: Path):
        async def _stub(task, cancel):  # noqa: ANN001
            from deepseek_tui.tools.task import TaskExecutionResult

            return TaskExecutionResult(summary="ok")

        cfg = TaskManagerConfig(data_dir=tmp_path, default_workspace=tmp_path)
        manager = TaskManager(cfg, executor=_stub)
        await manager.start()
        ctx = ToolContext(working_directory=tmp_path, task_manager=manager)

        result = await TaskGateRunTool().execute(
            {"gate": "custom", "command": "echo standalone"},
            ctx,
        )
        assert result.success is True
        assert "task_updates" not in result.metadata
        await manager.shutdown()


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
        rlm = runtime.registry.get("rlm")
        assert isinstance(rlm, RlmTool)
        assert rlm._client is None  # wired later by Engine.create
        await runtime.shutdown()
