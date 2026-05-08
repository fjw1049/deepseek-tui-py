"""Stage 2 integration wiring tests.

Verifies that the 4 previously-orphan modules (tool_parser, compaction,
capacity, command_safety) are now wired into the runtime.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.capacity import (
    CapacityController,
    CapacityControllerConfig,
    GuardrailAction,
)
from deepseek_tui.engine.capacity_flow import (
    run_error_escalation_checkpoint,
    run_post_tool_checkpoint,
    run_pre_request_checkpoint,
)
from deepseek_tui.engine.compaction import CompactionConfig, should_compact
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.events import EngineEvent, ToolCallEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.turn_loop import TurnLoop, TurnOutcomeStatus
from deepseek_tui.execpolicy.decision import Decision
from deepseek_tui.execpolicy.policy import Policy
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    Usage,
)
from deepseek_tui.tools.shell_tools import _command_safety_heuristic

# ── Helpers ───────────────────────────────────────────────────────────


class _TextOnlyClient(LLMClient):
    """Client that returns plain text containing tool-call markers."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    async def stream_chat_completion(
        self, request: Any
    ) -> AsyncIterator[StreamTextDelta | StreamDone]:
        yield StreamTextDelta(text=self._text)
        yield StreamDone(usage=Usage(input_tokens=10, output_tokens=5))


class _SimpleClient(LLMClient):
    """Client that yields plain deltas then done."""

    def __init__(self, deltas: list[str] | None = None) -> None:
        super().__init__()
        self._deltas = deltas or ["ok"]

    async def stream_chat_completion(
        self, request: Any
    ) -> AsyncIterator[StreamTextDelta | StreamDone]:
        for text in self._deltas:
            yield StreamTextDelta(text=text)
        yield StreamDone(usage=Usage(input_tokens=10, output_tokens=5))


# ── 1. tool_parser wired into turn_loop ──────────────────────────────


class TestToolParserTurnLoopFallback:
    """Verify tool_parser activates in turn_loop for text-based tool calls."""

    @pytest.mark.asyncio
    async def test_text_tool_call_detected(self) -> None:
        """When the model emits a tool call as text, turn_loop should parse it."""
        text_with_tool = (
            'Here is the result:\n'
            '[TOOL_CALL] {"name": "read_file", "arguments": {"path": "foo.py"}} [/TOOL_CALL]'
        )
        client = _TextOnlyClient(text_with_tool)
        loop = TurnLoop(client)
        events: list[EngineEvent] = []

        async def emit(ev: EngineEvent) -> None:
            events.append(ev)

        request = MessageRequest(
            model="deepseek-chat",
            messages=[Message.user("test")],
            system_prompt="",
            max_tokens=1024,
        )
        cancel = asyncio.Event()
        result = await loop.run(request, emit, cancel)

        assert result.outcome == TurnOutcomeStatus.SUCCESS
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"

        tool_events = [e for e in events if isinstance(e, ToolCallEvent)]
        assert len(tool_events) == 1

    @pytest.mark.asyncio
    async def test_plain_text_no_false_positive(self) -> None:
        """Plain text without markers should produce zero tool calls."""
        client = _TextOnlyClient("Hello world, no tool calls here.")
        loop = TurnLoop(client)
        events: list[EngineEvent] = []

        async def emit(ev: EngineEvent) -> None:
            events.append(ev)

        request = MessageRequest(
            model="deepseek-chat",
            messages=[Message.user("test")],
            system_prompt="",
            max_tokens=1024,
        )
        cancel = asyncio.Event()
        result = await loop.run(request, emit, cancel)

        assert result.outcome == TurnOutcomeStatus.SUCCESS
        assert len(result.tool_calls) == 0


# ── 2. compaction wired into Engine ──────────────────────────────────


