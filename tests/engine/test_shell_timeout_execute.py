"""Regression tests for the exec_shell timeout → host-escalation path.

Pins the double-count bug (A1) that the hint-only tests in
``test_shell_timeout_hint.py`` could not catch (they call the hint
function directly, never the ``execute()`` timeout branch):

``ExecShellTool.execute()`` used to call ``record_host_timeout`` *twice*
in its ``except TimeoutError`` branch (a bad-merge leftover). With the
escalation threshold at 2, a *single* timeout immediately flipped
``should_escalate`` to True — breaking the "a single timeout stays
quiet" invariant. Fixed by deleting the duplicate block.

These tests exercise the real ``execute()`` path by running a command
that genuinely times out, then asserting the host counter is exactly 1
and ``should_escalate`` is False after a single timeout.
"""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.tools.network_escalation import (
    host_timeout_count,
    should_escalate,
)
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.shell import ExecShellTool

# Short enough to keep the test fast, long enough to reliably exceed the
# foreground timeout_ms below.
_SLEEP_CMD = "sleep 10"
_TIMEOUT_MS = 150


async def test_single_curl_timeout_counts_host_once_not_twice(tmp_path: Path):
    """A1 regression: one exec_shell timeout must bump the host counter
    exactly once, not twice.

    Before the fix, ``execute()`` called ``record_host_timeout`` twice
    in the timeout branch (a bad-merge leftover). With the escalation
    threshold at 2, that meant a single timeout immediately triggered
    the mirror/CDN escalation hint — the opposite of the documented
    "single timeout stays quiet" behavior.
    """
    ctx = ToolContext(working_directory=tmp_path)
    tool = ExecShellTool()
    url = "https://example.com/slow"

    # The command embeds the URL so the timeout branch records it.
    # sleep guarantees the foreground timeout fires regardless of the
    # curl result.
    result = await tool.execute(
        {"command": f"curl -sL {url} ; {_SLEEP_CMD}", "timeout_ms": _TIMEOUT_MS},
        ctx,
    )

    assert result.success is False
    assert result.metadata.get("timed_out") is True

    # The core assertion: one timeout → count is 1, NOT 2.
    assert host_timeout_count(ctx, url) == 1, (
        "single timeout bumped the host counter more than once — the "
        "duplicate record_host_timeout call in execute() was not removed"
    )
    # And therefore a single timeout must NOT escalate.
    assert should_escalate(ctx, url) is False, (
        "a single timeout escalated to the mirror/CDN hint — the "
        "double-count bug made the threshold (2) fire after one timeout"
    )


async def test_two_curl_timeouts_on_same_host_do_escalate(tmp_path: Path):
    """Positive control: two genuine timeouts on one host within a turn
    DO escalate. Confirms the fix didn't break the escalation path
    itself — only the double-count."""
    ctx = ToolContext(working_directory=tmp_path)
    tool = ExecShellTool()
    url = "https://example.com/slow"

    for _ in range(2):
        await tool.execute(
            {"command": f"curl -sL {url} ; {_SLEEP_CMD}", "timeout_ms": _TIMEOUT_MS},
            ctx,
        )

    assert host_timeout_count(ctx, url) == 2
    assert should_escalate(ctx, url) is True


async def test_non_url_timeout_does_not_record_any_host(tmp_path: Path):
    """A timeout on a command with no URL must not record any host —
    ``host_timeout_count`` stays 0 and there's nothing to escalate."""
    ctx = ToolContext(working_directory=tmp_path)
    tool = ExecShellTool()

    await tool.execute({"command": _SLEEP_CMD, "timeout_ms": _TIMEOUT_MS}, ctx)

    assert host_timeout_count(ctx, "https://example.com/x") == 0
    assert should_escalate(ctx, "https://example.com/x") is False
