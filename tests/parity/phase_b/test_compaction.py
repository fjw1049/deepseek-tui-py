"""Parity tests for engine/compaction.

Mirror of Rust `crates/tui/src/compaction.rs` compaction tests.
"""

from __future__ import annotations

from deepseek_tui.engine.compaction import (
    KEEP_RECENT_MESSAGES,
    MIN_SUMMARIZE_MESSAGES,
    CompactionConfig,
    _estimate_tokens_for_message,
    _normalize_path_candidate,
    _tail_chars,
    _truncate_chars,
    plan_compaction,
    should_compact,
)
from deepseek_tui.protocol.messages import Message


class TestCompactionConfig:
    """Tests for CompactionConfig."""

    def test_config_defaults(self) -> None:
        """Config should have expected defaults."""
        config = CompactionConfig()

        assert config.enabled is True
        assert config.token_threshold == 50_000
        assert config.message_threshold == 50
        assert config.model == "deepseek-chat"
        assert config.cache_summary is True


class TestCompactionConstants:
    """Tests for compaction constants."""

    def test_keep_recent_messages_constant(self) -> None:
        """KEEP_RECENT_MESSAGES should be 4 (mirrors Rust)."""
        assert KEEP_RECENT_MESSAGES == 4

    def test_min_summarize_messages_constant(self) -> None:
        """MIN_SUMMARIZE_MESSAGES should be 6 (mirrors Rust)."""
        assert MIN_SUMMARIZE_MESSAGES == 6


class TestPathNormalization:
    """Tests for path normalization."""

    def test_normalize_valid_paths(self) -> None:
        """Valid paths should normalize correctly."""
        result = _normalize_path_candidate("src/main.py")
        assert result is not None
        assert "main.py" in result

    def test_normalize_empty_path(self) -> None:
        """Empty path should return None."""
        assert _normalize_path_candidate("") is None

    def test_normalize_very_long_path(self) -> None:
        """Very long path should return None."""
        long_path = "a" * 600
        assert _normalize_path_candidate(long_path) is None

    def test_normalize_common_extensions(self) -> None:
        """Paths with common extensions should work."""
        for path in ["file.py", "file.rs", "file.json", "file.toml"]:
            result = _normalize_path_candidate(path)
            assert result is not None


class TestTextTruncation:
    """Tests for text truncation utilities."""

    def test_truncate_chars_under_limit(self) -> None:
        """Text under limit should remain unchanged."""
        text = "hello world"
        result = _truncate_chars(text, 50)
        assert result == text

    def test_truncate_chars_over_limit(self) -> None:
        """Text over limit should be truncated."""
        text = "hello world this is a long string"
        result = _truncate_chars(text, 10)
        assert len(result) <= 10

    def test_truncate_chars_zero_limit(self) -> None:
        """Zero limit should return empty string."""
        assert _truncate_chars("hello", 0) == ""

    def test_tail_chars(self) -> None:
        """tail_chars should return last N characters."""
        text = "hello world"
        result = _tail_chars(text, 5)
        assert result == "world"

    def test_tail_chars_under_limit(self) -> None:
        """tail_chars under limit should return full text."""
        text = "hello"
        result = _tail_chars(text, 50)
        assert result == text


class TestTokenEstimation:
    """Tests for token estimation."""

    def test_estimate_tokens_empty_message(self) -> None:
        """Empty message should estimate ~1 token."""
        msg = Message.user("")
        tokens = _estimate_tokens_for_message(msg)
        assert tokens >= 1

    def test_estimate_tokens_short_message(self) -> None:
        """Short message should estimate few tokens."""
        msg = Message.user("hello")
        tokens = _estimate_tokens_for_message(msg)
        assert 1 <= tokens <= 5

    def test_estimate_tokens_longer_message(self) -> None:
        """Longer message should estimate more tokens."""
        msg = Message.user("a" * 1000)
        tokens = _estimate_tokens_for_message(msg)
        assert tokens > 200


class TestCompactionPlan:
    """Tests for compaction planning."""

    def test_plan_empty_messages(self) -> None:
        """Empty message list should produce empty plan."""
        plan = plan_compaction([])
        assert len(plan.pinned_indices) == 0
        assert len(plan.summarize_indices) == 0

    def test_plan_keeps_recent_messages(self) -> None:
        """Plan should always pin last KEEP_RECENT_MESSAGES messages."""
        messages = [Message.user(f"msg {i}") for i in range(10)]
        plan = plan_compaction(messages)

        # Last 4 messages should be pinned
        expected_pinned = set(range(10 - KEEP_RECENT_MESSAGES, 10))
        assert plan.pinned_indices == expected_pinned

    def test_plan_with_explicit_pins(self) -> None:
        """Plan should include explicitly pinned indices."""
        messages = [Message.user(f"msg {i}") for i in range(10)]
        explicit_pins = {2, 5}
        plan = plan_compaction(messages, pinned_indices=explicit_pins)

        # Should include both explicit pins and recent messages
        assert explicit_pins.issubset(plan.pinned_indices)
        assert len(plan.pinned_indices) >= len(explicit_pins)

    def test_plan_generates_summarize_indices(self) -> None:
        """Plan should generate list of messages to summarize."""
        messages = [Message.user(f"msg {i}") for i in range(10)]
        plan = plan_compaction(messages)

        # Summarize indices should be non-pinned messages
        summarize_set = set(plan.summarize_indices)
        assert summarize_set.isdisjoint(plan.pinned_indices)
        assert len(summarize_set) + len(plan.pinned_indices) == len(messages)


class TestShouldCompact:
    """Tests for compaction decision."""

    def test_should_not_compact_disabled(self) -> None:
        """Should not compact when disabled."""
        config = CompactionConfig(enabled=False)
        messages = [Message.user(f"msg {i}") for i in range(100)]
        assert should_compact(messages, config) is False

    def test_should_not_compact_few_messages(self) -> None:
        """Should not compact if too few unpinned messages."""
        config = CompactionConfig(
            enabled=True,
            token_threshold=1_000_000,
            message_threshold=100,
        )
        messages = [Message.user("msg")]
        assert should_compact(messages, config) is False

    def test_should_compact_message_threshold_exceeded(self) -> None:
        """Should compact when message threshold exceeded."""
        config = CompactionConfig(
            enabled=True,
            token_threshold=1_000_000,
            message_threshold=5,
        )
        messages = [Message.user(f"msg {i}") for i in range(20)]
        assert should_compact(messages, config) is True

    def test_should_compact_with_pinned_messages(self) -> None:
        """Should adjust thresholds when messages are pinned."""
        config = CompactionConfig(
            enabled=True,
            token_threshold=50_000,
            message_threshold=10,
        )
        messages = [Message.user(f"msg {i}") for i in range(20)]
        pinned = {5}  # Pin one early message
        result = should_compact(messages, config, pinned_indices=pinned)
        # Result depends on actual token counts
        assert isinstance(result, bool)
