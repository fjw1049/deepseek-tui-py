"""Tool-name codec for the DeepSeek (OpenAI-compatible) Chat Completions API.

Behavioral parity with the Rust implementation at
``crates/tui/src/client.rs:25-112`` of the original DeepSeek-TUI project.

The provider only accepts ``[A-Za-z0-9_-]`` in tool names, so any other
character must be escaped. Rust uses a reversible scheme:

* ``-`` → ``--``
* any other non-``[A-Za-z0-9_]`` char ``c`` →
  ``-x{codepoint:06X}-`` (six upper-case hex digits, dash-delimited)

Decoding is split into two passes:

1. **Delimiter-based pass** (`-x000041-` form): handles correctly
   formed escapes and ``--`` → ``-``.
2. **Bare hex pass**: real DeepSeek models occasionally mangle the
   delimiter form, e.g. ``-x00002E-`` → ``.x00002E-`` or ``x00002E``.
   This pass scans for bare ``x[0-9A-Fa-f]{6}-?`` sequences and decodes
   only those whose target character is one ``to_api_tool_name`` would
   have encoded (i.e. NOT alphanumeric, ``_`` or ``-``). This avoids
   accidentally rewriting innocent strings like ``foox000041bar``
   (where ``x000041`` would map back to ``A``).
"""

from __future__ import annotations

import re

__all__ = ["from_api_tool_name", "to_api_tool_name"]


# Regex for the bare-hex fallback pass. Group 1 is the 6-hex-digit body.
# Trailing dash, if present, is consumed by the regex itself.
_BARE_HEX_RE = re.compile(r"x([0-9A-Fa-f]{6})-?")


def _is_passthrough(ch: str) -> bool:
    """True if `ch` is a single character that needs no escaping."""
    return ch.isascii() and (ch.isalnum() or ch == "_")


def to_api_tool_name(name: str) -> str:
    """Encode a Python tool name into the provider-safe wire form.

    Mirrors `to_api_tool_name` in `crates/tui/src/client.rs:25-39`.
    """
    parts: list[str] = []
    for ch in name:
        if _is_passthrough(ch):
            parts.append(ch)
        elif ch == "-":
            parts.append("--")
        else:
            parts.append(f"-x{ord(ch):06X}-")
    return "".join(parts)


def from_api_tool_name(name: str) -> str:
    """Decode a provider-emitted tool name back to its original form.

    Mirrors `from_api_tool_name` in `crates/tui/src/client.rs:41-86`,
    plus the bare-hex fallback at L91-112.
    """
    return _decode_bare_hex_escapes(_decode_delimited(name))


def _decode_delimited(name: str) -> str:
    """Pass 1: handle ``--`` → ``-`` and ``-xHHHHHH-`` → char."""
    out: list[str] = []
    chars = list(name)
    i = 0
    n = len(chars)
    while i < n:
        ch = chars[i]
        if ch != "-":
            out.append(ch)
            i += 1
            continue
        # ch == '-'
        if i + 1 < n and chars[i + 1] == "-":
            out.append("-")
            i += 2
            continue
        if i + 1 < n and chars[i + 1] == "x":
            # Try to read up to 6 hex chars after `-x`.
            hex_start = i + 2
            hex_end = min(hex_start + 6, n)
            hex_str = "".join(chars[hex_start:hex_end])
            decoded_char = _safe_hex_to_char(hex_str)
            if decoded_char is not None:
                # Successful escape: optionally consume one trailing `-`.
                cursor = hex_end
                if cursor < n and chars[cursor] == "-":
                    cursor += 1
                out.append(decoded_char)
                i = cursor
                continue
            # Decode failed: emit `-x` + however many hex chars we read,
            # then advance past them. Matches Rust which appends `-x` +
            # the partial hex body and continues.
            out.append("-")
            out.append("x")
            out.append(hex_str)
            i = hex_end
            continue
        # `-` followed by something other than `-` or `x`, or at EOS.
        out.append("-")
        i += 1
    return "".join(out)


def _decode_bare_hex_escapes(text: str) -> str:
    """Pass 2: decode bare ``xHHHHHH-?`` sequences.

    Only decode if the resulting character would itself have been
    escaped by `to_api_tool_name` (i.e. it is NOT ASCII alnum, ``_`` or
    ``-``). Otherwise leave the match untouched.
    """

    def _replace(match: re.Match[str]) -> str:
        hex_body = match.group(1)
        decoded = _safe_hex_to_char(hex_body)
        if decoded is None:
            return match.group(0)
        # Mirror the Rust gating at L104: only decode if `decoded` is a
        # character that `to_api_tool_name` would itself have encoded.
        if decoded.isascii() and (decoded.isalnum() or decoded == "_"):
            return match.group(0)
        if decoded == "-":
            return match.group(0)
        return decoded

    return _BARE_HEX_RE.sub(_replace, text)


def _safe_hex_to_char(hex_str: str) -> str | None:
    """Parse a 6-digit hex string into a single Unicode character.

    Returns None for: short input, non-hex, surrogate codepoints
    (U+D800–U+DFFF), or values above U+10FFFF.
    """
    if len(hex_str) != 6:
        return None
    try:
        code = int(hex_str, 16)
    except ValueError:
        return None
    if code > 0x10FFFF:
        return None
    if 0xD800 <= code <= 0xDFFF:
        # UTF-16 surrogates are not valid Unicode scalars.
        return None
    return chr(code)
