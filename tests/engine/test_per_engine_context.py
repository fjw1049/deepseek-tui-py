"""Regression: per-engine ToolContext must inherit runtime managers.

When ``Engine.create`` reuses a shared ``ToolRuntime`` but the engine's
workspace differs from the runtime's cwd, a per-engine ``ToolContext`` is
created. Previously it was constructed bare (``ToolContext(working_directory=ws)``),
dropping ``task_manager`` / ``subagent_manager`` / ``network_policy`` /
``policy`` / ``metadata`` from the runtime context. The visible symptom was
``task_shell_start`` raising "TaskManager is not attached to this context"
on the main agent path even though ``features.tasks=true`` and the tool was
registered.

This test pins the fix: the per-engine context branches off the runtime
context (managers preserved) and carries its own ``metadata`` dict (so
per-engine writes don't mutate the shared runtime context).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.tools.runtime import create_tool_runtime


@pytest.fixture
def isolated_config() -> Config:
    """Features on, MCP off — avoids hanging MCP handshakes in tests."""
    return Config(
        features=FeatureConfig(
            tasks=True,
            subagents=True,
            mcp=False,
            automations=False,
        ),
    )


async def _make_shared_runtime(
    cfg: Config, runtime_ws: Path
):
    """A ToolRuntime owned by the caller (Engine reuses it, doesn't own it)."""
    return await create_tool_runtime(
        config=cfg,
        working_directory=runtime_ws,
        mode="agent",
        task_data_dir=runtime_ws / ".deepseek" / "tasks",
        start_mcp=False,
    )


async def test_per_engine_context_inherits_runtime_managers(
    tmp_path: Path, isolated_config: Config
):
    """A shared runtime with a *different* engine workspace must still
    expose task_manager / subagent_manager / network_policy on the
    per-engine ToolContext — otherwise task_shell_start is a guaranteed
    failure on the main agent path."""
    runtime_ws = tmp_path / "runtime_ws"
    runtime_ws.mkdir()
    engine_ws = tmp_path / "engine_ws"
    engine_ws.mkdir()

    runtime = await _make_shared_runtime(isolated_config, runtime_ws)
    handle = EngineHandle()
    try:
        assert runtime.context.task_manager is not None, "fixture precondition"
        assert runtime.context.subagent_manager is not None, "fixture precondition"

        engine = await Engine.create(
            handle=handle,
            client=AsyncMock(),
            config=isolated_config,
            working_directory=engine_ws,  # != runtime_ws → triggers per-engine ctx
            tool_runtime=runtime,
        )
        ctx = engine.tool_context

        # The fix: managers are inherited, not dropped.
        assert ctx.task_manager is runtime.context.task_manager, (
            "per-engine context dropped task_manager — task_shell_start "
            "would raise 'TaskManager is not attached'"
        )
        # Sub-agents are engine-scoped: the shared manager's single-consumer
        # Mailbox must NOT be reused across engines (cross-thread envelope
        # theft), so each engine gets its own manager + mailbox.
        assert ctx.subagent_manager is not None
        assert ctx.subagent_manager is not runtime.context.subagent_manager
        assert ctx.subagent_manager.mailbox is not runtime.mailbox
        assert ctx.network_policy is runtime.context.network_policy
        # Workspace itself must still reflect the engine's path.
        assert ctx.working_directory == engine_ws.resolve()
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
        handle.drain_events()


async def test_per_engine_context_metadata_is_isolated(
    tmp_path: Path, isolated_config: Config
):
    """Per-engine metadata writes must not leak back into the shared
    runtime context — the dict is shallow-copied, not aliased."""
    runtime_ws = tmp_path / "runtime_ws"
    runtime_ws.mkdir()
    engine_ws = tmp_path / "engine_ws"
    engine_ws.mkdir()

    runtime = await _make_shared_runtime(isolated_config, runtime_ws)
    handle = EngineHandle()
    try:
        engine = await Engine.create(
            handle=handle,
            client=AsyncMock(),
            config=isolated_config,
            working_directory=engine_ws,
            tool_runtime=runtime,
        )
        ctx = engine.tool_context

        # Simulate the orchestrator's own per-engine metadata write
        # (MEMORY_SEARCH_CALLS_KEY, MEMORY_PROVIDER_KEY, ...).
        ctx.metadata["per_engine_marker"] = "engine-only"
        assert runtime.context.metadata.get("per_engine_marker") is None, (
            "per-engine metadata write leaked into shared runtime context"
        )
        assert ctx.metadata is not runtime.context.metadata, (
            "per-engine context aliases the shared metadata dict"
        )
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
        handle.drain_events()


async def test_same_workspace_still_gets_engine_scoped_subagents(
    tmp_path: Path, isolated_config: Config
):
    """Even when engine ws == runtime ws, a shared runtime yields a
    per-engine context with an engine-owned SubAgentManager: the shared
    manager's single-consumer Mailbox cannot be safely drained by more
    than one engine's activity coordinator."""
    runtime_ws = tmp_path / "shared_ws"
    runtime_ws.mkdir()

    runtime = await _make_shared_runtime(isolated_config, runtime_ws)
    handle = EngineHandle()
    try:
        engine = await Engine.create(
            handle=handle,
            client=AsyncMock(),
            config=isolated_config,
            working_directory=runtime_ws,  # == runtime cwd
            tool_runtime=runtime,
        )
        ctx = engine.tool_context
        assert ctx is not runtime.context
        assert ctx.task_manager is runtime.context.task_manager
        assert ctx.subagent_manager is not None
        assert ctx.subagent_manager is not runtime.context.subagent_manager
        assert ctx.working_directory == runtime_ws.resolve()
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
        handle.drain_events()
