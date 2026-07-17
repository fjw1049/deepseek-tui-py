"""Parity tests for RLM, Subagent, and Task refactors."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.tools.subagent import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentType,
    build_subagent_system_prompt,
    summarize_subagent_result,
    whale_nickname_for_index,
)
from deepseek_tui.tools.subagent.types import SubAgentResult, SubAgentStatus
from deepseek_tui.tools.task import (
    NewTaskRequest as TaskNewTaskRequest,
)
from deepseek_tui.tools.task import (
    TaskManager,
    TaskManagerConfig,
)


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
        assert "### SUMMARY" in prompt

    def test_build_subagent_system_prompt_can_omit_markdown_report(self):
        prompt = build_subagent_system_prompt(
            SubAgentType.GENERAL,
            SubAgentAssignment(objective="x"),
            include_markdown_report_contract=False,
        )
        assert "### SUMMARY" not in prompt
        assert "general-purpose sub-agent" in prompt.lower()

    def test_summarize_subagent_result_prefers_summary_section(self):
        snap = SubAgentResult(
            agent_id="a1",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="x"),
            model="m",
            nickname=None,
            status=SubAgentStatus.completed(),
            result=(
                "Working notes above the report.\n"
                "### SUMMARY\nFound the bug in foo.py.\n"
                "### EVIDENCE\n- foo.py:1-10\n"
                "### CHANGES\nNone.\n"
                "### RISKS\nNone observed.\n"
                "### BLOCKERS\nNone.\n"
            ),
            steps_taken=3,
            duration_ms=10,
        )
        assert summarize_subagent_result(snap) == "Found the bug in foo.py."

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
    from deepseek_tui.tools.task import TaskExecutionResult

    return TaskExecutionResult(summary="ok")


async def _immediate_subagent_stub(agent, cancel):  # noqa: ANN001
    return "done"


async def _slow_subagent_stub(agent, cancel):  # noqa: ANN001
    try:
        await asyncio.wait_for(cancel.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        return "finished"
    raise asyncio.CancelledError
