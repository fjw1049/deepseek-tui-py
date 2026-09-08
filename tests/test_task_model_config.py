"""Tasks inherit the active session route, not the disk default provider."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.engine.dispatch import _run_task_engine_turn
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.task import ExecutionTask, TaskManager, TaskManagerConfig
from deepseek_tui.tools.task.store import _task_record_from_dict, _task_record_to_dict
from deepseek_tui.tools.task.tools import TaskCreateTool


def endpoint_config():
    return Config(
        provider="custom",
        providers={
            "custom": ProviderConfig(
                model="custom-default",
                base_url="https://example.test/v1",
                api_key="test-secret",
                protocol="anthropic",
                extra_headers={"x-test": "header-secret"},
                timeout=45,
            )
        },
    )


async def test_create_inherits_live_session_and_persists_only_provider(tmp_path):
    cfg = endpoint_config()
    manager = TaskManager(TaskManagerConfig(data_dir=tmp_path, default_workspace=tmp_path))
    context = ToolContext(
        working_directory=tmp_path,
        task_manager=manager,
        metadata={"task_config": cfg, "task_model": "selected-model"},
    )
    result = await TaskCreateTool().execute({"prompt": "work"}, context)
    record = await manager.get_task(result.metadata["task_id"])
    assert record.model == "selected-model"
    assert record.provider == "custom"
    saved = _task_record_to_dict(record)
    assert "test-secret" not in str(saved)
    assert "header-secret" not in str(saved)
    assert _task_record_from_dict(saved).provider == "custom"
    saved.pop("provider")
    assert _task_record_from_dict(saved).provider is None
    cfg.providers["custom"].base_url = "https://changed.test"
    _, task, _ = await manager._pop_next_task()
    assert task.config.effective_provider_config().base_url == "https://example.test/v1"
    assert task.provider == "custom"
    override = await TaskCreateTool().execute({"prompt": "work", "model": "override"}, context)
    assert (await manager.get_task(override.metadata["task_id"])).model == "override"


@pytest.mark.parametrize("restored", [False, True])
async def test_executor_uses_live_or_restored_custom_route(tmp_path, monkeypatch, restored):
    cfg = endpoint_config()
    if restored:
        cfg.provider = "deepseek"
        cfg.api_key = "wrong-global-key"
        cfg.base_url = "https://api.deepseek.com"
    monkeypatch.setattr(
        "deepseek_tui.config.loader.ConfigLoader.load", lambda self: cfg if restored else Config()
    )
    captured = []

    def build(config):
        captured.append(config)
        return SimpleNamespace(close=AsyncMock())

    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", build)

    class ReachedRuntime(Exception):
        pass

    async def runtime(**kwargs):
        raise ReachedRuntime

    monkeypatch.setattr("deepseek_tui.tools.runtime.create_tool_runtime", runtime)
    task = ExecutionTask(
        id="test",
        prompt="work",
        model="selected-model",
        workspace=str(tmp_path),
        mode_label="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=False,
        provider="custom",
        config=None if restored else cfg,
    )
    with pytest.raises(ReachedRuntime):
        await _run_task_engine_turn(task, asyncio.Event())
    actual = captured[0]
    pc = actual.effective_provider_config()
    assert actual.provider == "custom"
    assert pc.model == "selected-model"
    assert pc.base_url == "https://example.test/v1"
    assert pc.api_key == "test-secret"
    assert pc.protocol == "anthropic"
    assert pc.extra_headers == {"x-test": "header-secret"}
    assert pc.timeout == 45
    assert cfg.model != "selected-model"
