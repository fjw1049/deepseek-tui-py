"""SSE (Server-Sent Events) support for streaming responses.

Mirrors the SSE framing used by Rust app-server. Each envelope contains
an ``event:`` field (the tagged-union discriminator) and a ``data:``
field (the payload JSON), terminated by a blank line.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any


def format_sse(payload: dict[str, Any]) -> str:
    """Render one SSE envelope from a plain dict.

    If ``payload['event']`` is present it becomes the ``event:`` field;
    everything else is JSON-encoded under ``data:``.
    """
    event_name = payload.get("event")
    if isinstance(event_name, str) and event_name:
        return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
    return f"data: {json.dumps(payload)}\n\n"


async def iter_sse(source: AsyncIterable[dict[str, Any]]) -> AsyncIterator[str]:
    """Lift an async iterable of event dicts into SSE-framed strings."""
    async for envelope in source:
        yield format_sse(envelope)
