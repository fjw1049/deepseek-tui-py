"""Unit tests for turn-local same-args tool-call dedup."""

from __future__ import annotations

from deepseek_tui.engine.tool_dedup import (
    REPEAT_FORCE_STOP_STREAK,
    REPEAT_REMINDER_1_START,
    ToolCallDeduplicator,
    make_tool_call_key,
)


def test_canonical_key_is_order_independent() -> None:
    a = make_tool_call_key("grep_files", {"path": "a", "pattern": "x"})
    b = make_tool_call_key("grep_files", {"pattern": "x", "path": "a"})
    assert a == b


def test_same_batch_reuse() -> None:
    dedup = ToolCallDeduplicator()
    dedup.begin_batch()
    first = dedup.classify("read_file", {"path": "a.py"})
    assert first.kind == "execute"
    dedup.record(first.key, "file body", is_error=False)

    second = dedup.classify("read_file", {"path": "a.py"})
    assert second.kind == "reuse"
    assert second.reuse_content == "file body"
    reused = dedup.reuse_content(second)
    assert "Duplicate tool call" in reused
    assert "file body" in reused


def test_cross_round_reminder_and_block() -> None:
    dedup = ToolCallDeduplicator()
    args = {"path": "a.py"}

    for _ in range(REPEAT_REMINDER_1_START - 1):
        dedup.begin_batch()
        d = dedup.classify("read_file", args)
        assert d.kind == "execute"
        content = dedup.decorate_execute_content(d, "ok")
        assert "<system-reminder>" not in content
        dedup.record(d.key, "ok", is_error=False)
        dedup.end_batch()

    dedup.begin_batch()
    d = dedup.classify("read_file", args)
    assert d.kind == "execute"
    assert d.projected_streak == REPEAT_REMINDER_1_START
    content = dedup.decorate_execute_content(d, "ok")
    assert "repeated several times" in content
    dedup.record(d.key, "ok", is_error=False)
    dedup.end_batch()

    # Drive streak up to the force-stop threshold.
    while True:
        dedup.begin_batch()
        d = dedup.classify("read_file", args)
        if d.kind == "block":
            assert d.projected_streak >= REPEAT_FORCE_STOP_STREAK
            assert "was not executed again" in dedup.block_content(d)
            break
        dedup.record(d.key, "ok", is_error=False)
        dedup.end_batch()
        assert d.projected_streak < REPEAT_FORCE_STOP_STREAK + 2


def test_different_args_reset_streak() -> None:
    dedup = ToolCallDeduplicator()
    for _ in range(4):
        dedup.begin_batch()
        d = dedup.classify("read_file", {"path": "a.py"})
        dedup.record(d.key, "a", is_error=False)
        dedup.end_batch()

    dedup.begin_batch()
    d = dedup.classify("read_file", {"path": "b.py"})
    assert d.kind == "execute"
    assert d.projected_streak == 1
    assert "<system-reminder>" not in dedup.decorate_execute_content(d, "b")


def test_reset_turn_clears_streak() -> None:
    dedup = ToolCallDeduplicator()
    for _ in range(5):
        dedup.begin_batch()
        d = dedup.classify("grep_files", {"pattern": "x"})
        dedup.record(d.key, "hits", is_error=False)
        dedup.end_batch()

    dedup.reset_turn()
    d = dedup.classify("grep_files", {"pattern": "x"})
    assert d.projected_streak == 1
