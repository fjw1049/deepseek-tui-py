"""Parity tests for the DeepSeek tool-name codec.

Each named test mirrors a `#[test]` block in
``crates/tui/src/client.rs::tests`` (see lines 965–1012 of the original
Rust client).

Cross-reference table:

| Python test                              | Rust test                                |
|------------------------------------------|------------------------------------------|
| test_roundtrip_dot                       | tool_name_roundtrip_dot                  |
| test_decode_mangled_dot_prefix           | tool_name_decode_mangled_dot_prefix      |
| test_decode_bare_hex_no_trailing_dash    | tool_name_decode_bare_hex_no_trailing... |
| test_bare_hex_preserves_alnum            | tool_name_bare_hex_preserves_alnum       |
| test_bare_hex_preserves_underscore       | tool_name_bare_hex_preserves_underscore  |
| test_roundtrip_colon                     | tool_name_roundtrip_colon                |
"""

from __future__ import annotations

import pytest

from deepseek_tui.tools.encoding import from_api_tool_name, to_api_tool_name

# ---------------------------------------------------------------------------
# Direct ports of the seven Rust assertions.
# ---------------------------------------------------------------------------


def test_roundtrip_dot() -> None:
    original = "multi_tool_use.parallel"
    encoded = to_api_tool_name(original)
    assert encoded == "multi_tool_use-x00002E-parallel"
    assert from_api_tool_name(encoded) == original


def test_decode_mangled_dot_prefix() -> None:
    """Model swapped the leading `-` of `-x00002E-` for `.`."""
    mangled = "multi_tool_use.x00002E-parallel"
    assert from_api_tool_name(mangled) == "multi_tool_use..parallel"


def test_decode_bare_hex_no_trailing_dash() -> None:
    """Model dropped both delimiter dashes; bare `x00002E` survives."""
    mangled = "foo_x00002Ebar"
    assert from_api_tool_name(mangled) == "foo_.bar"


def test_bare_hex_preserves_alnum() -> None:
    """U+41 = 'A' is alphanumeric — must NOT be decoded by the bare pass."""
    text = "foox000041bar"
    assert from_api_tool_name(text) == text


def test_bare_hex_preserves_underscore() -> None:
    """U+5F = '_' — must NOT be decoded by the bare pass."""
    text = "foox00005Fbar"
    assert from_api_tool_name(text) == text


def test_roundtrip_colon() -> None:
    original = "mcp__server:tool_name"
    encoded = to_api_tool_name(original)
    assert from_api_tool_name(encoded) == original


# ---------------------------------------------------------------------------
# Extra Python-side coverage that goes beyond the 7 Rust cases.
# These exist to lock behavior at the Unicode-plane edges and around the
# "mixed delimiter + bare" scenarios the Rust comment talks about.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name",
    [
        "simple",
        "with_underscore",
        "with-hyphen",
        "many--hyphens---in-a-row",
        "tool.dot",
        "tool:colon",
        "tool/slash",
        "tool space",
        "tool@at",
        "tool#hash",
        "工具中文",  # CJK
        "tool🙂emoji",  # supplementary plane (U+1F642)
        "tool​lz",  # zero-width space (U+200B)
        "MixOfEverything-_.:!? 工具🙂",
    ],
)
def test_roundtrip_arbitrary_strings(tool_name: str) -> None:
    encoded = to_api_tool_name(tool_name)
    assert from_api_tool_name(encoded) == tool_name


def test_encode_uses_six_digit_uppercase_hex() -> None:
    # '.' is U+2E. The literal must be `-x00002E-`, NOT `-x2e-` or `-x2E-`.
    assert to_api_tool_name(".") == "-x00002E-"
    # An emoji forces 5-digit codepoint that still gets padded to 6.
    # 🙂 is U+1F642.
    assert to_api_tool_name("🙂") == "-x01F642-"


def test_encode_only_hyphen_doubles() -> None:
    assert to_api_tool_name("a-b-c") == "a--b--c"
    assert to_api_tool_name("---") == "------"


def test_decode_double_hyphen_is_single_hyphen() -> None:
    # Pass 1 collapses `--` → `-`.
    assert from_api_tool_name("a--b--c") == "a-b-c"


def test_decode_lone_trailing_hyphen() -> None:
    # An unpaired `-` at end of string must be emitted verbatim, not eaten.
    assert from_api_tool_name("foo-") == "foo-"


def test_decode_invalid_hex_escape_is_passthrough() -> None:
    # `-xZZZZZZ-` cannot be decoded — Rust emits `-x` + the body.
    out = from_api_tool_name("ab-xZZZZZZ-cd")
    # The `-` after the body is then a fresh delimiter, not part of an escape.
    assert out == "ab-xZZZZZZ-cd"


def test_decode_short_hex_escape_is_passthrough() -> None:
    # Only 4 hex chars after `-x` — Rust reads what is there and emits
    # `-x` + the partial body unchanged.
    assert from_api_tool_name("foo-x002E") == "foo-x002E"


def test_mixed_delimited_and_bare() -> None:
    # First piece is a clean delimited escape, second piece is bare.
    text = "a-x00002E-b_x00002Ec"
    # Pass 1 decodes `-x00002E-` → `.`; Pass 2 decodes the bare
    # `x00002E` (U+2E, '.') because '.' is non-passthrough.
    assert from_api_tool_name(text) == "a.b_.c"


def test_bare_hex_unicode_supplementary_plane() -> None:
    # Bare `x01F642` should decode to 🙂, since 🙂 is non-passthrough.
    assert from_api_tool_name("foox01F642bar") == "foo🙂bar"


def test_bare_hex_invalid_codepoint_is_passthrough() -> None:
    # U+110000 is above the Unicode max — must NOT be decoded.
    assert from_api_tool_name("foox110000bar") == "foox110000bar"


def test_bare_hex_surrogate_is_passthrough() -> None:
    # U+D800 is a high-surrogate, not a valid Unicode scalar.
    assert from_api_tool_name("foox00D800bar") == "foox00D800bar"
