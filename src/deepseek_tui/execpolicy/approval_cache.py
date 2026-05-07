"""Per-call approval cache with fingerprint keys.

Mirrors ``crates/tui/src/tools/approval_cache.rs`` (280 lines).

Instead of caching approvals by tool name alone — which would let an
approved ``exec_shell "cat foo"`` silently unlock
``exec_shell "rm -rf /"`` — this cache keys off a **call fingerprint**
that includes the semantically-relevant portion of the arguments.

Fingerprint shapes:

- ``apply_patch`` → ``patch:<hash of sorted unique file paths>``
- ``exec_shell*`` → ``shell:<classify_command(tokens)>`` (flags dropped)
- ``fetch_url`` / ``web_fetch`` → ``net:<hostname>``
- everything else → ``tool:<tool_name>``

Entries carry an ``approved_for_session`` flag. When true, subsequent
calls with the same fingerprint auto-approve for the rest of the
session. When false, the grant is one-shot: the next call with the same
key still has to re-prompt.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from deepseek_tui.execpolicy.command_safety import classify_command

_SHELL_TOOLS = {
    "exec_shell",
    "exec_shell_wait",
    "exec_shell_interact",
    "exec_wait",
    "exec_interact",
}
_PATCH_TOOLS = {"apply_patch"}
_FETCH_TOOLS = {"fetch_url", "web.fetch", "web_fetch"}


@dataclass(frozen=True, slots=True)
class ApprovalKey:
    """Tool-call fingerprint used as the cache key.

    Mirrors Rust ``ApprovalKey`` (approval_cache.rs:31). Stable enough to
    match repeated calls; specific enough to avoid privilege confusion.
    """

    value: str

    def __str__(self) -> str:  # convenience for logs / events
        return self.value


class ApprovalCacheStatus(Enum):
    """Status of a previously-rendered approval decision.

    Mirrors Rust ``ApprovalCacheStatus`` (approval_cache.rs:35).
    """

    APPROVED = "approved"
    """Call fingerprint matched and the session flag says reuse."""
    DENIED = "denied"
    """Matched but the grant was one-shot (already consumed)."""
    UNKNOWN = "unknown"
    """No match — requires fresh approval."""


@dataclass(slots=True)
class _CacheEntry:
    approved_for_session: bool


@dataclass(slots=True)
class ApprovalCache:
    """Approval cache backed by tool-call fingerprints.

    Mirrors Rust ``ApprovalCache`` (approval_cache.rs:55-110). Scope is
    the current engine session — the engine owns one instance and clears
    it on session boundaries.
    """

    _entries: dict[ApprovalKey, _CacheEntry] = field(default_factory=dict)

    def check(self, key: ApprovalKey) -> ApprovalCacheStatus:
        entry = self._entries.get(key)
        if entry is None:
            return ApprovalCacheStatus.UNKNOWN
        if entry.approved_for_session:
            return ApprovalCacheStatus.APPROVED
        return ApprovalCacheStatus.DENIED

    def insert(self, key: ApprovalKey, approved_for_session: bool) -> None:
        self._entries[key] = _CacheEntry(approved_for_session=approved_for_session)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def is_empty(self) -> bool:
        return not self._entries


# --- Fingerprint builders --------------------------------------------------


def build_approval_key(tool_name: str, tool_input: Any) -> ApprovalKey:
    """Build the approval-cache key for a tool call.

    Mirrors Rust ``build_approval_key`` (approval_cache.rs:121-142).
    """
    if tool_name in _PATCH_TOOLS:
        return ApprovalKey(f"patch:{_hash_patch_paths(tool_input)}")
    if tool_name in _SHELL_TOOLS:
        return ApprovalKey(f"shell:{_command_prefix(tool_input)}")
    if tool_name in _FETCH_TOOLS:
        return ApprovalKey(f"net:{_parse_host(tool_input)}")
    return ApprovalKey(f"tool:{tool_name}")


def _command_prefix(tool_input: Any) -> str:
    """Canonical command prefix via the arity dictionary.

    ``git status -s`` and ``git status --porcelain`` fingerprint identical;
    ``git push`` fingerprints differently. Mirrors Rust ``command_prefix``.
    """
    command = ""
    if isinstance(tool_input, dict):
        raw = tool_input.get("command")
        if isinstance(raw, str):
            command = raw
    tokens = command.split()
    if not tokens:
        return "<empty>"
    return classify_command(tokens)


def _hash_patch_paths(tool_input: Any) -> str:
    """Hash the sorted set of file paths referenced by a patch input.

    Mirrors Rust ``hash_patch_paths`` (approval_cache.rs:159-191). Supports
    both the structured ``changes`` list and the unified-diff ``patch``
    text. Rust uses ``DefaultHasher``; we use ``blake2b`` truncated to
    16 hex chars — stable across Python runs (unlike ``hash()``) and
    fast. The fingerprint *identity* matters, not hash compatibility
    with Rust, because each session has its own cache.
    """
    paths: list[str] = []
    if isinstance(tool_input, dict):
        changes = tool_input.get("changes")
        if isinstance(changes, list):
            for change in changes:
                if isinstance(change, dict):
                    p = change.get("path")
                    if isinstance(p, str) and p:
                        paths.append(p)
        elif isinstance(tool_input.get("patch"), str):
            patch_text = tool_input["patch"]
            for line in patch_text.splitlines():
                if line.startswith("+++ b/"):
                    rest = line[len("+++ b/") :].strip()
                    if rest and rest != "/dev/null":
                        paths.append(rest)

    if not paths:
        return "no_files"

    unique_sorted = sorted(set(paths))
    digest = hashlib.blake2b(digest_size=8)
    for path in unique_sorted:
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _parse_host(tool_input: Any) -> str:
    """Extract hostname from a URL input.

    Mirrors Rust ``parse_host`` (approval_cache.rs:194-202). If the URL
    is unparseable or has no host, fall back to the raw string so the
    cache still differentiates distinct garbage inputs.
    """
    url = ""
    if isinstance(tool_input, dict):
        raw = tool_input.get("url")
        if isinstance(raw, str):
            url = raw
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    return parsed.hostname or url
