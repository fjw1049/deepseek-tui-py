"""Network policy evaluation and session caching.

Mirrors ``crates/tui/src/network_policy.rs``.

Provides domain-level allow/deny gating for all outbound HTTP requests
made by tools (fetch_url, web_search, MCP transports). Deny-wins
precedence: a host in both allow and deny lists is always denied.
"""

from __future__ import annotations



import logging
import threading
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

__all__ = ["Decision", "NetworkPolicy", "NetworkPolicyDecider"]

_LOG = logging.getLogger(__name__)


class Decision(Enum):
    ALLOW = auto()
    DENY = auto()
    PROMPT = auto()


class NetworkPolicy:
    """Domain allow/deny lists with subdomain wildcard support.

    Entries starting with ``.`` (e.g. ``.example.com``) match subdomains
    but NOT the apex. Bare entries (``example.com``) match exactly.
    """

    def __init__(
        self,
        allow: Sequence[str] = (),
        deny: Sequence[str] = (),
    ) -> None:
        self._allow = list(allow)
        self._deny = list(deny)

    def evaluate(self, host: str) -> Decision:
        """Evaluate *host* against policy. Deny wins over allow."""
        host = host.lower().strip()
        if not host:
            return Decision.DENY

        # Deny check first (deny-wins precedence)
        if self._matches_list(host, self._deny):
            return Decision.DENY

        # Allow check
        if self._matches_list(host, self._allow):
            return Decision.ALLOW

        # Not in either list → prompt user
        return Decision.PROMPT

    @staticmethod
    def _matches_list(host: str, patterns: list[str]) -> bool:
        for pattern in patterns:
            p = pattern.lower().strip()
            if not p:
                continue
            if p.startswith("."):
                # Subdomain wildcard: .example.com matches sub.example.com
                # but NOT example.com itself
                if host.endswith(p) or host == p[1:]:
                    return True
            else:
                if host == p:
                    return True
        return False


class _SessionCache:
    """Thread-safe session-level approval cache."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._decisions: dict[str, Decision] = {}

    def get(self, host: str) -> Decision | None:
        with self._lock:
            return self._decisions.get(host)

    def put(self, host: str, decision: Decision) -> None:
        with self._lock:
            self._decisions[host] = decision


class NetworkPolicyDecider:
    """Bundles policy + session cache + auditor.

    Call :meth:`evaluate` before any outbound HTTP request.
    """

    def __init__(
        self,
        policy: NetworkPolicy | None = None,
        audit_path: Path | str | None = None,
    ) -> None:
        self._policy = policy or NetworkPolicy()
        self._cache = _SessionCache()
        if audit_path is None:
            self._audit_path = Path.home() / ".deepseek" / "audit.log"
        else:
            self._audit_path = Path(audit_path)

    def evaluate(self, url: str, tool_name: str = "unknown") -> Decision:
        """Evaluate URL and return decision. Checks cache first."""
        host = self._extract_host(url)
        if not host:
            return Decision.DENY

        # Check session cache
        cached = self._cache.get(host)
        if cached is not None:
            self._audit(host, tool_name, cached, from_cache=True)
            return cached

        # Evaluate policy
        decision = self._policy.evaluate(host)

        # Cache non-PROMPT decisions immediately; PROMPT decisions
        # are cached after the user responds (via approve/deny methods)
        if decision != Decision.PROMPT:
            self._cache.put(host, decision)

        self._audit(host, tool_name, decision, from_cache=False)
        return decision

    def approve(self, host: str) -> None:
        """Record user approval for this session."""
        self._cache.put(host.lower().strip(), Decision.ALLOW)

    def deny(self, host: str) -> None:
        """Record user denial for this session."""
        self._cache.put(host.lower().strip(), Decision.DENY)

    def _audit(
        self, host: str, tool: str, decision: Decision, *, from_cache: bool
    ) -> None:
        """Append one line to audit log (best-effort)."""
        try:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            cached_tag = " [cached]" if from_cache else ""
            line = f"{ts} {host} {tool} {decision.name}{cached_tag}\n"
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass  # best-effort audit

    @staticmethod
    def _extract_host(url: str) -> str:
        """Extract hostname from URL."""
        try:
            parsed = urlparse(url)
            return (parsed.hostname or "").lower().strip()
        except Exception:
            return ""
