from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.capabilities.memory import (
    MEMORY_TURN_CONTEXT_DECORATION,
    MemoryTurnContext,
    attach_memory_legacy_bindings,
    build_flush_evidence,
    build_turn_evidence,
    capture_memory_after_turn,
    create_memory_runtime,
    memory_before_turn_observer,
    messages_for_capture,
    prepare_memory_turn_context,
    recall_memory_for_turn,
    resolve_memory_thread_id,
    should_skip_memory_recall,
    turn_had_tool_calls,
)
from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.host.lifecycle import BeforeUserTurnContext, LifecycleRegistry
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.memory.coordinator import MemoryCoordinator
from deepseek_tui.memory.provider import MemoryProvider, RecallResult
from deepseek_tui.protocol.messages import Message, ToolUseBlock
from deepseek_tui.tools.memory_tools import MEMORY_PROVIDER_KEY, MEMORY_SEARCH_CALLS_KEY


@pytest.mark.asyncio
async def test_memory_capability_skips_smart_memory_when_disabled() -> None:
    services = ServiceRegistry()
    cfg = Config(memory=MemoryConfig(enabled=False))

    runtime = await create_memory_runtime(cfg, AsyncMock(), services)
    metadata: dict[str, object] = {}
    attach_memory_legacy_bindings(runtime, metadata=metadata, services=services)

    assert runtime.enabled is False
    assert runtime.coordinator is None
    assert runtime.provider is None
    assert metadata == {MEMORY_SEARCH_CALLS_KEY: 0}
    assert services.optional(MemoryCoordinator) is None
    assert services.optional(MemoryProvider) is None


@pytest.mark.asyncio
async def test_memory_capability_creates_smart_runtime(tmp_path: Path) -> None:
    services = ServiceRegistry()
    cfg = Config(
        memory=MemoryConfig(
            enabled=True,
            mode="hybrid",
            smart=MemorySmartConfig(
                enabled=True,
                data_dir=str(tmp_path / "memory_data"),
                l1_every_n=100,
            ),
        )
    )

    runtime = await create_memory_runtime(cfg, AsyncMock(), services)
    metadata: dict[str, object] = {}
    attach_memory_legacy_bindings(runtime, metadata=metadata, services=services)
    try:
        assert runtime.enabled is True
        assert runtime.mode == "hybrid"
        assert isinstance(runtime.coordinator, MemoryCoordinator)
        assert runtime.provider is not None
        assert services.require(MemoryCoordinator) is runtime.coordinator
        assert services.require(MemoryProvider) is runtime.provider
        assert metadata[MEMORY_SEARCH_CALLS_KEY] == 0
        assert metadata[MEMORY_PROVIDER_KEY] is runtime.provider
        assert services.require_named(MEMORY_PROVIDER_KEY) is runtime.provider
    finally:
        if runtime.coordinator is not None:
            await runtime.coordinator.stop()


@pytest.mark.asyncio
async def test_memory_capability_allows_existing_services(tmp_path: Path) -> None:
    services = ServiceRegistry()
    cfg = Config(
        memory=MemoryConfig(
            enabled=True,
            smart=MemorySmartConfig(
                enabled=True,
                data_dir=str(tmp_path / "memory_data"),
                l1_every_n=100,
            ),
        )
    )

    first = await create_memory_runtime(cfg, AsyncMock(), services)
    second = await create_memory_runtime(cfg, AsyncMock(), services)
    try:
        assert first.coordinator is not None
        assert second.coordinator is not None
        assert services.require(MemoryCoordinator) is first.coordinator
    finally:
        if second.coordinator is not None:
            await second.coordinator.stop()
        if first.coordinator is not None:
            await first.coordinator.stop()


class _RecallCoordinator(MemoryCoordinator):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.captures: list[dict[str, object]] = []

    async def recall_for_turn(
        self,
        thread_id: str,
        user_text: str,
        *,
        workspace: str,
        thread_memory_mode: str | None = None,
    ) -> object:
        self.calls.append(
            {
                "thread_id": thread_id,
                "user_text": user_text,
                "workspace": workspace,
                "thread_memory_mode": thread_memory_mode,
            }
        )
        return RecallResult(l1_context="remembered fact", inject_position="user")

    async def capture_after_turn(
        self,
        *,
        thread_id: str,
        user_text: str,
        workspace: str,
        messages: list[dict[str, str]],
        had_tool_calls: bool,
        success: bool,
    ) -> None:
        self.captures.append(
            {
                "thread_id": thread_id,
                "user_text": user_text,
                "workspace": workspace,
                "messages": messages,
                "had_tool_calls": had_tool_calls,
                "success": success,
            }
        )


def test_memory_capability_skips_trivial_recall() -> None:
    assert should_skip_memory_recall("")
    assert should_skip_memory_recall("  thanks  ")
    assert should_skip_memory_recall("你好")
    assert not should_skip_memory_recall("please inspect this repo")


