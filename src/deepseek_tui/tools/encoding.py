from __future__ import annotations

import re

_ALLOWED_PATTERN = re.compile(r"[^a-zA-Z0-9_]")


def to_api_tool_name(name: str) -> str:
    encoded = _ALLOWED_PATTERN.sub("_", name)
    return re.sub(r"_+", "_", encoded).strip("_")


def from_api_tool_name(name: str) -> str:
    return name
