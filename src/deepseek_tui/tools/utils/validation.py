"""Shared input validation helpers for tool implementations.

Extracted from per-tool duplicates to reduce ~100 lines of redundancy
across 12+ tool files.
"""

from __future__ import annotations


from typing import Any

from deepseek_tui.tools.registry import ToolError


def require_string(input_data: dict[str, object], key: str) -> str:
    """Extract a required string parameter or raise ToolError."""
    value = input_data.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def require_nonempty_string(input_data: dict[str, object], key: str) -> str:
    """Extract a required non-empty string parameter or raise ToolError."""
    value = input_data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"'{key}' must be a non-empty string")
    return value


def optional_string(input_data: dict[str, object], key: str) -> str | None:
    """Extract an optional string parameter or raise ToolError if wrong type."""
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def optional_int(input_data: dict[str, object], key: str) -> int | None:
    """Extract an optional integer parameter or raise ToolError if wrong type.

    ``bool`` is rejected: it is an ``int`` subclass but never a valid count
    or offset from the model.
    """
    value = input_data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
    return value


def optional_non_negative_int(input_data: dict[str, object], key: str) -> int | None:
    """Optional integer that must be >= 0; ``bool`` is rejected."""
    value = optional_int(input_data, key)
    if value is not None and value < 0:
        raise ToolError(f"{key} must be a non-negative integer")
    return value


def optional_bool(data: dict[str, Any], key: str) -> bool | None:
    """Extract an optional boolean parameter or raise ToolError if wrong type."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ToolError(f"{key} must be a boolean")
    return value


def optional_string_list(
    input_data: dict[str, object], key: str
) -> list[str] | None:
    """Extract an optional list of strings or raise ToolError if wrong type."""
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolError(f"{key} must be a list of strings")
    return value


def pick_str(data: dict[str, Any], *keys: str) -> str | None:
    """First non-empty string among ``keys``."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def pick_bool(data: dict[str, Any], *keys: str, default: bool = False) -> bool:
    """First real bool among ``keys`` (bools only; no truthy coercion)."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            return value
    return default


def pick_int(data: dict[str, Any], *keys: str, default: int | None = None) -> int | None:
    """First non-bool int among ``keys``."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return default