class TestCompactionWiring:
    """Verify Engine has compaction config and should_compact is reachable."""

    @pytest.mark.asyncio
    async def test_engine_has_compaction_config(self, tmp_path: Any) -> None:
        """Engine.__init__ should instantiate a CompactionConfig."""
        handle = EngineHandle()
        client = _SimpleClient()
        engine = await Engine.create(
            handle, client, default_model="test",
            working_directory=tmp_path,
        )
        assert isinstance(engine.compaction_config, CompactionConfig)

    def test_should_compact_returns_false_for_short_conversations(self) -> None:
        """Short message lists should not trigger compaction."""
        messages = [Message.user("hello"), Message.user("world")]
        config = CompactionConfig(enabled=True, token_threshold=50_000)
        assert should_compact(messages, config) is False

    @pytest.mark.asyncio
    async def test_turn_loop_accepts_compact_fn(self) -> None:
        """TurnLoop should accept and store a compact_fn callback."""
        client = _SimpleClient()

        async def dummy_compact(msgs: list[Message]) -> list[Message]:
            return msgs

        loop = TurnLoop(client, compact_fn=dummy_compact)
        assert loop._compact_fn is dummy_compact


# ── 3. capacity wired into Engine ────────────────────────────────────


class TestCapacityWiring:
    """Verify capacity controller is instantiated and checkpoints are callable."""

    @pytest.mark.asyncio
    async def test_engine_has_capacity_controller(self, tmp_path: Any) -> None:
        """Engine should have a CapacityController instance."""
        handle = EngineHandle()
        client = _SimpleClient()
        engine = await Engine.create(
            handle, client, default_model="test",
            working_directory=tmp_path,
        )
        assert isinstance(engine.capacity_controller, CapacityController)

    @pytest.mark.asyncio
    async def test_pre_request_checkpoint_runs(self) -> None:
        """run_pre_request_checkpoint should return a decision without error."""
        controller = CapacityController(config=CapacityControllerConfig())
        messages = [Message.user("hello")]
        decision, compacted = await run_pre_request_checkpoint(
            controller, turn_index=1, model="deepseek-chat",
            messages=messages,
        )
        assert decision.action == GuardrailAction.NO_INTERVENTION
        assert compacted is False

    @pytest.mark.asyncio
    async def test_post_tool_checkpoint_runs(self) -> None:
        """run_post_tool_checkpoint should return a decision without error."""
        controller = CapacityController(config=CapacityControllerConfig())
        messages = [Message.user("hello")]
        decision = await run_post_tool_checkpoint(
            controller, turn_index=1, model="deepseek-chat",
            messages=messages,
        )
        assert decision.action == GuardrailAction.NO_INTERVENTION

    @pytest.mark.asyncio
    async def test_error_escalation_below_threshold(self) -> None:
        """Low error counts should not trigger escalation."""
        controller = CapacityController(config=CapacityControllerConfig())
        messages = [Message.user("hello")]
        decision = await run_error_escalation_checkpoint(
            controller, turn_index=1, model="deepseek-chat",
            messages=messages, step_error_count=0,
            consecutive_tool_error_steps=0,
        )
        assert decision.action == GuardrailAction.NO_INTERVENTION


# ── 4. command_safety wired into ExecShellTool ───────────────────────


class TestCommandSafetyHeuristic:
    """Verify the heuristic fallback maps SafetyLevel to Decision."""

    def test_safe_command_allows(self) -> None:
        assert _command_safety_heuristic(["ls", "-la"]) == Decision.ALLOW

    def test_workspace_safe_allows(self) -> None:
        assert _command_safety_heuristic(["cargo", "build"]) == Decision.ALLOW

    def test_dangerous_command_forbidden(self) -> None:
        assert _command_safety_heuristic(["rm", "-rf", "/"]) == Decision.FORBIDDEN

    def test_unknown_command_prompts(self) -> None:
        assert _command_safety_heuristic(["some_unknown_binary"]) == Decision.PROMPT

    def test_policy_uses_heuristic_fallback(self) -> None:
        """Policy.check with no rules should fall back to command_safety."""
        policy = Policy.empty()
        evaluation = policy.check(["rm", "-rf", "/"], _command_safety_heuristic)
        assert evaluation.decision == Decision.FORBIDDEN

    def test_policy_safe_command_via_heuristic(self) -> None:
        policy = Policy.empty()
        evaluation = policy.check(["git", "status"], _command_safety_heuristic)
        assert evaluation.decision == Decision.ALLOW
