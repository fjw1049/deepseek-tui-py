"""Parity tests for engine/turn_loop.

Mirror of Rust `crates/tui/src/core/engine/tests.rs` turn_loop related tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from deepseek_tui.engine.tool_setup import (
    active_tools_for_step,
    ensure_advanced_tooling,
    initial_active_tools,
)
from deepseek_tui.engine.turn_loop import (
    MAX_CONTEXT_RECOVERY_ATTEMPTS,
    MAX_STREAM_RETRIES,
    TurnLoop,
    TurnOutcomeStatus,
    TurnResult,
)


class TestToolSetup:
    """Tests for tool setup and filtering logic."""

    def test_ensure_advanced_tooling_adds_missing_system_tools(self) -> None:
        """Mirror of Rust test: verify system tools are injected into catalog."""
        tools: list[dict[str, Any]] = []
        ensure_advanced_tooling(tools)

        tool_names = {t.get("name") for t in tools}
        assert "update_plan" in tool_names
        assert "note" in tool_names

    def test_ensure_advanced_tooling_preserves_existing_tools(self) -> None:
        """System tools shouldn't duplicate if already present."""
        tools = [
            {
                "type": "function",
                "name": "update_plan",
                "description": "Update plan",
                "parameters": {"type": "object"},
            }
        ]
        original_len = len(tools)
        ensure_advanced_tooling(tools)

        assert len(tools) >= original_len
        tool_names = [t.get("name") for t in tools if t.get("name")]
        assert tool_names.count("update_plan") == 1

    def test_initial_active_tools_returns_all_tool_names(self) -> None:
        """Initial active tools should include all tools in catalog."""
        tools = [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read file",
                "parameters": {"type": "object"},
            },
            {
                "type": "function",
                "name": "write_file",
                "description": "Write file",
                "parameters": {"type": "object"},
            },
        ]
        active = initial_active_tools(tools)

        assert active == {"read_file", "write_file"}

    def test_active_tools_for_step_returns_all_when_not_forcing_plan(self) -> None:
        """When not forcing plan, should return all active tools."""
        tools = [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read file",
                "parameters": {"type": "object"},
            },
            {
                "type": "function",
                "name": "update_plan",
                "description": "Update plan",
                "parameters": {"type": "object"},
            },
        ]
        active_names = {"read_file", "update_plan"}

        filtered = active_tools_for_step(tools, active_names, force_update_plan_first=False)

        assert len(filtered) == 2
        names = {t.get("name") for t in filtered}
        assert names == {"read_file", "update_plan"}

    def test_active_tools_for_step_only_returns_plan_when_forced(self) -> None:
        """Mirror of Rust test: when forcing plan, only update_plan should be active."""
        tools = [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read file",
                "parameters": {"type": "object"},
            },
            {
                "type": "function",
                "name": "update_plan",
                "description": "Update plan",
                "parameters": {"type": "object"},
            },
        ]
        active_names = {"read_file", "update_plan"}

        filtered = active_tools_for_step(tools, active_names, force_update_plan_first=True)

        assert len(filtered) == 1
        assert filtered[0].get("name") == "update_plan"

    def test_active_tools_for_step_returns_empty_if_plan_missing(self) -> None:
        """If plan tool missing and forced, should return empty."""
        tools = [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read file",
                "parameters": {"type": "object"},
            }
        ]
        active_names = {"read_file"}

        filtered = active_tools_for_step(tools, active_names, force_update_plan_first=True)

        assert len(filtered) == 0


class TestTurnLoop:
    """Tests for turn loop orchestration."""

    def test_turn_result_default_outcome(self) -> None:
        """Mirror of Rust test: TurnResult should default to SUCCESS outcome."""
        result = TurnResult(assistant_message=None)

        assert result.outcome == TurnOutcomeStatus.SUCCESS
        assert result.error_message is None
        assert result.cancelled is False

    def test_turn_result_with_cancelled(self) -> None:
        """TurnResult should track cancellation state."""
        result = TurnResult(
            assistant_message=None,
            cancelled=True,
            outcome=TurnOutcomeStatus.INTERRUPTED,
        )

        assert result.cancelled is True
        assert result.outcome == TurnOutcomeStatus.INTERRUPTED

    def test_turn_result_with_error_state(self) -> None:
        """TurnResult should track failure states with error message."""
        error_msg = "Context overflow"
        result = TurnResult(
            assistant_message=None,
            outcome=TurnOutcomeStatus.CONTEXT_OVERFLOW,
            error_message=error_msg,
        )

        assert result.outcome == TurnOutcomeStatus.CONTEXT_OVERFLOW
        assert result.error_message == error_msg

    @pytest.mark.asyncio
    async def test_turn_loop_initializes(self) -> None:
        """Verify TurnLoop can be instantiated with a client."""
        from deepseek_tui.client.base import LLMClient

        class DummyClient(LLMClient):
            async def stream_with_retry(self, request: Any) -> Any:
                yield None

            async def stream_chat_completion(self, request: Any) -> Any:
                yield None

        client = DummyClient()
        turn_loop = TurnLoop(client)

        assert turn_loop.client is client

    def test_turn_outcome_status_enum(self) -> None:
        """Verify TurnOutcomeStatus enum has expected values."""
        assert TurnOutcomeStatus.SUCCESS.value == "success"
        assert TurnOutcomeStatus.FAILED.value == "failed"
        assert TurnOutcomeStatus.INTERRUPTED.value == "interrupted"
        assert TurnOutcomeStatus.CONTEXT_OVERFLOW.value == "context_overflow"


class TestConstants:
    """Verify turn loop constants match Rust."""

    def test_max_stream_retries_constant(self) -> None:
        """Mirror of Rust constant MAX_STREAM_RETRIES = 3."""
        assert MAX_STREAM_RETRIES == 3

    def test_max_context_recovery_attempts_constant(self) -> None:
        """Mirror of Rust constant MAX_CONTEXT_RECOVERY_ATTEMPTS = 3."""
        assert MAX_CONTEXT_RECOVERY_ATTEMPTS == 3
