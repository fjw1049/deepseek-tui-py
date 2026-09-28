"""Keep ownership of mutations until their cleanup has finished."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

_T = TypeVar("_T")


async def complete_before_cancel(operation: Awaitable[_T]) -> _T:
    task = asyncio.ensure_future(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        # Retrieve failures so a disconnected caller leaves no orphaned exception.
        if not task.cancelled():
            task.exception()
        raise
