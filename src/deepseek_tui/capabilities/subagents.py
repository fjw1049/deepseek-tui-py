"""Sub-agent capability adapter for host runtime assembly."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.config.models import Config
from deepseek_tui.host.engine_shell import EngineShell
from deepseek_tui.host.services import ServiceRegistry, ServiceScope
from deepseek_tui.tools.subagent import Mailbox, SubAgentExecutor, SubAgentManager
from deepseek_tui.tools.subagent.completion import SubAgentCompletion
from deepseek_tui.tools.subagent.manager import SubAgentRuntime

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.tools.task_manager import TaskManager

ExecutorFactory = Callable[[], SubAgentExecutor]
CompletionSink = Callable[[SubAgentCompletion], None]


def create_subagent_manager(
    config: Config,
    services: ServiceRegistry,
    *,
    workspace: Path,
    state_path: Path | None,
    executor_factory: ExecutorFactory,
) -> tuple[SubAgentManager | None, Mailbox | None]:
    if not config.features.subagents:
        return None, None

    mailbox = Mailbox()
    resolved_state_path = state_path or (workspace / ".deepseek" / "subagents.v1.json")
    max_agents = min(
        20,
        config.max_subagents or config.subagents.max_concurrent or 10,
    )
    manager = SubAgentManager(
        workspace=workspace,
        max_agents=max_agents,
        state_path=resolved_state_path,
        mailbox=mailbox,
        executor=executor_factory(),
        default_model=(
            config.subagents.default_model
            or config.default_text_model
            or "deepseek-chat"
        ),
    )
    services.add(
        SubAgentManager,
        manager,
        owner="subagents",
        scope=ServiceScope.PROCESS,
    )
    services.add_named(
        "subagent_manager",
        manager,
        owner="subagents",
        scope=ServiceScope.PROCESS,
    )
    return manager, mailbox


def attach_subagent_parent_cancel(
    manager: SubAgentManager | None,
    cancel_token: asyncio.Event,
) -> None:
    if manager is None:
        return
    manager.attach_parent_cancel(cancel_token)


async def attach_engine_subagents(
    shell: EngineShell,
    *,
    config: Config,
    client: LLMClient,
    workspace: Path,
    default_model: str,
    tool_runtime: object,
) -> None:
    """Wire subagent loop runtime onto a materialized engine."""
    manager = getattr(tool_runtime, "subagent_manager", None)
    if manager is None:
        return
    auto_approve = await shell.approval_handler.auto_approve_enabled()
    attach_subagent_engine_bindings(
        manager,
        config=config,
        client=client,
        model=default_model,
        workspace=workspace,
        allow_shell=getattr(config, "allow_shell", True),
        auto_approve=auto_approve,
        task_manager=getattr(tool_runtime, "task_manager", None),
        cancel_token=shell.cancel_token,
        mailbox=getattr(tool_runtime, "mailbox", None),
        completion_sink=shell.enqueue_subagent_completion,
    )


def attach_subagent_engine_bindings(
    manager: SubAgentManager | None,
    *,
    config: Config,
    client: LLMClient,
    model: str,
    workspace: Path,
    allow_shell: bool,
    auto_approve: bool,
    task_manager: TaskManager | None,
    cancel_token: asyncio.Event,
    mailbox: Mailbox | None,
    completion_sink: CompletionSink,
) -> None:
    if manager is None:
        return
    manager.attach_parent_cancel(cancel_token)
    manager.attach_parent_completion_sink(completion_sink)
    manager.attach_loop_runtime(
        SubAgentRuntime(
            manager=manager,
            client=client,
            model=model,
            config=config,
            workspace=workspace.resolve(),
            allow_shell=allow_shell,
            auto_approve=auto_approve,
            task_manager=task_manager,
            cancel_token=cancel_token,
            mailbox=mailbox,
        )
    )


async def shutdown_subagent_runtime(
    manager: SubAgentManager | None,
    mailbox: Mailbox | None,
    *,
    owns_manager: bool,
) -> None:
    if mailbox is not None:
        mailbox.close()
    if owns_manager and manager is not None:
        await manager.shutdown()
