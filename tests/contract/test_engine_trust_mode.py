"""Engine.tool_context.trust_mode wiring for HTTP threads."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.app_server.runtime_threads import (
    CreateThreadRequest,
    RuntimeThreadManagerConfig,
)
from deepseek_tui.app_server.thread_manager import RuntimeThreadManager
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.tools.context import ToolContext


@pytest.mark.asyncio
async def test_ensure_engine_applies_thread_trust_mode(
    runtime_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    async def fake_create(**kwargs: object) -> SimpleNamespace:
        wd = kwargs.get("working_directory", Path("."))
        ctx = ToolContext(working_directory=Path(wd))  # type: ignore[arg-type]
        return SimpleNamespace(tool_context=ctx, run=AsyncMock())

    monkeypatch.setattr("deepseek_tui.engine.engine.Engine.create", fake_create)

    tasks_dir = runtime_data_dir / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    mgr = RuntimeThreadManager(
        config=Config(
            features=FeatureConfig(mcp=False, tasks=False, subagents=False, automations=False)
        ),
        workspace=runtime_data_dir,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tasks_dir),
        llm_client=object(),
    )
    thread = await mgr.create_thread(CreateThreadRequest(trust_mode=True))
    await mgr._ensure_engine_loaded(thread)

    async with mgr._active_lock:
        state = mgr._active.get(thread.id)
        assert state is not None
        assert state.engine.tool_context.trust_mode is True
        state.engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await state.engine_task
        mgr._active.pop(thread.id, None)
