"""Turn evidence must exist for memory capture when evolution is disabled."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.evolution.constants import EVOLUTION_LEDGER_KEY, TURN_EVIDENCE_KEY
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry


def test_sync_turn_evidence_without_ledger_sets_current_only(tmp_path: Path) -> None:
    engine = Engine(
        handle=EngineHandle(),
        client=object(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
        tool_context=ToolContext(working_directory=tmp_path),
    )
    engine.memory_thread_id = "thread-1"
    working = [Message.user("hello")]

    engine._sync_tool_turn_evidence(
        working_messages=working,
        prior_count=0,
        user_text="hello",
        turn_id="turn-1",
        success=True,
    )

    assert engine._current_turn_evidence is not None
    assert engine._current_turn_evidence.thread_id == "thread-1"  # type: ignore[attr-defined]
    assert TURN_EVIDENCE_KEY not in engine.tool_context.metadata
    inp = engine._current_turn_evidence.to_capture_input()  # type: ignore[attr-defined]
    assert inp.user_text == "hello"


def test_sync_turn_evidence_with_ledger_sets_tool_metadata(tmp_path: Path) -> None:
    engine = Engine(
        handle=EngineHandle(),
        client=object(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
        tool_context=ToolContext(working_directory=tmp_path),
    )
    engine.tool_context.metadata[EVOLUTION_LEDGER_KEY] = object()
    working = [Message.user("hi")]

    engine._sync_tool_turn_evidence(
        working_messages=working,
        prior_count=0,
        user_text="hi",
        turn_id="turn-2",
        success=False,
    )

    assert TURN_EVIDENCE_KEY in engine.tool_context.metadata
    assert engine.tool_context.metadata[TURN_EVIDENCE_KEY].turn_id == "turn-2"  # type: ignore[attr-defined]
