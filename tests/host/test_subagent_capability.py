from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.capabilities.subagents import (
    attach_subagent_engine_bindings,
    attach_subagent_parent_cancel,
    create_subagent_manager,
    shutdown_subagent_runtime,
)
from deepseek_tui.config.models import Config, FeatureConfig, SubagentConfig
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.tools.subagent import AgentRunOutput, Mailbox, SubAgent, SubAgentManager


async def _fake_executor(
    _agent: SubAgent,
    _cancel: asyncio.Event,
) -> AgentRunOutput:
    return AgentRunOutput(text="ok", structured=None)


def test_subagent_capability_skips_when_disabled(tmp_path: Path) -> None:
    services = ServiceRegistry()
    cfg = Config(features=FeatureConfig(subagents=False))

    manager, mailbox = create_subagent_manager(
        cfg,
        services,
        workspace=tmp_path,
        state_path=tmp_path / "subagents.json",
        executor_factory=lambda: _fake_executor,
    )

    assert manager is None
    assert mailbox is None
    assert services.optional(SubAgentManager) is None


def test_subagent_capability_creates_manager_and_mailbox(tmp_path: Path) -> None:
    services = ServiceRegistry()
    cfg = Config(
        default_text_model="deepseek-test",
        max_subagents=3,
        features=FeatureConfig(subagents=True),
        subagents=SubagentConfig(max_concurrent=3),
    )

    manager, mailbox = create_subagent_manager(
        cfg,
        services,
        workspace=tmp_path,
        state_path=tmp_path / "subagents.json",
        executor_factory=lambda: _fake_executor,
    )

    assert manager is not None
    assert isinstance(mailbox, Mailbox)
    assert services.require(SubAgentManager) is manager
    assert manager.workspace == tmp_path
    assert manager.max_agents == 3
    assert manager.default_model == "deepseek-test"
    assert manager._state_path == tmp_path / "subagents.json"  # noqa: SLF001


def test_subagent_capability_caps_max_agents(tmp_path: Path) -> None:
    services = ServiceRegistry()
    cfg = Config(
        features=FeatureConfig(subagents=True),
        max_subagents=100,
    )

    manager, _mailbox = create_subagent_manager(
        cfg,
        services,
        workspace=tmp_path,
        state_path=None,
        executor_factory=lambda: _fake_executor,
    )

    assert manager is not None
    assert manager.max_agents == 20
    assert manager._state_path == tmp_path / ".deepseek" / "subagents.v1.json"  # noqa: SLF001


def test_subagent_capability_attaches_engine_bindings(tmp_path: Path) -> None:
    services = ServiceRegistry()
    cfg = Config(features=FeatureConfig(subagents=True))
    manager, mailbox = create_subagent_manager(
        cfg,
        services,
        workspace=tmp_path,
        state_path=None,
        executor_factory=lambda: _fake_executor,
    )
    cancel = asyncio.Event()
    completions: list[object] = []

    attach_subagent_engine_bindings(
        manager,
        config=cfg,
        client=AsyncMock(),
        model="deepseek-test",
        workspace=tmp_path,
        allow_shell=True,
        auto_approve=False,
        task_manager=None,
        cancel_token=cancel,
        mailbox=mailbox,
        completion_sink=completions.append,
    )

    assert manager is not None
    assert manager.loop_runtime is not None
    assert manager.loop_runtime.manager is manager
    assert manager.loop_runtime.model == "deepseek-test"
    assert manager.loop_runtime.workspace == tmp_path.resolve()
    assert manager.loop_runtime.mailbox is mailbox


def test_subagent_capability_refreshes_parent_cancel(tmp_path: Path) -> None:
    services = ServiceRegistry()
    manager, _mailbox = create_subagent_manager(
        Config(features=FeatureConfig(subagents=True)),
        services,
        workspace=tmp_path,
        state_path=None,
        executor_factory=lambda: _fake_executor,
    )
    cancel = asyncio.Event()

    attach_subagent_parent_cancel(manager, cancel)

    assert manager is not None
    assert manager._parent_cancel is cancel  # noqa: SLF001


@pytest.mark.asyncio
async def test_subagent_capability_shutdown_closes_mailbox(tmp_path: Path) -> None:
    services = ServiceRegistry()
    manager, mailbox = create_subagent_manager(
        Config(features=FeatureConfig(subagents=True)),
        services,
        workspace=tmp_path,
        state_path=None,
        executor_factory=lambda: _fake_executor,
    )

    await shutdown_subagent_runtime(manager, mailbox, owns_manager=True)

    assert mailbox is not None
    assert mailbox.is_closed()
