from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.capabilities.cycle import (
    advance_cycle_if_needed,
    apply_layered_context_checkpoint,
    create_cycle_runtime,
)
from deepseek_tui.capabilities.hooks import (
    attach_hook_bindings,
    create_hook_runtime,
)
from deepseek_tui.capabilities.post_turn import (
    build_post_turn_pipelines,
    flush_post_turn_before_loss,
    post_turn_tool_observer,
    run_post_turn_after_turn,
    start_post_turn_orchestrator,
    stop_post_turn_orchestrator,
)
from deepseek_tui.capabilities.workflow import workflow_mode_hint
from deepseek_tui.config.models import Config, PostTurnConfig
from deepseek_tui.engine.cycle_manager import CycleConfig
from deepseek_tui.engine.seam_manager import SeamConfig, SeamManager
from deepseek_tui.hooks.executor import HookExecutor
from deepseek_tui.host.lifecycle import AfterToolContext, LifecycleRegistry
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.protocol.messages import Message


class _Handle:
    def __init__(self) -> None:
        self.hooks = None

    def attach_hooks(self, hooks: object) -> None:
        self.hooks = hooks


class _Pipeline:
    name = "test"

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1

    async def after_turn(self, _evidence: object) -> None:
        return None

    async def flush_before_loss(self, _evidence: object) -> None:
        return None


class _PostTurnRecorder:
    def __init__(self) -> None:
        self.after: list[object] = []
        self.flushes: list[object] = []
        self.main_tools: list[str] = []

    async def after_turn(self, evidence: object) -> None:
        self.after.append(evidence)

    async def flush_before_loss(self, evidence: object) -> None:
        self.flushes.append(evidence)

    def on_main_tool_called(self, tool_name: str) -> None:
        self.main_tools.append(tool_name)


class _WorkingSet:
    def pinned_message_indices(self, _messages: object, _workspace: object) -> set[int]:
        return set()


def test_hook_capability_attaches_dispatcher_and_legacy_binding(tmp_path: Path) -> None:
    handle = _Handle()
    runtime = create_hook_runtime(Config(), workspace=tmp_path, handle=handle)
    metadata: dict[str, object] = {}
    services = ServiceRegistry()

    attach_hook_bindings(runtime, services)

    assert handle.hooks is not None
    assert isinstance(runtime.executor, HookExecutor)
    assert "hook_executor" not in metadata
    assert services.require(HookExecutor) is runtime.executor
    assert services.optional_named("hook_executor") is runtime.executor


def test_cycle_capability_defaults_off_and_creates_session_id() -> None:
    cfg = Config(cycle_enabled=False, seam_enabled=False)

    runtime = create_cycle_runtime(cfg, client=AsyncMock())

    assert runtime.config.enabled is False
    assert runtime.seam_manager is None
    assert runtime.session_id
    assert runtime.started_at > 0


def test_cycle_capability_creates_enabled_seam_runtime() -> None:
    cfg = Config(cycle_enabled=True, seam_enabled=True)

    runtime = create_cycle_runtime(cfg, client=AsyncMock())

    assert runtime.config.enabled is True
    assert runtime.seam_manager is not None
    assert runtime.seam_manager.config.enabled is True


@pytest.mark.asyncio
async def test_cycle_capability_applies_layered_context_checkpoint(
    tmp_path: Path,
) -> None:
    seam = SeamManager(AsyncMock(), SeamConfig(enabled=True))
    seam.highest_level = AsyncMock(return_value=None)  # type: ignore[method-assign]
    seam.seam_level_for = lambda _tokens, _highest: 1  # type: ignore[method-assign]
    seam.verbatim_window_start = lambda _count: 1  # type: ignore[method-assign]
    seam.collect_seam_texts = AsyncMock(return_value=[])  # type: ignore[method-assign]
    seam.produce_soft_seam = AsyncMock(return_value="<archived_context>x</archived_context>")  # type: ignore[method-assign]
    messages = [Message.user("hello"), Message.assistant("world")]

    await apply_layered_context_checkpoint(
        seam_manager=seam,
        messages=messages,
        working_set=_WorkingSet(),
        workspace=tmp_path,
    )

    assert len(messages) == 3
    assert messages[-1].content[0].text == "<archived_context>x</archived_context>"


