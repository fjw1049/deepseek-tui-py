"""AppRuntime Engine attach integration tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.host.engine_attach import attach_engine_shell
from deepseek_tui.host.lifecycle import PREPARED_USER_TURN_DECORATION, BeforeUserTurnContext
from deepseek_tui.tools.runtime import create_tool_runtime


@pytest.mark.asyncio
async def test_attach_engine_shell_registers_memory_lifecycle(tmp_path: Path) -> None:
    cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False))
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=tmp_path,
        start_mcp=False,
    )
    handle = EngineHandle()
    client = AsyncMock()
    engine = Engine(
        handle=handle,
        client=client,
        tool_runtime=runtime,
    )
    try:
        await attach_engine_shell(
            engine,
            config=cfg,
            client=client,
            workspace=tmp_path,
            mode="agent",
            default_model="deepseek-chat",
            handle=handle,
            tool_runtime=runtime,
        )
        observer_ids = {
            registration.id for registration in engine.lifecycle_registry.registrations()
        }
        assert "memory.before_turn" in observer_ids

        before_turn = BeforeUserTurnContext(
            thread_id="thread-1",
            turn_id="turn-1",
            user_text="hello",
            workspace=tmp_path,
            metadata=engine.tool_context.metadata,
            services=engine.tool_context.services,
        )
        await engine.lifecycle_registry.before_user_turn(before_turn)
        assert PREPARED_USER_TURN_DECORATION in before_turn.decorations
    finally:
        await engine.shutdown_session()


@pytest.mark.asyncio
async def test_handle_tool_returns_error_envelope_for_mcp_runtime_error(
    tmp_path: Path,
) -> None:
    from deepseek_tui.app_server.runtime import AppRuntime
    from deepseek_tui.mcp.config import McpServerConfig
    from deepseek_tui.mcp.manager import McpManager

    cfg = Config()
    runtime = await AppRuntime.create(config=cfg)
    assert runtime._tool_runtime is not None

    mgr = MagicMock(spec=McpManager)
    mgr.server_names = ["mock"]
    mgr._configs = {"mock": McpServerConfig(name="mock", command="echo")}
    mgr.discover_tools = AsyncMock(return_value=[])
    mgr.call_tool = AsyncMock(side_effect=RuntimeError("transport exploded"))
    runtime._tool_runtime.mcp_manager = mgr

    result = await runtime.handle_tool(
        {
            "call": {
                "name": "mcp_mock_echo",
                "arguments": {"message": "boom"},
            }
        }
    )
    assert result == {"ok": False, "error": "transport exploded"}


def test_stream_engine_events_uses_engine_composition_root() -> None:
    import inspect

    from deepseek_tui.app_server.runtime import AppRuntime

    source = inspect.getsource(AppRuntime._stream_engine_events)
    assert "Engine.create" in source
    assert "attach_engine_shell" not in source
