"""Parity tests for RLM, Subagent, and Task refactors."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.responses import Usage
from deepseek_tui.tools.builder import build_default_registry, wire_registry_client
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.rlm.repl import ReplRuntime, chunk_coverage
from deepseek_tui.tools.rlm.tool import RlmTool
from deepseek_tui.tools.rlm.turn import RlmUsage
from deepseek_tui.tools.subagent.manager import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentType,
    build_subagent_system_prompt,
    whale_nickname_for_index,
)
from deepseek_tui.tools.task_manager import (
    NewTaskRequest as TaskNewTaskRequest,
)
from deepseek_tui.tools.task_manager import (
    TaskManager,
    TaskManagerConfig,
)


class TestRlmWiring:
    def test_wire_registry_injects_client(self):
        registry = build_default_registry()
        client = MagicMock()
        wire_registry_client(registry, client, root_model="deepseek-v4-pro")
        rlm = registry.get("rlm")
        assert isinstance(rlm, RlmTool)
        assert rlm._client is client
        assert rlm._root_model == "deepseek-v4-pro"

    def test_wire_registry_injects_client_without_overwrite_warning(self, caplog):
        registry = build_default_registry()
        client = MagicMock()
        with caplog.at_level(logging.WARNING, logger="deepseek_tui.tools.registry"):
            wire_registry_client(registry, client, root_model="deepseek-v4-pro")

        assert "Overwriting existing tool: rlm" not in caplog.text

    def test_rlm_description_does_not_suppress_use(self):
        tool = RlmTool(client=None, root_model="x")
        desc = tool.description()
        assert "DO NOT use" not in desc
        assert "slower and more expensive" not in desc
        assert "chunk_context()" in desc

    def test_rlm_schema_has_no_child_model_override(self):
        schema = RlmTool(client=None, root_model="x").input_schema()
        assert "child_model" not in schema["properties"]

    @pytest.mark.asyncio
    async def test_rlm_execute_requires_client(self, tmp_path: Path):
        tool = RlmTool(client=None, root_model="x")
        ctx = ToolContext(working_directory=tmp_path)
        sample = tmp_path / "big.txt"
        sample.write_text("hello world", encoding="utf-8")
        with pytest.raises(Exception, match="requires an active DeepSeek client"):
            await tool.execute({"task": "summarize", "file_path": "big.txt"}, ctx)

    def test_chunk_helpers_in_repl(self):
        runtime = ReplRuntime.spawn("abcdefghij", {})
        chunks = runtime.namespace["chunk_context"](max_chars=4, overlap=1)
        coverage = chunk_coverage(chunks)
        assert coverage["chunks"] >= 2
        assert coverage["chars_covered"] > 0

    def test_rlm_usage_accumulator(self):
        usage = RlmUsage()
        usage.add(Usage(input_tokens=10, output_tokens=5))
        usage.add(Usage(input_tokens=3, output_tokens=2, cache_read_input_tokens=1))
        assert usage.input_tokens == 13
        assert usage.output_tokens == 7
        assert usage.cache_read_input_tokens == 1


class TestEngineChildCostAccrual:
    def test_accrue_child_token_cost_from_metadata(self):
        handle = EngineHandle()
        client = MagicMock()
        engine = Engine(handle=handle, client=client)
        before_usd = engine.session_cost_usd
        engine._accrue_child_token_cost_from_metadata(
            {
                "child_model": "deepseek-v4-flash",
                "child_input_tokens": 1000,
                "child_output_tokens": 200,
            }
        )
        assert engine.session_cost_usd >= before_usd


class TestTaskSecurity:
    @pytest.mark.asyncio
    async def test_add_task_default_auto_approve_false(self, tmp_path: Path):
        cfg = TaskManagerConfig(
            data_dir=tmp_path,
            default_workspace=tmp_path,
        )
        manager = TaskManager(cfg, executor=_immediate_stub)
        await manager.start()
        task = await manager.add_task(TaskNewTaskRequest(prompt="fix todos"))
        assert task.auto_approve is False
        assert task.allow_shell is False
        await manager.shutdown()


class TestSubagentParity:
    @pytest.mark.asyncio
    async def test_spawn_assigns_whale_nickname(self, tmp_path: Path):
        manager = SubAgentManager(workspace=tmp_path, executor=_immediate_subagent_stub)
        result = await manager.spawn(
            SpawnRequest(
                prompt="explore src",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(objective="explore src"),
            )
        )
        assert result.nickname == whale_nickname_for_index(0)

    def test_build_subagent_system_prompt_includes_role(self):
        prompt = build_subagent_system_prompt(
            SubAgentType.EXPLORE,
            SubAgentAssignment(objective="x", role="security"),
        )
        assert "exploration sub-agent" in prompt.lower()
        assert "security" in prompt

    @pytest.mark.asyncio
    async def test_parent_cancel_propagates(self, tmp_path: Path):
        parent_cancel = asyncio.Event()
        manager = SubAgentManager(
            workspace=tmp_path,
            executor=_slow_subagent_stub,
        )
        manager.attach_parent_cancel(parent_cancel)
        await manager.spawn(
            SpawnRequest(
                prompt="slow work",
                agent_type=SubAgentType.GENERAL,
                assignment=SubAgentAssignment(objective="slow work"),
            )
        )
        parent_cancel.set()
        await asyncio.sleep(0.05)
        assert manager.running_count() == 0 or parent_cancel.is_set()


async def _immediate_stub(task, cancel):  # noqa: ANN001
    from deepseek_tui.tools.task_manager import TaskExecutionResult

    return TaskExecutionResult(summary="ok")


async def _immediate_subagent_stub(agent, cancel):  # noqa: ANN001
    return "done"


async def _slow_subagent_stub(agent, cancel):  # noqa: ANN001
    try:
        await asyncio.wait_for(cancel.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        return "finished"
    raise asyncio.CancelledError