@pytest.mark.asyncio
async def test_cycle_capability_advances_cycle_and_keeps_recent_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archived: list[dict[str, object]] = []

    def _archive_cycle(**kwargs: object) -> str:
        archived.append(kwargs)
        return "/tmp/archive.jsonl"

    monkeypatch.setattr(
        "deepseek_tui.capabilities.cycle.archive_cycle",
        _archive_cycle,
    )
    messages = [Message.user(f"message {idx}") for idx in range(12)]

    result = await advance_cycle_if_needed(
        messages=messages,
        model="deepseek-chat",
        config=CycleConfig(enabled=True, threshold_tokens=1),
        session_id="session-1",
        cycle_n=2,
        started_at=100,
    )

    assert result.advanced is True
    assert result.cycle_n == 3
    assert len(messages) == 8
    assert messages[0].content[0].text == "message 4"
    assert archived and archived[0]["cycle_n"] == 2


@pytest.mark.asyncio
async def test_post_turn_capability_starts_and_stops_pipelines() -> None:
    first = _Pipeline()
    second = _Pipeline()

    orchestrator = await start_post_turn_orchestrator(
        Config(),
        [first, second],
    )
    await stop_post_turn_orchestrator(orchestrator)

    assert orchestrator is not None
    assert first.started == 1
    assert second.started == 1
    assert first.stopped == 1
    assert second.stopped == 1


@pytest.mark.asyncio
async def test_post_turn_capability_skips_when_disabled() -> None:
    orchestrator = await start_post_turn_orchestrator(
        Config(post_turn=PostTurnConfig(enabled=False)),
        [_Pipeline()],
    )

    assert orchestrator is None


def test_post_turn_capability_preserves_pipeline_order() -> None:
    evolution = _Pipeline()
    pipelines = build_post_turn_pipelines(
        Config(),
        memory_coordinator=None,
        evolution_pipeline=evolution,
    )

    assert pipelines == [evolution]


@pytest.mark.asyncio
async def test_post_turn_capability_after_tool_observer_notifies_main_tool() -> None:
    post_turn = _PostTurnRecorder()
    registry = LifecycleRegistry()
    registry.add(
        id="post_turn.after_tool",
        owner="post_turn",
        observer=post_turn_tool_observer(post_turn),
    )

    await registry.after_tool(
        AfterToolContext(
            tool_call_id="call-1",
            tool_name="memory_curate",
            arguments={},
            success=True,
            result=object(),
            metadata={},
            services=ServiceRegistry(),
        )
    )

    assert post_turn.main_tools == ["memory_curate"]


@pytest.mark.asyncio
async def test_post_turn_capability_runs_after_turn_or_memory_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_turn = _PostTurnRecorder()
    evidence = object()

    await run_post_turn_after_turn(
        post_turn=post_turn,
        evidence=evidence,
        memory_coordinator=object(),
    )

    assert post_turn.after == [evidence]

    captures: list[tuple[object | None, object | None]] = []

    async def _capture(coordinator: object | None, evidence: object | None) -> None:
        captures.append((coordinator, evidence))

    monkeypatch.setattr(
        "deepseek_tui.capabilities.memory.capture_memory_after_turn",
        _capture,
    )
    coordinator = object()
    await run_post_turn_after_turn(
        post_turn=None,
        evidence=evidence,
        memory_coordinator=coordinator,
    )

    assert captures == [(coordinator, evidence)]


@pytest.mark.asyncio
async def test_post_turn_capability_flushes_before_loss() -> None:
    post_turn = _PostTurnRecorder()
    evidence = object()

    await flush_post_turn_before_loss(post_turn=post_turn, evidence=evidence)
    await flush_post_turn_before_loss(post_turn=post_turn, evidence=None)
    await flush_post_turn_before_loss(post_turn=None, evidence=evidence)

    assert post_turn.flushes == [evidence]


def test_workflow_capability_mode_hint() -> None:
    assert workflow_mode_hint("agent") == ""
    assert "workflow tool" in workflow_mode_hint("workflow")
