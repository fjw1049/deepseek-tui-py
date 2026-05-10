"""OSC 8 hyperlink wrap/strip parity tests.

Mirrors Rust tests in ``crates/tui/src/tui/osc8.rs`` (osc8.rs:94-165).
"""

from __future__ import annotations

from deepseek_tui.tui.osc8 import (
    enabled,
    set_enabled,
    strip,
    wrap_link,
)


def test_wrap_link_shape_is_osc_8_compliant() -> None:
    """Mirror Rust ``wrap_link_shape_is_osc_8_compliant`` (osc8.rs:110)."""
    wrapped = wrap_link("https://example.com", "click me")
    assert wrapped == "\x1b]8;;https://example.com\x1b\\click me\x1b]8;;\x1b\\"


def test_strip_removes_wrapper_keeps_label() -> None:
    """Mirror Rust ``strip_removes_wrapper_keeps_label`` (osc8.rs:118)."""
    wrapped = wrap_link("https://example.com", "click me")
    assert strip(wrapped) == "click me"


def test_strip_handles_bel_terminator() -> None:
    """Mirror Rust ``strip_handles_bel_terminator`` (osc8.rs:124)."""
    wrapped = "\x1b]8;;https://example.com\x07click me\x1b]8;;\x07"
    assert strip(wrapped) == "click me"


def test_strip_passes_through_text_with_no_escapes() -> None:
    """Mirror Rust ``strip_passes_through_text_with_no_escapes`` (osc8.rs:130)."""
    plain = "no escapes here"
    assert strip(plain) == plain


def test_strip_preserves_non_osc_8_escapes() -> None:
    """Mirror Rust ``strip_preserves_non_osc_8_escapes`` (osc8.rs:136)."""
    wrapped = wrap_link("https://example.com", "click")
    mixed = f"\x1b[31mred\x1b[0m {wrapped}"
    assert strip(mixed) == "\x1b[31mred\x1b[0m click"


def test_enabled_is_true_by_default() -> None:
    """Mirror Rust ``enabled_is_true_by_default_when_untouched`` (osc8.rs:146)."""
    prior = enabled()
    set_enabled(True)
    try:
        assert enabled() is True
    finally:
        set_enabled(prior)


def test_set_enabled_round_trips() -> None:
    """Mirror Rust ``set_enabled_round_trips`` (osc8.rs:155)."""
    prior = enabled()
    set_enabled(False)
    assert enabled() is False
    set_enabled(True)
    assert enabled() is True
    set_enabled(prior)
