"""create_thread empty-model fallback follows the active provider model."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, FeatureConfig, ProviderConfig
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeThreadManager,
    RuntimeThreadManagerConfig,
)


@pytest.mark.asyncio
async def test_create_thread_without_model_uses_provider_model(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    cfg = Config(
        provider="volcengine-ark",
        features=FeatureConfig(
            mcp=False, tasks=False, subagents=False, automations=False
        ),
        providers={
            "volcengine-ark": ProviderConfig(
                api_key="test-key",
                model="glm-5.2",
                base_url="https://ark.example/api/coding/v3",
            )
        },
    )
    mgr = RuntimeThreadManager(
        config=cfg,
        workspace=tmp_path,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tasks_dir),
        llm_client=object(),
    )
    thread = await mgr.create_thread(CreateThreadRequest())
    assert thread.model == "glm-5.2"
    assert thread.provider == "volcengine-ark"


@pytest.mark.asyncio
async def test_create_thread_explicit_model_wins(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    cfg = Config(
        provider="volcengine-ark",
        features=FeatureConfig(
            mcp=False, tasks=False, subagents=False, automations=False
        ),
        providers={
            "volcengine-ark": ProviderConfig(
                api_key="test-key",
                model="glm-5.2",
                base_url="https://ark.example/api/coding/v3",
            )
        },
    )
    mgr = RuntimeThreadManager(
        config=cfg,
        workspace=tmp_path,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tasks_dir),
        llm_client=object(),
    )
    thread = await mgr.create_thread(
        CreateThreadRequest(model="kimi-k2.6", title="First query title")
    )
    assert thread.model == "kimi-k2.6"
    assert thread.title == "First query title"
