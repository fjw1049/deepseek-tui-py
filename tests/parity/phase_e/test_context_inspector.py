"""Context inspector parity tests.

Mirror Rust tests in ``crates/tui/src/tui/context_inspector.rs``
(context_inspector.rs:294-466).
"""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.protocol.messages import Message, TextBlock
from deepseek_tui.tui.widgets.context_inspector import (
    WORKING_SET_MARKER,
    ContextReferenceView,
    InspectorSnapshot,
    ToolDetailView,
    build_context_inspector_text,
)


def _snap(**overrides: object) -> InspectorSnapshot:
    base = {
        "model": "unknown-model",
        "workspace": Path("/tmp/project"),
    }
    base.update(overrides)
    return InspectorSnapshot(**base)  # type: ignore[arg-type]


def test_inspector_formats_empty_state() -> None:
    text = build_context_inspector_text(_snap())
    assert "Session Context" in text
    assert "No file, directory, or media references recorded yet." in text
    assert "No tool activity recorded yet." in text


def test_inspector_lists_context_references() -> None:
    refs = [
        ContextReferenceView(
            badge="file",
            label="src/main.rs",
            target="/tmp/project/src/main.rs",
            source="at_mention",
            included=True,
            expanded=True,
            detail="included",
        )
    ]
    text = build_context_inspector_text(_snap(references=refs))
    assert "[file] @src/main.rs -> /tmp/project/src/main.rs" in text


def test_inspector_marks_high_context_pressure() -> None:
    bigtext = "x" * 4_000_000
    msg = Message.user(bigtext)
    text = build_context_inspector_text(_snap(api_messages=[msg]))
    assert "Context: critical" in text


def test_inspector_no_system_prompt_shows_section() -> None:
    text = build_context_inspector_text(_snap())
    assert "System Prompt Structure" in text
    assert "No system prompt set." in text


def test_inspector_blocks_format_shows_stable_prefix_and_working_set() -> None:
    blocks = [
        "## Stable Base\n\nYou are DeepSeek TUI.",
        f"{WORKING_SET_MARKER}\nsrc/main.rs changed",
    ]
    text = build_context_inspector_text(_snap(system_prompt_blocks=blocks))
    assert "System Prompt Structure" in text
    assert "Stable prefix: 1 block" in text
    assert "Volatile working set: 1 block" in text
    assert "[cache-friendly]" in text
    assert "[changes every turn]" in text
    assert "First line: ## Repo Working Set" in text


def test_inspector_blocks_without_working_set_shows_stable_only() -> None:
    blocks = [
        "## Stable Base",
        "## Personality\nCalm",
    ]
    text = build_context_inspector_text(_snap(system_prompt_blocks=blocks))
    assert "Stable prefix: 2 block(s)" in text
    assert "Volatile working set: none" in text


def test_inspector_text_prompt_shows_single_blob_and_working_marker() -> None:
    text = build_context_inspector_text(
        _snap(system_prompt="You are DeepSeek TUI.\n## Repo Working Set\nsrc/")
    )
    assert "System Prompt Structure" in text
    assert "Single text blob" in text
    assert "working-set marker" in text


def test_inspector_lists_active_tools() -> None:
    tools = [ToolDetailView(tool_name="grep", tool_id="abcdef1234567890")]
    text = build_context_inspector_text(_snap(active_tool_details=tools))
    assert "[active] grep" in text
    assert "abcdef12..." in text


def test_inspector_dedupes_repeated_references() -> None:
    ref = ContextReferenceView(
        badge="file", label="x.py", target="/tmp/project/x.py"
    )
    text = build_context_inspector_text(_snap(references=[ref, ref, ref]))
    assert text.count("[file] @x.py") == 1


def test_inspector_truncates_long_reference_list() -> None:
    refs = [
        ContextReferenceView(badge="file", label=f"f{i}", target=f"/p/{i}")
        for i in range(20)
    ]
    text = build_context_inspector_text(_snap(references=refs))
    assert "more reference(s)" in text


def test_inspector_uses_message_text_in_estimate() -> None:
    msg = Message(role="user", content=[TextBlock(text="hello world")])
    text = build_context_inspector_text(_snap(api_messages=[msg]))
    # ``ok`` because the body is tiny.
    assert "Context: ok" in text
