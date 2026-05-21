"""Deterministic JSON argument repair ladder.

Mirrors ``crates/tui/src/tools/arg_repair.rs``.

LLM streaming can produce malformed JSON in tool call arguments:
- Truncated streams → unclosed braces/brackets
- Control characters (0x00-0x1F) inside string values
- Trailing commas before } or ]
- Excess closing delimiters from delta corruption

The repair ladder attempts increasingly aggressive fixes, guaranteeing
a valid dict is always returned (worst case: empty {}).
"""

from __future__ import annotations

import json
import re

# Max input size — beyond this we bail to {} to avoid pathological regex.
_MAX_INPUT_BYTES = 1_048_576  # 1 MiB


def repair(raw: str) -> dict:
    """Attempt to parse *raw* as JSON, applying repairs if needed.

    Always returns a dict. Never raises.
    """
    if not raw or not raw.strip():
        return {}

    if len(raw) > _MAX_INPUT_BYTES:
        return {}

    # Stage 1: strict parse
    result = _try_parse(raw)
    if result is not None:
        return result

    # Stage 2: strip control chars inside string values
    cleaned = _strip_control_chars_in_strings(raw)
    if cleaned != raw:
        result = _try_parse(cleaned)
        if result is not None:
            return result
    else:
        cleaned = raw

    # Stage 3: strip trailing commas before } or ]
    no_trailing = _strip_trailing_commas(cleaned)
    if no_trailing != cleaned:
        result = _try_parse(no_trailing)
        if result is not None:
            return result
    else:
        no_trailing = cleaned

    # Stage 4: balance braces/brackets
    balanced = _balance_braces(no_trailing)
    if balanced != no_trailing:
        result = _try_parse(balanced)
        if result is not None:
            return result

    # Stage 5: strip excess closers
    stripped = _strip_excess_closers(no_trailing)
    if stripped != no_trailing:
        result = _try_parse(stripped)
        if result is not None:
            return result

    # Fallback: empty object
    return {}


def _try_parse(s: str) -> dict | None:
    """Return parsed dict or None."""
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(obj, dict):
        return obj
    # Non-dict JSON (e.g. array, scalar) — wrap it
    return {"value": obj}


def _strip_control_chars_in_strings(s: str) -> str:
    """Remove 0x00-0x1F (except \\t \\n \\r) that appear inside JSON strings."""
    out: list[str] = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue
        if ch == '\\' and in_string:
            out.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ord(ch) < 0x20 and ch not in ('\t', '\n', '\r'):
            continue  # drop control char
        out.append(ch)
    return "".join(out)


# Pattern: comma followed by optional whitespace then } or ]
_TRAILING_COMMA_RE = re.compile(r',\s*([}\]])')


def _strip_trailing_commas(s: str) -> str:
    """Remove trailing commas before closing delimiters."""
    return _TRAILING_COMMA_RE.sub(r'\1', s)


def _balance_braces(s: str) -> str:
    """Append missing closing braces/brackets."""
    stack: list[str] = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append('}' if ch == '{' else ']')
        elif ch in ('}', ']'):
            if stack and stack[-1] == ch:
                stack.pop()
    # Append missing closers in reverse order
    if stack:
        return s + "".join(reversed(stack))
    return s


def _strip_excess_closers(s: str) -> str:
    """Remove excess } or ] that have no matching opener."""
    stack: list[str] = []
    keep: list[bool] = [True] * len(s)
    in_string = False
    escape_next = False
    for i, ch in enumerate(s):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
            else:
                keep[i] = False
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()
            else:
                keep[i] = False
    if all(keep):
        return s
    return "".join(ch for ch, k in zip(s, keep) if k)