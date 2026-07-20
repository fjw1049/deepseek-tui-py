"""Regression tests for stage-A subagent fixes (allowlist, model, background)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.config.models import Config, SubagentConfig
from deepseek_tui.engine.handle import SendMessageOp
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, StreamEvent, StreamTextDelta
from deepseek_tui.tools.registry import ToolContext, build_subagent_registry
from deepseek_tui.tools.subagent import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentType,
    get_real_subagent_executor,
)
from deepseek_tui.tools.subagent.tools import AgentSpawnTool, _spawn_config
from deepseek_tui.tools.subagent.types import resolve_subagent_model


def test_explore_allowlist_excludes_write_and_shell() -> None:
    tools = SubAgentType.EXPLORE.allowed_tools()
    assert tools is not None
    assert "read_file" in tools
    assert "grep_files" in tools
    assert "write_file" not in tools
    assert "edit_file" not in tools
    assert "exec_shell" not in tools
    assert "agent_spawn" not in tools


def test_plan_allowlist_has_plan_tools_without_shell() -> None:
    tools = SubAgentType.PLAN.allowed_tools()
    assert tools is not None
    assert "update_plan" in tools
    assert "checklist_write" in tools
    assert "exec_shell" not in tools
    assert "write_file" not in tools


def test_build_subagent_registry_applies_type_allowlist() -> None:
    registry = build_subagent_registry(
        Config(),
        allowed_tools=sorted(SubAgentType.EXPLORE.allowed_tools() or ()),
    )
    assert registry.contains("read_file")
    assert not registry.contains("write_file")
    assert not registry.contains("exec_shell")


def test_resolve_subagent_model_priority() -> None:
    cfg = Config(
        subagents=SubagentConfig(
            explorer_model="from-field",
            worker_model="worker",
            review_model="reviewer",
            models={"explore": "from-map"},
        )
    )
    assert resolve_subagent_model(SubAgentType.EXPLORE, cfg) == "from-map"
    assert resolve_subagent_model(SubAgentType.PLAN, cfg) == "from-field"
    assert resolve_subagent_model(SubAgentType.IMPLEMENTER, cfg) == "worker"
    assert resolve_subagent_model(SubAgentType.REVIEW, cfg) == "reviewer"
    assert resolve_subagent_model(SubAgentType.GENERAL, cfg) is None


def test_spawn_config_falls_back_to_manager_loop_runtime(tmp_path: Path) -> None:
    """Parent Engine path has no metadata['subagent_runtime'] — use manager."""
    cfg = Config(subagents=SubagentConfig(explorer_model="explore-model-x"))
    manager = SubAgentManager(workspace=tmp_path, default_model="fallback")
    manager.attach_loop_runtime(
        SubAgentRuntime(
            manager=manager,
            client=AsyncMock(),
            model="fallback",
            config=cfg,
            workspace=tmp_path,
        )
    )
    ctx = ToolContext(
        working_directory=tmp_path,
        subagent_manager=manager,
        metadata={},  # parent path
    )
    assert _spawn_config(ctx) is cfg
    assert resolve_subagent_model(SubAgentType.EXPLORE, _spawn_config(ctx)) == (
        "explore-model-x"
    )


@pytest.mark.asyncio
async def test_agent_spawn_uses_per_type_model_on_parent_path(
    tmp_path: Path,
) -> None:
    cfg = Config(subagents=SubagentConfig(explorer_model="explore-model-y"))
    manager = SubAgentManager(
        workspace=tmp_path,
        default_model="fallback-def",
        executor=AsyncMock(return_value="ok"),
    )
    manager.attach_loop_runtime(
        SubAgentRuntime(
            manager=manager,
            client=AsyncMock(),
            model="fallback-def",
            config=cfg,
            workspace=tmp_path,
        )
    )
    ctx = ToolContext(
        working_directory=tmp_path,
        subagent_manager=manager,
        metadata={},
    )
    result = await AgentSpawnTool().execute(
        {"prompt": "map auth", "type": "explore"},
        ctx,
    )
    assert result.success
    agent_id = result.metadata["agent_id"]
    snap = await manager.get_result(agent_id)
    assert snap.model == "explore-model-y"


@pytest.mark.asyncio
async def test_running_foreground_count_excludes_background(tmp_path: Path) -> None:
    async def _slow(agent, cancel):  # noqa: ANN001
        await asyncio.sleep(60)
        return "never"

    manager = SubAgentManager(
        workspace=tmp_path,
        executor=_slow,
        default_model="deepseek-chat",
    )
    await manager.spawn(
        SpawnRequest(
            prompt="fg",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="fg"),
            background=False,
        )
    )
    await manager.spawn(
        SpawnRequest(
            prompt="bg",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="bg"),
            background=True,
        )
    )
    assert manager.running_count() == 2
    assert manager.running_foreground_count() == 1
    # Cleanup
    for snap in manager.list_agents():
        await manager.cancel(snap.agent_id)


class _ScriptedClient(LLMClient):
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        self._scripts = scripts
        self.calls = 0
        self.requests: list[MessageRequest] = []

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        script = self._scripts[min(self.calls, len(self._scripts) - 1)]
        self.calls += 1
        for event in script:
            yield event


@pytest.mark.asyncio
async def test_explore_loop_does_not_expose_write_tools(tmp_path: Path) -> None:
    report = (
        "### SUMMARY\nok\n\n### EVIDENCE\nNone.\n\n### CHANGES\nNone.\n\n"
        "### RISKS\nNone.\n\n### BLOCKERS\nNone."
    )
    client = _ScriptedClient(
        [[StreamTextDelta(text=report), StreamDone(usage=None)]]
    )
    manager = SubAgentManager(
        workspace=tmp_path,
        mailbox=None,
        executor=get_real_subagent_executor(),
        default_model="deepseek-chat",
    )
    manager.attach_loop_runtime(
        SubAgentRuntime(
            manager=manager,
            client=client,
            model="deepseek-chat",
            config=Config(),
            workspace=tmp_path,
            auto_approve=True,
        )
    )
    snap = await manager.spawn(
        SpawnRequest(
            prompt="explore only",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="explore only"),
        )
    )
    for _ in range(100):
        cur = await manager.get_result(snap.agent_id)
        if cur.status.kind.value != "running":
            break
        await asyncio.sleep(0.02)
    assert client.requests
    tool_names = {t["function"]["name"] for t in (client.requests[0].tools or [])}
    assert "read_file" in tool_names
    assert "write_file" not in tool_names
    assert "exec_shell" not in tool_names


@pytest.mark.asyncio
async def test_background_completion_wakes_idle_parent(engine_ctx: tuple) -> None:
    engine, handle = engine_ctx
    manager = engine.tool_context.subagent_manager
    assert manager is not None

    async def _fast(agent, cancel):  # noqa: ANN001
        await asyncio.sleep(0.05)
        return (
            "### SUMMARY\nbg done\n\n### EVIDENCE\nNone.\n\n### CHANGES\nNone.\n\n"
            "### RISKS\nNone.\n\n### BLOCKERS\nNone."
        )

    manager._executor = _fast  # noqa: SLF001
    assert not handle.is_turn_active()

    await manager.spawn(
        SpawnRequest(
            prompt="bg work",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="bg work"),
            background=True,
        )
    )

    op = await asyncio.wait_for(handle.next_op(), timeout=3.0)
    assert isinstance(op, SendMessageOp)
    assert op.hidden is True
    assert op.internal_kind == "subagent_background_done"
    assert "subagent.done" in op.content
