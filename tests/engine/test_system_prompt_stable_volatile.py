"""Volatile state stays out of the system prompt (A); handoff is a reminder."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.engine.prompts import (
    build_system_prompt,
    load_handoff_reminder,
)
from deepseek_tui.protocol.messages import MessageOrigin


def test_system_prompt_ignores_working_set_and_omits_handoff(tmp_path: Path) -> None:
    deepseek = tmp_path / ".deepseek"
    deepseek.mkdir()
    (deepseek / "handoff.md").write_text(
        "Blocked on auth refresh token.\n", encoding="utf-8"
    )

    prompt = build_system_prompt(
        workspace=tmp_path,
        working_set_summary="### Working Set (recent files)\n- `a.py`\n",
        project_context_enabled=False,
    )
    assert "Working Set" not in prompt
    assert "Previous Session Handoff" not in prompt
    assert "auth refresh" not in prompt
    assert "After Compaction" in prompt


def test_load_handoff_reminder_reads_file(tmp_path: Path) -> None:
    deepseek = tmp_path / ".deepseek"
    deepseek.mkdir()
    (deepseek / "handoff.md").write_text("Next: finish login.\n", encoding="utf-8")
    body = load_handoff_reminder(tmp_path)
    assert body is not None
    assert "Previous Session Handoff" in body
    assert "finish login" in body


def test_take_handoff_reminder_injects_once(tmp_path: Path) -> None:
    from deepseek_tui.engine.orchestrator.core import Engine
    from deepseek_tui.tools.registry import ToolContext

    deepseek = tmp_path / ".deepseek"
    deepseek.mkdir()
    handoff = deepseek / "handoff.md"
    handoff.write_text("Carry this forward.\n", encoding="utf-8")

    engine = object.__new__(Engine)
    engine.tool_context = ToolContext(working_directory=tmp_path)
    engine._handoff_injected_mtime = None

    first = Engine._take_handoff_reminder_message(engine)
    assert first is not None
    assert first.origin is MessageOrigin.SYSTEM_REMINDER
    assert "<system-reminder>" in first.text_content()
    assert "Carry this forward" in first.text_content()

    second = Engine._take_handoff_reminder_message(engine)
    assert second is None

    # Rewrite file → inject again.
    handoff.write_text("Updated handoff.\n", encoding="utf-8")
    # Ensure mtime advances on fast filesystems.
    import os
    import time

    now = time.time() + 1
    os.utime(handoff, (now, now))
    third = Engine._take_handoff_reminder_message(engine)
    assert third is not None
    assert "Updated handoff" in third.text_content()


def test_hard_cap_message_count_removed_from_trigger_logic() -> None:
    """Regression: compact must not key off len(messages) > 500."""
    import inspect

    from deepseek_tui.engine.orchestrator import core as core_mod

    src = inspect.getsource(core_mod.Engine._run_conversation)
    assert "len(messages) > 500" not in src
    assert "hard_cap" not in src
