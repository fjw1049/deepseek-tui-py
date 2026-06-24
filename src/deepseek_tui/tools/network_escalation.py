"""Network timeout escalation: track per-host timeouts on the ToolContext.

Goal: when the same host times out repeatedly within a turn, surface a
mirror / tool-swap suggestion instead of letting the model retry in
place (the reverse-skill trace burned 4-5 rounds hammering
``raw.githubusercontent.com`` before the model thought to switch hosts).

State lives on ``context.metadata["network_host_timeouts"]`` as a
``{host: count}`` dict. ToolContext is per-engine and shared across
rounds within a single turn, so the counter covers the multi-round retry
storm we saw. It does not persist across turns — a fresh turn starts
clean, which is the right call (a transient network blip one turn ago
shouldn't permanently poison the host).

This module is deliberately tiny: two helpers and the jsDelivr rewrite.
Both ``exec_shell`` (curl timeout) and ``fetch_url`` (httpx timeout) call
``record_host_timeout`` and read ``host_timeout_count`` to decide whether
to attach an escalation hint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    # Avoid a runtime circular import: registry -> shell -> network_escalation
    # -> registry. We only use ToolContext for type hints; the runtime passes
    # a duck-typed object whose .metadata we read/write.
    from deepseek_tui.tools.registry import ToolContext

# Metadata key holding the {host: int} timeout counter.
_HOST_TIMEOUTS_KEY = "network_host_timeouts"

# After this many timeouts on one host within a turn, escalate from a
# quiet single-shot hint to an explicit mirror/tool-swap suggestion.
_ESCALATION_THRESHOLD = 2


def _store(context: ToolContext) -> dict[str, int]:
    store = context.metadata.get(_HOST_TIMEOUTS_KEY)
    if not isinstance(store, dict):
        store = {}
        context.metadata[_HOST_TIMEOUTS_KEY] = store
    return store


def record_host_timeout(context: ToolContext, url: str) -> str | None:
    """Bump the per-host timeout counter for ``url``'s host.

    Returns the host so the caller can format a hint without re-parsing.
    Returns None if ``url`` has no usable host (not an http(s) URL).
    """
    host = _host_of(url)
    if host is None:
        return None
    store = _store(context)
    store[host] = store.get(host, 0) + 1
    return host


def host_timeout_count(context: ToolContext, url: str) -> int:
    """How many times ``url``'s host has timed out this turn."""
    host = _host_of(url)
    if host is None:
        return 0
    store = context.metadata.get(_HOST_TIMEOUTS_KEY)
    if not isinstance(store, dict):
        return 0
    return int(store.get(host, 0))


def should_escalate(context: ToolContext, url: str) -> bool:
    """True once a host has crossed the escalation threshold."""
    return host_timeout_count(context, url) >= _ESCALATION_THRESHOLD


def reset_host_timeouts(context: ToolContext) -> None:
    """Clear all per-host timeout counters.

    Called at turn start so a transient network blip in a prior turn
    doesn't permanently poison a host into escalation. Matches the
    module's intended invariant ("a fresh turn starts clean") that the
    counter is turn-scoped, not session-scoped.
    """
    context.metadata.pop(_HOST_TIMEOUTS_KEY, None)


def _host_of(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    return host or None
