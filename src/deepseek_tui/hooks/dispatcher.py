"""Hook dispatcher for broadcasting events to multiple sinks."""

from __future__ import annotations

import logging

from deepseek_tui.hooks.events import HookEvent
from deepseek_tui.hooks.sinks import HookSink

logger = logging.getLogger(__name__)


class HookDispatcher:
    """Broadcast hook events to multiple sinks."""

    def __init__(self) -> None:
        self.sinks: list[HookSink] = []

    def add_sink(self, sink: HookSink) -> None:
        """Register a sink."""
        self.sinks.append(sink)

    async def emit(self, event: HookEvent) -> None:
        """Emit event to all sinks (best-effort)."""
        for sink in self.sinks:
            try:
                await sink.emit(event)
            except Exception:
                logger.warning(
                    "hook sink emit failed sink=%s event=%s",
                    type(sink).__name__,
                    type(event).__name__,
                    exc_info=True,
                )
