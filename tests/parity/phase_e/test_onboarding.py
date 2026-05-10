"""Onboarding screen parity tests.

Mirror Rust ``mask_key`` / ``is_onboarded`` / ``mark_onboarded``
helpers in ``crates/tui/src/tui/onboarding/``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from deepseek_tui.tui.screens.onboarding import (
    is_onboarded,
    mark_onboarded,
    mask_key,
)


def test_mask_key_empty() -> None:
    """Mirror Rust ``mask_key`` empty-string branch."""
    assert mask_key("") == ""
    assert mask_key("   ") == ""


def test_mask_key_short() -> None:
    """Keys ≤ 4 chars become full-asterisk."""
    assert mask_key("abc") == "***"
    assert mask_key("abcd") == "****"


def test_mask_key_long_keeps_last_four() -> None:
    """Keys > 4 chars expose only the last 4 — mirror Rust behaviour."""
    assert mask_key("sk-1234567890abcd") == "*************abcd"
    assert mask_key("ABCDEFGH") == "****EFGH"


def test_is_onboarded_false_when_no_marker(tmp_path: Path) -> None:
    with patch("deepseek_tui.tui.screens.onboarding.default_marker_path",
               return_value=tmp_path / "marker"):
        assert is_onboarded() is False


def test_mark_onboarded_creates_marker(tmp_path: Path) -> None:
    target = tmp_path / "marker"
    with patch("deepseek_tui.tui.screens.onboarding.default_marker_path",
               return_value=target):
        path = mark_onboarded()
        assert path == target
        assert target.exists()
        assert target.read_text() == ""
