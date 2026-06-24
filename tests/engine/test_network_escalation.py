"""Tests for network_escalation per-host timeout tracking.

Pins step 4: repeated timeouts on one host within a turn must escalate
from a quiet hint to an explicit mirror/tool-swap. The counter lives on
``context.metadata`` and resets each turn (per-engine context). This is
the state behind the exec_shell timeout hint and the fetch_url timeout
hint — both call ``record_host_timeout`` / ``should_escalate``.
"""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.utils.network_escalation import (
    host_timeout_count,
    record_host_timeout,
    reset_host_timeouts,
    should_escalate,
)


def _ctx() -> ToolContext:
    return ToolContext(working_directory=Path("/tmp"))


# --- record / count ---

def test_record_increments_per_host():
    ctx = _ctx()
    url = "https://raw.githubusercontent.com/o/r/b/p.md"
    assert record_host_timeout(ctx, url) == "raw.githubusercontent.com"
    assert host_timeout_count(ctx, url) == 1
    record_host_timeout(ctx, url)
    assert host_timeout_count(ctx, url) == 2


def test_record_isolates_hosts():
    ctx = _ctx()
    raw = "https://raw.githubusercontent.com/o/r/b/p.md"
    other = "https://example.com/x"
    record_host_timeout(ctx, raw)
    record_host_timeout(ctx, other)
    assert host_timeout_count(ctx, raw) == 1
    assert host_timeout_count(ctx, other) == 1


def test_record_strips_www_prefix():
    ctx = _ctx()
    record_host_timeout(ctx, "https://www.example.com/a")
    assert host_timeout_count(ctx, "https://example.com/b") == 1


def test_record_non_http_url_returns_none():
    ctx = _ctx()
    assert record_host_timeout(ctx, "not a url") is None
    assert host_timeout_count(ctx, "not a url") == 0


# --- escalation threshold ---

def test_should_not_escalate_below_threshold():
    ctx = _ctx()
    url = "https://raw.githubusercontent.com/o/r/b/p.md"
    record_host_timeout(ctx, url)
    assert should_escalate(ctx, url) is False


def test_should_escalate_at_threshold():
    ctx = _ctx()
    url = "https://raw.githubusercontent.com/o/r/b/p.md"
    record_host_timeout(ctx, url)
    record_host_timeout(ctx, url)
    assert should_escalate(ctx, url) is True


# --- turn reset ---

def test_reset_clears_all_host_counters():
    """A turn-start reset wipes every host's counter so a prior turn's
    transient blip doesn't carry over and poison the current turn.

    The orchestrator reuses one ``tool_context`` across turns (it's an
    instance attribute, not rebuilt per turn). Without this reset, a
    host that timed out twice in turn N would start turn N+1 already at
    the escalation threshold — the first timeout in N+1 would
    immediately trigger a mirror/tool-swap suggestion.
    """
    ctx = _ctx()
    url = "https://raw.githubusercontent.com/o/r/b/p.md"
    record_host_timeout(ctx, url)
    record_host_timeout(ctx, url)
    assert should_escalate(ctx, url) is True  # precondition

    reset_host_timeouts(ctx)

    assert host_timeout_count(ctx, url) == 0
    assert should_escalate(ctx, url) is False


def test_reset_is_idempotent_on_fresh_context():
    """Resetting a context with no timeout history must not raise."""
    ctx = _ctx()
    reset_host_timeouts(ctx)  # no-op, no KeyError
    assert host_timeout_count(ctx, "https://example.com/x") == 0


def test_counter_starts_clean_on_fresh_context():
    """A new ToolContext has no history — a transient blip in a prior
    turn must not poison the host for the current turn."""
    ctx = _ctx()
    assert host_timeout_count(ctx, "https://example.com/x") == 0
    assert should_escalate(ctx, "https://example.com/x") is False


def test_cross_turn_reset_simulates_turn_boundary():
    """End-to-end simulation of the cross-turn guarantee: the same
    context object (mirroring the orchestrator's reused tool_context)
    accumulates timeouts during turn 1, but after the turn-start
    reset that ``_handle_send_message_inner`` calls, turn 2 starts
    clean — a single new timeout does NOT escalate."""
    ctx = _ctx()
    url = "https://example.com/file.txt"

    # Turn 1: two timeouts on example.com → would escalate.
    record_host_timeout(ctx, url)
    record_host_timeout(ctx, url)
    assert should_escalate(ctx, url) is True

    # Turn boundary: orchestrator calls reset_host_timeouts.
    reset_host_timeouts(ctx)

    # Turn 2: a single timeout must NOT escalate (threshold is 2).
    record_host_timeout(ctx, url)
    assert should_escalate(ctx, url) is False, (
        "cross-turn accumulation: a single timeout in turn 2 escalated, "
        "meaning turn 1's counters were not reset at the turn boundary"
    )
