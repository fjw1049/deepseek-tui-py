"""Wait for blocking TUI work to finish before releasing its owner."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")


async def run_io(function: Callable[_P, _R], *args: _P.args, **kwargs: _P.kwargs) -> _R:
    """Keep a worker owned even if its caller is cancelled during an OS operation."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        if not task.cancelled():
            task.exception()
        raise
