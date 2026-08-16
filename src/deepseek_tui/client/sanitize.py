"""Last-mile hardening for config-supplied ``extra_body`` / ``extra_headers``.

Provider configuration may inject extra request-body keys and HTTP headers.
Project-level config strips them outright (see ``config.loader``), but
user-level (or phished) config can still carry them — so the clients apply
a hard block at the point of use: keys that could hijack the conversation
body or credentials are dropped with a warning instead of failing startup.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: ``extra_body`` keys that define the conversation itself — never overridable.
BLOCKED_EXTRA_BODY_KEYS = frozenset(
    {"messages", "tools", "tool_choice", "model", "stream", "system"}
)

#: Credential-carrying headers — never overridable (matched case-insensitively).
BLOCKED_EXTRA_HEADER_NAMES = frozenset({"authorization", "x-api-key", "cookie"})


def sanitize_extra_body(extra_body: dict[str, Any]) -> dict[str, Any]:
    """Return ``extra_body`` minus keys that would override the request core."""
    safe: dict[str, Any] = {}
    for key, value in extra_body.items():
        if key in BLOCKED_EXTRA_BODY_KEYS:
            logger.warning("extra_body key %r ignored (blocked)", key)
            continue
        safe[key] = value
    return safe


def sanitize_extra_headers(extra_headers: dict[str, str]) -> dict[str, str]:
    """Return ``extra_headers`` minus credential-carrying entries."""
    safe: dict[str, str] = {}
    for name, value in extra_headers.items():
        if name.lower() in BLOCKED_EXTRA_HEADER_NAMES:
            logger.warning("extra_headers entry %r ignored (blocked)", name)
            continue
        safe[name] = value
    return safe
