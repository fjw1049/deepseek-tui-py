"""ExecPolicyEngine wiring from Config.approval_policy."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.app_server.runtime_threads import CreateThreadRequest, RuntimeThreadManagerConfig
from deepseek_tui.app_server.thread_manager import RuntimeThreadManager
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.execpolicy.engine import ExecPolicyEngine, exec_policy_for_config
from deepseek_tui.tools.base import ToolCapability
from deepseek_tui.tools.context import ToolContext


def test_exec_policy_for_config_reads_approval_policy() -> None:
    cfg = Config(approval_policy="never")
    engine = exec_policy_for_config(cfg)
    assert engine.approval_policy == "never"


def test_exec_policy_never_blocks_high_risk_tools() -> None:
    engine = ExecPolicyEngine(approval_policy="never")
    req = engine.evaluate("write_file", [ToolCapability.WRITES_FILES])
    assert req is not None
    assert "never" in req.reason


@pytest.mark.asyncio
async def test_runtime_engine_uses_config_approval_policy(
    runtime_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, ExecPolicyEngine] = {}

    async def fake_create(**kwargs: object) -> SimpleNamespace:
        policy = kwargs.get("exec_policy")
        assert isinstance(policy, ExecPolicyEngine)
        captured["policy"] = policy
        wd = kwargs.get("working_directory", Path("."))
        ctx = ToolContext(working_directory=Path(wd))  # type: ignore[arg-type]
        return SimpleNamespace(tool_context=ctx, run=AsyncMock())

    monkeypatch.setattr("deepseek_tui.engine.engine.Engine.create", fake_create)

    tasks_dir = runtime_data_dir / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    mgr = RuntimeThreadManager(
        config=Config(
            approval_policy="auto",
            features=FeatureConfig(mcp=False, tasks=False, subagents=False, automations=False),
        ),
        workspace=runtime_data_dir,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tasks_dir),
        llm_client=object(),
    )
    thread = await mgr.create_thread(CreateThreadRequest())
    await mgr._ensure_engine_loaded(thread)

    assert captured["policy"].approval_policy == "auto"

    async with mgr._active_lock:
        state = mgr._active.get(thread.id)
        assert state is not None
        state.engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await state.engine_task
        mgr._active.pop(thread.id, None)
