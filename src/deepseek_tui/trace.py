"""Cross-call trace correlation for the logging subsystem.

Provides per-turn and per-tool-call IDs that ride implicitly on every
log record without forcing call sites to thread them through arguments.

Usage::

    from deepseek_tui.trace import bind_turn, bind_tool, current_turn

    with bind_turn() as turn_id:
        logger.info("user message accepted")
        with bind_tool("call-abc"):
            logger.info("running tool")
        # turn_id is automatically attached to log record as `turn=...`

The :class:`TraceFilter` installed by :mod:`logging_setup` reads these
context variables and rewrites the log record so the formatter prints
``[turn=ab12c34d tool=ee56f78g]`` between the level and logger name.

Mirrors the conceptual role of Rust's structured ``tracing`` spans
without bringing in a full tracing framework — for behavior-parity
testing we only need correlation, not span trees.
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

# Context variables — empty string when unset so the filter can render
# ``[turn=- tool=-]`` consistently without optional formatting branches.
_turn_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "deepseek_turn_id", default=""
)
_tool_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "deepseek_tool_id", default=""
)


def short_id() -> str:
    """Generate an 8-char hex id suitable for one turn or tool call.

    Hex (rather than e.g. base32) keeps it greppable on the command line
    and aligns with the format the engine already uses for tool_call ids.
    """
    return uuid.uuid4().hex[:8]


def current_turn() -> str:
    """Return the currently bound turn id (empty string if unbound)."""
    return _turn_id.get()


def current_tool() -> str:
    """Return the currently bound tool-call id (empty string if unbound)."""
    return _tool_id.get()


@contextmanager
def bind_turn(turn_id: str | None = None) -> Iterator[str]:
    """Bind a turn id for the duration of the ``with`` block.

    If no id is supplied a fresh 8-char hex is generated. The previously
    bound id is restored on exit even if an exception bubbles up — this
    matters for nested turns (sub-agents may run their own turns inside
    the parent's context).
    """
    tid = turn_id or short_id()
    token = _turn_id.set(tid)
    try:
        yield tid
    finally:
        _turn_id.reset(token)


@contextmanager
def bind_tool(tool_call_id: str | None = None) -> Iterator[str]:
    """Bind a tool-call id for the duration of the ``with`` block.

    Accepts either a full UUID-style id (truncated to 8 hex) or a
    pre-shortened one. Empty / None falls through to a fresh id so
    spontaneous tool runs (e.g. text-parser fallback) still correlate.
    """
    if tool_call_id:
        compact = "".join(c for c in tool_call_id if c.isalnum())[:8]
        tid = compact or short_id()
    else:
        tid = short_id()
    token = _tool_id.set(tid)
    try:
        yield tid
    finally:
        _tool_id.reset(token)


class TraceFilter(logging.Filter):
    """Inject the current trace ids onto every log record.

    The filter sets two attributes on the record:

    * ``trace_turn`` — current turn id or empty string
    * ``trace_tool`` — current tool-call id or empty string

    A pre-formatted ``trace_tag`` of the form ``[turn=ab12c34d tool=ee56f78g]``
    (with ``-`` placeholders when unbound) is also attached so the
    formatter can use a single ``%(trace_tag)s`` placeholder rather than
    duplicating the bracket logic in each format string.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        turn = current_turn() or "-"
        tool = current_tool() or "-"
        record.trace_turn = turn
        record.trace_tool = tool
        record.trace_tag = f"[turn={turn} tool={tool}]"
        return True


__all__ = [
    "TraceFilter",
    "bind_tool",
    "bind_turn",
    "current_tool",
    "current_turn",
    "short_id",
]
