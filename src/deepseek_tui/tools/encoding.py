"""Tool encoding, deprecation, and schema sanitization.

Consolidates encoding.py, deprecation.py, schema_sanitize.py.
"""

from __future__ import annotations



# Tool-name codec for the DeepSeek (OpenAI-compatible) Chat Completions API.
#
# Behavioral parity with the Rust implementation at
# ``crates/tui/src/client.rs:25-112`` of the original DeepSeek-TUI project.
#
# The provider only accepts ``[A-Za-z0-9_-]`` in tool names, so any other
# character must be escaped. Rust uses a reversible scheme:
#
# * ``-`` → ``--``
# * any other non-``[A-Za-z0-9_]`` char ``c`` →
#   ``-x{codepoint:06X}-`` (six upper-case hex digits, dash-delimited)
#
# Decoding is split into two passes:
#
# 1. **Delimiter-based pass** (`-x000041-` form): handles correctly
#    formed escapes and ``--`` → ``-``.
# 2. **Bare hex pass**: real DeepSeek models occasionally mangle the
#    delimiter form, e.g. ``-x00002E-`` → ``.x00002E-`` or ``x00002E``.
#    This pass scans for bare ``x[0-9A-Fa-f]{6}-?`` sequences and decodes
#    only those whose target character is one ``to_api_tool_name`` would
#    have encoded (i.e. NOT alphanumeric, ``_`` or ``-``). This avoids
#    accidentally rewriting innocent strings like ``foox000041bar``
#    (where ``x000041`` would map back to ``A``).
#
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


# Deprecated tool alias notices — mirrors Rust ``wrap_with_deprecation_notice``.
from dataclasses import replace

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext


def deprecation_notice(alias: str, canonical: str) -> dict[str, str]:
    return {
        "this_tool": alias,
        "use_instead": canonical,
        "removed_in": "0.8.0",
        "message": (
            f"Tool '{alias}' is deprecated; switch to '{canonical}' before v0.8.0."
        ),
    }


def attach_deprecation(result: ToolResult, alias: str, canonical: str) -> ToolResult:
    metadata = dict(result.metadata)
    metadata["_deprecation"] = deprecation_notice(alias, canonical)
    return replace(result, metadata=metadata)


class DeprecatingAliasTool(ToolSpec):
    """Delegate to *inner* but expose *alias_name* and stamp deprecation metadata."""

    def __init__(
        self,
        inner: ToolSpec,
        alias_name: str,
        canonical_name: str,
    ) -> None:
        self._inner = inner
        self._alias = alias_name
        self._canonical = canonical_name

    def name(self) -> str:
        return self._alias

    def description(self) -> str:
        return (
            f"Compatibility alias for {self._canonical}. "
            f"Use {self._canonical} instead."
        )

    def input_schema(self) -> dict[str, object]:
        return self._inner.input_schema()

    def capabilities(self) -> list[ToolCapability]:
        return self._inner.capabilities()

    def approval_requirement(self) -> ApprovalRequirement:
        return self._inner.approval_requirement()

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        result = await self._inner.execute(input_data, context)
        return attach_deprecation(result, self._alias, self._canonical)


# JSON Schema sanitizer for DeepSeek strict function calling.
#
# Mirrors ``crates/tui/src/tools/schema_sanitize.rs``.
#
# Pydantic-generated schemas contain patterns that DeepSeek's strict mode
# rejects:
#   - ``anyOf: [X, {type: "null"}]`` for Optional fields
#   - bare ``{type: "object"}`` without ``properties``
#   - ``required`` entries not present in ``properties``
#   - single-element ``oneOf`` / ``allOf`` wrappers
#
# This module normalizes schemas in-place so strict mode can be enabled
# without hand-editing tool definitions.
#
from typing import Any


def sanitize(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize *schema* for DeepSeek compatibility. Idempotent."""
    _walk(schema)
    return schema


def sanitize_for_strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize and enforce strict-mode requirements.

    Adds ``additionalProperties: false`` and marks all properties as
    required on every object sub-schema.
    """
    _walk(schema, strict=True)
    return schema


def prepare_tools_for_strict_mode(
    tools: list[dict[str, Any]],
) -> bool:
    """Sanitize all tool schemas for strict mode.

    Returns False if any tool has a root-level ``anyOf``/``oneOf``/``allOf``
    that cannot be collapsed (incompatible with strict). Otherwise sanitizes
    all tools and returns True.
    """
    for tool in tools:
        fn = tool.get("function", {})
        params = fn.get("parameters")
        if not isinstance(params, dict):
            continue
        # Root-level composition → incompatible with strict
        for key in ("anyOf", "oneOf", "allOf"):
            val = params.get(key)
            if isinstance(val, list) and len(val) > 1:
                return False

    for tool in tools:
        fn = tool.get("function", {})
        params = fn.get("parameters")
        if isinstance(params, dict):
            sanitize_for_strict(params)
    return True


# ---------------------------------------------------------------------------
# Internal recursive walker
# ---------------------------------------------------------------------------


def _walk(schema: dict[str, Any], *, strict: bool = False) -> None:
    """Recursively normalize a JSON schema dict."""
    # 1. Collapse nullable anyOf: [X, {type: "null"}] → X
    _collapse_nullable_union(schema)

    # 2. Collapse single-element oneOf / allOf
    _collapse_single_composition(schema)

    # 3. Inject properties on bare objects
    if schema.get("type") == "object" and "properties" not in schema:
        schema["properties"] = {}

    # 4. Prune dangling required entries
    _prune_dangling_required(schema)

    # 5. Strict mode additions
    if strict and schema.get("type") == "object":
        schema["additionalProperties"] = False
        props = schema.get("properties", {})
        if props:
            schema["required"] = list(props.keys())

    # Recurse into sub-schemas
    props = schema.get("properties")
    if isinstance(props, dict):
        for sub in props.values():
            if isinstance(sub, dict):
                _walk(sub, strict=strict)

    items = schema.get("items")
    if isinstance(items, dict):
        _walk(items, strict=strict)

    for key in ("anyOf", "oneOf", "allOf"):
        variants = schema.get(key)
        if isinstance(variants, list):
            for v in variants:
                if isinstance(v, dict):
                    _walk(v, strict=strict)


def _collapse_nullable_union(schema: dict[str, Any]) -> None:
    """Collapse ``anyOf: [X, {type: "null"}]`` → X merged into schema."""
    any_of = schema.get("anyOf")
    if not isinstance(any_of, list):
        return
    if len(any_of) != 2:
        return

    null_idx = -1
    for i, variant in enumerate(any_of):
        if isinstance(variant, dict) and variant.get("type") == "null":
            null_idx = i
            break

    if null_idx == -1:
        return

    # The other variant is the real type
    real = any_of[1 - null_idx]
    if not isinstance(real, dict):
        return

    # Remove anyOf and merge the real type into schema
    del schema["anyOf"]
    for k, v in real.items():
        schema[k] = v


def _collapse_single_composition(schema: dict[str, Any]) -> None:
    """Collapse single-element oneOf/allOf into the schema."""
    for key in ("oneOf", "allOf"):
        variants = schema.get(key)
        if isinstance(variants, list) and len(variants) == 1:
            single = variants[0]
            if isinstance(single, dict):
                del schema[key]
                for k, v in single.items():
                    schema[k] = v


def _prune_dangling_required(schema: dict[str, Any]) -> None:
    """Remove required entries not present in properties."""
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        return
    valid = [r for r in required if r in properties]
    if valid:
        schema["required"] = valid
    else:
        del schema["required"]
