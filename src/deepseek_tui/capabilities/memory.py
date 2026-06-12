"""Memory capability prompt contributions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from deepseek_tui.config.models import Config
from deepseek_tui.host.engine_shell import EngineShell
from deepseek_tui.host.lifecycle import PREPARED_USER_TURN_DECORATION, PreparedUserTurn
from deepseek_tui.host.prompts import (
    FunctionPromptContributor,
    PromptContributor,
    PromptContributorContext,
)
from deepseek_tui.host.services import ServiceRegistry, ServiceScope
from deepseek_tui.memory.coordinator import MemoryCoordinator
from deepseek_tui.memory.formatting import wrap_relevant_memories_system_block
from deepseek_tui.memory.provider import MemoryProvider, RecallResult
from deepseek_tui.tools.memory_tools import MEMORY_PROVIDER_KEY, MEMORY_SEARCH_CALLS_KEY

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.protocol.messages import Message


_TRIVIAL_RECALL_PROMPTS = {
    "hi",
    "hello",
    "hey",
    "ok",
    "okay",
    "thanks",
    "thank you",
    "你好",
    "您好",
    "好的",
    "好",
    "嗯",
    "谢谢",
}

MEMORY_TURN_CONTEXT_DECORATION = PREPARED_USER_TURN_DECORATION


@dataclass(slots=True)
class MemoryRuntime:
    enabled: bool
    path: Path | None
    mode: str | None
    coordinator: MemoryCoordinator | None = None
    provider: MemoryProvider | None = None


MemoryTurnContext = PreparedUserTurn


@dataclass(slots=True)
class DynamicMemoryBeforeTurnObserver:
    coordinator: Callable[[], object | None]
    memory_thread_id: Callable[[], str | None]
    cycle_session_id: Callable[[], str | None]
    memory_mode: Callable[[], str | None]

    async def before_user_turn(self, context: object) -> None:
        prepared = await prepare_memory_turn_context(
            coordinator=self.coordinator(),
            metadata=context.metadata,  # type: ignore[attr-defined]
            memory_thread_id=self.memory_thread_id(),
            cycle_session_id=self.cycle_session_id(),
            user_text=context.user_text,  # type: ignore[attr-defined]
            workspace=context.workspace,  # type: ignore[attr-defined]
            memory_mode=self.memory_mode(),
        )
        context.decorations[MEMORY_TURN_CONTEXT_DECORATION] = prepared  # type: ignore[attr-defined]


def dynamic_memory_before_turn_observer(
    *,
    coordinator: Callable[[], object | None],
    memory_thread_id: Callable[[], str | None],
    cycle_session_id: Callable[[], str | None],
    memory_mode: Callable[[], str | None],
) -> DynamicMemoryBeforeTurnObserver:
    return DynamicMemoryBeforeTurnObserver(
        coordinator=coordinator,
        memory_thread_id=memory_thread_id,
        cycle_session_id=cycle_session_id,
        memory_mode=memory_mode,
    )


def register_engine_lifecycle_observer(access: object, registry: object) -> None:
    """Register the memory before-turn lifecycle observer once."""
    from deepseek_tui.host.lifecycle import lifecycle_observer_registered

    if lifecycle_observer_registered(registry, "memory.before_turn"):  # type: ignore[arg-type]
        return

    registry.add(  # type: ignore[attr-defined]
        id="memory.before_turn",
        owner="memory",
        order=100,
        observer=dynamic_memory_before_turn_observer(
            coordinator=access.memory_coordinator,  # type: ignore[attr-defined]
            memory_thread_id=access.memory_thread_id,  # type: ignore[attr-defined]
            cycle_session_id=access.cycle_session_id,  # type: ignore[attr-defined]
            memory_mode=access.memory_mode,  # type: ignore[attr-defined]
        ),
    )


async def create_memory_runtime(
    config: Config,
    client: LLMClient,
    services: ServiceRegistry,
) -> MemoryRuntime:
    runtime = MemoryRuntime(
        enabled=config.memory_enabled(),
        path=config.resolved_memory_path(),
        mode=config.memory.mode,
    )
    if not config.smart_memory_enabled():
        return runtime

    from deepseek_tui.memory.factory import create_smart_memory_provider

    provider = create_smart_memory_provider(config, client)
    coordinator = MemoryCoordinator(config, provider)
    await coordinator.start()
    runtime.coordinator = coordinator
    runtime.provider = provider
    if services.optional(MemoryCoordinator) is None:
        services.add(
            MemoryCoordinator,
            coordinator,
            owner="memory",
            scope=ServiceScope.ENGINE,
        )
    if services.optional(MemoryProvider) is None:
        services.add(
            MemoryProvider,
            provider,
            owner="memory",
            scope=ServiceScope.ENGINE,
        )
    return runtime


async def attach_engine_memory(
    shell: EngineShell,
    config: Config,
    client: LLMClient,
) -> MemoryRuntime:
    """Wire memory runtime onto a materialized engine."""
    memory_runtime = await create_memory_runtime(
        config,
        client,
        shell.tool_context.services,
    )
    shell.memory_enabled = memory_runtime.enabled
    shell.memory_path = memory_runtime.path
    shell.memory_mode = memory_runtime.mode
    shell.memory_coordinator = memory_runtime.coordinator
    attach_memory_bindings(
        memory_runtime,
        metadata=shell.tool_context.metadata,
        services=shell.tool_context.services,
    )
    return memory_runtime


def attach_memory_bindings(
    runtime: MemoryRuntime,
    *,
    metadata: dict[str, object],
    services: ServiceRegistry,
) -> None:
    metadata[MEMORY_SEARCH_CALLS_KEY] = 0
    if runtime.provider is None:
        return
    if services.optional_named(MEMORY_PROVIDER_KEY) is None:
        services.add_named(
            MEMORY_PROVIDER_KEY,
            runtime.provider,
            owner="memory",
            scope=ServiceScope.ENGINE,
        )


def should_skip_memory_recall(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return True
    return normalized in _TRIVIAL_RECALL_PROMPTS


async def recall_memory_for_turn(
    coordinator: object | None,
    *,
    thread_id: str,
    user_text: str,
    workspace: Path,
    memory_mode: str | None,
) -> object | None:
    if coordinator is None or should_skip_memory_recall(user_text):
        return None
    if not isinstance(coordinator, MemoryCoordinator):
        return None
    return cast(
        object | None,
        await coordinator.recall_for_turn(
            thread_id,
            user_text,
            workspace=str(workspace.resolve()),  # noqa: ASYNC240
            thread_memory_mode=memory_mode,
        ),
    )


async def prepare_memory_turn_context(
    *,
    coordinator: object | None,
    metadata: dict[str, object],
    memory_thread_id: str | None,
    cycle_session_id: str | None,
    user_text: str,
    workspace: Path,
    memory_mode: str | None,
) -> PreparedUserTurn:
    from deepseek_tui.memory.formatting import wrap_relevant_memories
    from deepseek_tui.protocol.messages import Message

    metadata[MEMORY_SEARCH_CALLS_KEY] = 0
    thread_id = resolve_memory_thread_id(
        memory_thread_id=memory_thread_id,
        metadata=metadata,
        cycle_session_id=cycle_session_id,
    )
    recall = await recall_memory_for_turn(
        coordinator,
        thread_id=thread_id,
        user_text=user_text,
        workspace=workspace,
        memory_mode=memory_mode,
    )
    user_message = Message.user(user_text)
    if (
        isinstance(recall, RecallResult)
        and recall.l1_context.strip()
        and recall.inject_position == "user"
    ):
        wrapped = wrap_relevant_memories(user_text, recall.l1_context)
        user_message = Message.user(wrapped)
    return PreparedUserTurn(
        thread_id=thread_id,
        recall=recall,
        user_message=user_message,
    )


async def capture_memory_after_turn(
    coordinator: object | None,
    evidence: object | None,
) -> None:
    if coordinator is None or evidence is None:
        return
    if not isinstance(coordinator, MemoryCoordinator):
        return
    capture_input = evidence.to_capture_input()  # type: ignore[attr-defined]
    await coordinator.capture_after_turn(
        thread_id=capture_input.thread_id,
        user_text=capture_input.user_text,
        workspace=capture_input.workspace,
        messages=capture_input.messages,
        had_tool_calls=capture_input.had_tool_calls,
        success=capture_input.success,
    )


def resolve_memory_thread_id(
    *,
    memory_thread_id: str | None,
    metadata: dict[str, object],
    cycle_session_id: str | None,
) -> str:
    if memory_thread_id:
        return memory_thread_id
    runtime_tid = metadata.get("runtime_thread_id")
    if isinstance(runtime_tid, str) and runtime_tid:
        return runtime_tid
    if cycle_session_id:
        return cycle_session_id
    return "default"


def memory_md_enabled(
    *,
    coordinator: object | None,
    memory_mode: str | None,
    fallback_enabled: bool,
) -> bool:
    if coordinator is not None:
        if isinstance(coordinator, MemoryCoordinator):
            return bool(coordinator.memory_md_enabled(memory_mode))
    return fallback_enabled


def messages_for_capture(messages: list[Message]) -> list[dict[str, str]]:
    from deepseek_tui.protocol.messages import TextBlock, ToolResultBlock

    out: list[dict[str, str]] = []
    for msg in messages:
        parts: list[str] = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                parts.append(block.text)
            elif isinstance(block, ToolResultBlock):
                parts.append(str(block.content))
        content = "\n".join(parts).strip()
        if not content:
            continue
        out.append({"role": msg.role.value, "content": content})
    return out


def turn_had_tool_calls(messages: list[Message]) -> bool:
    from deepseek_tui.protocol.messages import Role, ToolUseBlock

    for msg in messages:
        if msg.role == Role.TOOL:
            return True
        if msg.role == Role.ASSISTANT:
            for block in msg.content:
                if isinstance(block, ToolUseBlock):
                    return True
    return False


def build_turn_evidence(
    *,
    thread_id: str,
    user_text: str,
    workspace: Path,
    turn_slice: list[Message],
    success: bool,
    tool_rounds: int,
    user_turn_index: int,
    turn_id: str,
    flush_mode: bool = False,
) -> object:
    from deepseek_tui.post_turn.evidence import TurnEvidence

    return TurnEvidence(
        thread_id=thread_id,
        user_text=user_text,
        workspace=str(workspace.resolve()),
        messages=messages_for_capture(turn_slice),
        had_tool_calls=turn_had_tool_calls(turn_slice),
        success=success,
        tool_rounds=tool_rounds,
        user_turn_index=user_turn_index,
        turn_id=turn_id,
        flush_mode=flush_mode,
    )


def build_flush_evidence(
    *,
    messages: list[Message],
    thread_id: str,
    workspace: Path,
    user_turn_index: int,
    turn_id: str,
) -> object:
    from deepseek_tui.protocol.messages import TextBlock

    turn_slice = messages[-20:] if len(messages) > 20 else messages
    user_text = ""
    for msg in reversed(messages):
        if msg.role.value == "user":
            parts = [b.text for b in msg.content if isinstance(b, TextBlock)]
            user_text = "\n".join(parts).strip()
            if user_text:
                break
    return build_turn_evidence(
        thread_id=thread_id,
        user_text=user_text,
        workspace=workspace,
        turn_slice=turn_slice,
        success=True,
        tool_rounds=0,
        user_turn_index=user_turn_index,
        turn_id=turn_id,
        flush_mode=True,
    )


def memory_prompt_contributors() -> list[PromptContributor]:
    return [
        FunctionPromptContributor("memory-stable", 400, _memory_stable),
        FunctionPromptContributor("memory-volatile", 1000, _memory_volatile),
        FunctionPromptContributor("user-memory", 1200, _user_memory),
    ]


def _memory_stable(ctx: PromptContributorContext) -> str | None:
    recall = ctx.memory_recall
    if isinstance(recall, RecallResult) and recall.append_system.strip():
        return str(recall.append_system.strip())
    return None


def _memory_volatile(ctx: PromptContributorContext) -> str | None:
    recall = ctx.memory_recall
    if not isinstance(recall, RecallResult):
        return None
    if not recall.l1_context.strip() or recall.inject_position != "system_volatile":
        return None
    return str(wrap_relevant_memories_system_block(recall.l1_context))


def _user_memory(ctx: PromptContributorContext) -> str | None:
    memory_path = ctx.memory_path
    if memory_path is None:
        from deepseek_tui.config.paths import user_memory_path

        memory_path = user_memory_path()
    from deepseek_tui.memory.user_memory import compose_block

    return cast(str | None, compose_block(ctx.memory_enabled, memory_path))