@pytest.mark.asyncio
async def test_memory_capability_recalls_for_non_trivial_turn(tmp_path: Path) -> None:
    coordinator = _RecallCoordinator()

    recall = await recall_memory_for_turn(
        coordinator,
        thread_id="thread-1",
        user_text="please inspect this repo",
        workspace=tmp_path,
        memory_mode="hybrid",
    )

    assert isinstance(recall, RecallResult)
    assert coordinator.calls == [
        {
            "thread_id": "thread-1",
            "user_text": "please inspect this repo",
            "workspace": str(tmp_path.resolve()),
            "thread_memory_mode": "hybrid",
        }
    ]


@pytest.mark.asyncio
async def test_memory_capability_prepares_turn_context(tmp_path: Path) -> None:
    coordinator = _RecallCoordinator()
    metadata: dict[str, object] = {"runtime_thread_id": "runtime-thread"}

    prepared = await prepare_memory_turn_context(
        coordinator=coordinator,
        metadata=metadata,
        memory_thread_id=None,
        cycle_session_id="cycle-thread",
        user_text="please inspect this repo",
        workspace=tmp_path,
        memory_mode="hybrid",
    )

    assert prepared.thread_id == "runtime-thread"
    assert isinstance(prepared.recall, RecallResult)
    assert metadata[MEMORY_SEARCH_CALLS_KEY] == 0
    assert "<relevant-memories>" in prepared.user_message.content[0].text


@pytest.mark.asyncio
async def test_memory_capability_before_turn_observer_decorates_context(
    tmp_path: Path,
) -> None:
    coordinator = _RecallCoordinator()
    metadata: dict[str, object] = {"runtime_thread_id": "runtime-thread"}
    registry = LifecycleRegistry()
    registry.add(
        id="memory.before_turn",
        owner="memory",
        observer=memory_before_turn_observer(
            coordinator=coordinator,
            memory_thread_id=None,
            cycle_session_id="cycle-thread",
            memory_mode="hybrid",
        ),
    )
    context = BeforeUserTurnContext(
        thread_id="runtime-thread",
        turn_id="turn-1",
        user_text="please inspect this repo",
        workspace=tmp_path,
        metadata=metadata,
        services=ServiceRegistry(),
    )

    await registry.before_user_turn(context)

    prepared = context.decorations[MEMORY_TURN_CONTEXT_DECORATION]
    assert isinstance(prepared, MemoryTurnContext)
    assert prepared.thread_id == "runtime-thread"
    assert metadata[MEMORY_SEARCH_CALLS_KEY] == 0


@pytest.mark.asyncio
async def test_memory_capability_capture_after_turn(tmp_path: Path) -> None:
    coordinator = _RecallCoordinator()
    evidence = build_turn_evidence(
        thread_id="thread-1",
        user_text="remember this",
        workspace=tmp_path,
        turn_slice=[Message.user("remember this")],
        success=True,
        tool_rounds=0,
        user_turn_index=1,
        turn_id="turn-1",
    )

    await capture_memory_after_turn(coordinator, evidence)

    assert len(coordinator.captures) == 1
    assert coordinator.captures[0]["thread_id"] == "thread-1"
    assert coordinator.captures[0]["user_text"] == "remember this"


def test_memory_capability_resolves_thread_id() -> None:
    assert (
        resolve_memory_thread_id(
            memory_thread_id="memory-thread",
            metadata={"runtime_thread_id": "runtime-thread"},
            cycle_session_id="cycle-thread",
        )
        == "memory-thread"
    )
    assert (
        resolve_memory_thread_id(
            memory_thread_id=None,
            metadata={"runtime_thread_id": "runtime-thread"},
            cycle_session_id="cycle-thread",
        )
        == "runtime-thread"
    )
    assert (
        resolve_memory_thread_id(
            memory_thread_id=None,
            metadata={},
            cycle_session_id="cycle-thread",
        )
        == "cycle-thread"
    )


def test_memory_capability_builds_capture_messages_and_tool_flag() -> None:
    messages = [
        Message.user("hello"),
        Message.assistant_with_tools(
            [
                ToolUseBlock(
                    id="tool-1",
                    name="read_file",
                    input={},
                )
            ]
        ),
        Message.tool_result("tool-1", "file body"),
    ]

    assert messages_for_capture(messages) == [
        {"role": "user", "content": "hello"},
        {"role": "tool", "content": "file body"},
    ]
    assert turn_had_tool_calls(messages) is True


def test_memory_capability_builds_turn_and_flush_evidence(tmp_path: Path) -> None:
    messages = [Message.user("please remember this"), Message.assistant("done")]

    evidence = build_turn_evidence(
        thread_id="thread-1",
        user_text="please remember this",
        workspace=tmp_path,
        turn_slice=messages,
        success=True,
        tool_rounds=2,
        user_turn_index=3,
        turn_id="turn-1",
    )
    assert evidence.thread_id == "thread-1"
    assert evidence.workspace == str(tmp_path.resolve())
    assert evidence.messages[0]["content"] == "please remember this"
    assert evidence.tool_rounds == 2
    assert evidence.flush_mode is False

    flush = build_flush_evidence(
        messages=messages,
        thread_id="thread-1",
        workspace=tmp_path,
        user_turn_index=3,
        turn_id="turn-1",
    )
    assert flush.flush_mode is True
    assert flush.user_text == "please remember this"
