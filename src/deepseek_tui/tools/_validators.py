"""Shared input validation helpers for tool implementations.

Extracted from per-tool duplicates to reduce ~100 lines of redundancy
across 12+ tool files.
"""
from __future__ import annotations

from typing import Any

from deepseek_tui.tools.base import ToolError


def require_string(input_data: dict[str, object], key: str) -> str:
    """Extract a required string parameter or raise ToolError."""
    value = input_data.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
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
    """Extract an optional integer parameter or raise ToolError if wrong type."""
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
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
