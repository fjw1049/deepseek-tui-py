"""Network policy — domain-level allow/deny for outbound HTTP.

Mirrors ``crates/tui/src/network_policy.rs``.
"""

from .policy import NetworkPolicy, NetworkPolicyDecider, Decision

__all__ = ["NetworkPolicy", "NetworkPolicyDecider", "Decision"]
