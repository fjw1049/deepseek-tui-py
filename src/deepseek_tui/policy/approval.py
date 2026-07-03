"""Tool approval — decision engine, cache, and amendment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Single source of truth for the execpolicy Decision enum and error types
# lives in policy.exec_policy; re-exported here for callers that import
# them from policy.approval (e.g. tools/shell.py).
from deepseek_tui.policy.exec_policy import (  # noqa: F401
    AmendError,
    Decision,
    ExecPolicyError,
)

from dataclasses import dataclass, field
from enum import Enum
import hashlib
from urllib.parse import urlparse
import json
from typing import TYPE_CHECKING


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolCategory(Enum):
    READ_ONLY = "read_only"
    FILE_WRITE = "file_write"
    CODE_EXEC = "code_exec"
    NETWORK = "network"
    DESTRUCTIVE = "destructive"


@dataclass(slots=True)
class ApprovalRequest:
    tool_name: str
    risk_level: RiskLevel
    category: ToolCategory
    reason: str
    input_summary: str = ""
    title: str = ""
    impacts: list[str] = field(default_factory=list)
    primary_preview: str = ""
    presentation_risk: str = ""  # benign | destructive
    approval_key: str = ""


class ApprovalDecision(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    APPROVED_SESSION = "approved_session"


@dataclass(slots=True)
class PolicyRule:
    """A single policy rule matching tool patterns to decisions."""

    pattern: str
    decision: ApprovalDecision
    risk_threshold: RiskLevel = RiskLevel.LOW
    categories: list[ToolCategory] = field(default_factory=list)

    def matches(self, tool_name: str, category: ToolCategory) -> bool:
        if self.categories and category not in self.categories:
            return False
        if self.pattern == "*":
            return True
        return tool_name == self.pattern or tool_name.startswith(self.pattern.rstrip("*"))



# Per-call approval cache with fingerprint keys.
#
# Instead of caching approvals by tool name alone — which would let an
# approved ``exec_shell "cat foo"`` silently unlock
# ``exec_shell "rm -rf /"`` — this cache keys off a **call fingerprint**
# that includes the semantically-relevant portion of the arguments.
#
# Fingerprint shapes:
#
# - ``apply_patch`` → ``patch:<hash of sorted unique file paths>``
# - ``exec_shell*`` → ``shell:<classify_command(tokens)>`` (flags dropped)
# - ``fetch_url`` / ``web_fetch`` → ``net:<hostname>``
# - everything else → ``tool:<tool_name>``
#
# Entries carry an ``approved_for_session`` flag. When true, subsequent
# calls with the same fingerprint auto-approve for the rest of the
# session. When false, the grant is one-shot: the next call with the same
# key still has to re-prompt.


from deepseek_tui.policy.command_safety import classify_command


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

    Stable enough to match repeated calls; specific enough to avoid
    privilege confusion.
    """

    value: str

    def __str__(self) -> str:  # convenience for logs / events
        return self.value


class ApprovalCacheStatus(Enum):
    """Status of a previously-rendered approval decision."""

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

    Scope is the current engine session — the engine owns one instance and
    clears it on session boundaries.
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
    """Build the approval-cache key for a tool call."""
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
    ``git push`` fingerprints differently.
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

    Supports both the structured ``changes`` list and the unified-diff
    ``patch`` text. We use ``blake2b`` truncated to 16 hex chars —
    stable across Python runs (unlike ``hash()``) and fast. Only the
    fingerprint *identity* matters, not any cross-implementation hash
    compatibility, because each session has its own cache.
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

    If the URL is unparseable or has no host, fall back to the raw string
    so the cache still differentiates distinct garbage inputs.
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



# Advisory file-locked append for policy amendments.
#
# The invariant: appending a new ``prefix_rule(...)`` line must
#
# 1. create the parent directory if it doesn't exist;
# 2. take an advisory lock on the policy file (``fcntl.flock`` on Unix);
# 3. ensure the existing content ends in ``\n`` before appending;
# 4. release the lock via the standard context manager on exit.
#
# macOS / Linux only (the current project scope). Windows support is
# deferred — the audit noted the sandbox module is the real Windows
# blocker, so we don't spend effort here on a Win-specific ``msvcrt``
# lock path.



__all__ = ["blocking_append_allow_prefix_rule"]


def blocking_append_allow_prefix_rule(
    policy_path: Path, prefix: list[str]
) -> None:
    """Append a ``prefix_rule(pattern=..., decision="allow")`` to the file.

    This blocks on advisory locking, so callers should wrap it in
    ``asyncio.to_thread`` when invoked from async code.
    """
    if not prefix:
        raise AmendError.empty_prefix()

    tokens_json = [json.dumps(token) for token in prefix]
    pattern_literal = "[" + ", ".join(tokens_json) + "]"
    line = f'prefix_rule(pattern={pattern_literal}, decision="allow")'

    parent = policy_path.parent
    if str(parent) == "":
        raise AmendError.missing_parent(policy_path)
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise AmendError.create_policy_dir(parent, err) from err

    _append_locked_line(policy_path, line)


def _append_locked_line(policy_path: Path, line: str) -> None:
    """Open ``policy_path`` for append, lock, and append ``line``."""
    import fcntl

    try:
        handle = open(  # noqa: SIM115 — lifetime is bounded by try/finally
            policy_path, "a+", encoding="utf-8"
        )
    except OSError as err:
        raise AmendError.open_policy_file(policy_path, err) from err

    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as err:
            raise AmendError.lock_policy_file(policy_path, err) from err

        # Ensure the file ends with a newline before we append. Seek to
        # the final byte (if any) and check.
        try:
            handle.seek(0, 2)  # SEEK_END
            size = handle.tell()
        except OSError as err:
            raise AmendError.read_policy_file(policy_path, err) from err

        needs_newline = False
        if size > 0:
            try:
                handle.seek(size - 1)
                last = handle.read(1)
            except OSError as err:
                raise AmendError.read_policy_file(policy_path, err) from err
            if last != "\n":
                needs_newline = True

        try:
            if needs_newline:
                handle.write("\n")
            handle.write(line + "\n")
            handle.flush()
        except OSError as err:
            raise AmendError.write_policy_file(policy_path, err) from err
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()




from deepseek_tui.tools.registry import ToolCapability

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config


def exec_policy_for_config(config: Config | None) -> ExecPolicyEngine:
    """Build an :class:`ExecPolicyEngine` from runtime ``Config``."""
    if config is None:
        return ExecPolicyEngine()
    policy = (getattr(config, "approval_policy", None) or "on-request").strip()
    return ExecPolicyEngine(approval_policy=policy or "on-request")


class ExecPolicyEngine:
    """Evaluates tool calls against policy rules and session cache."""

    def __init__(
        self,
        rules: list[PolicyRule] | None = None,
        *,
        approval_policy: str = "on-request",
    ) -> None:
        self._rules: list[PolicyRule] = rules or []
        self._session_cache: dict[str, ApprovalDecision] = {}
        self.approval_policy = approval_policy

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)

    def clear_cache(self) -> None:
        self._session_cache.clear()

    def evaluate(
        self,
        tool_name: str,
        capabilities: list[ToolCapability],
    ) -> ApprovalRequest | None:
        """Legacy API — delegates gate logic to ``tools.approval_gate``.

        Engine tool execution uses ``approval_request_for_tool`` instead.
        Kept for ``PolicyRule`` overrides and contract tests.
        """
        from deepseek_tui.tools.approval import approval_request_for_capabilities

        cached = self._session_cache.get(tool_name)
        if cached == ApprovalDecision.APPROVED_SESSION:
            return None

        category = _classify_category(capabilities)
        for rule in self._rules:
            if rule.matches(tool_name, category):
                if rule.decision == ApprovalDecision.APPROVED:
                    return None
                if rule.decision == ApprovalDecision.DENIED:
                    risk = _assess_risk(capabilities)
                    return ApprovalRequest(
                        tool_name=tool_name,
                        risk_level=risk,
                        category=category,
                        reason="denied by policy rule",
                    )

        return approval_request_for_capabilities(
            tool_name, capabilities, self.approval_policy
        )

    def record_decision(self, tool_name: str, decision: ApprovalDecision) -> None:
        self._session_cache[tool_name] = decision


def _classify_category(capabilities: list[ToolCapability]) -> ToolCategory:
    if ToolCapability.EXECUTES_CODE in capabilities:
        return ToolCategory.CODE_EXEC
    if ToolCapability.REQUIRES_APPROVAL in capabilities:
        return ToolCategory.DESTRUCTIVE
    if ToolCapability.WRITES_FILES in capabilities:
        return ToolCategory.FILE_WRITE
    if ToolCapability.NETWORK in capabilities:
        return ToolCategory.NETWORK
    return ToolCategory.READ_ONLY


def _assess_risk(capabilities: list[ToolCapability]) -> RiskLevel:
    if ToolCapability.REQUIRES_APPROVAL in capabilities:
        return RiskLevel.HIGH
    if ToolCapability.EXECUTES_CODE in capabilities:
        return RiskLevel.MEDIUM
    if ToolCapability.WRITES_FILES in capabilities:
        return RiskLevel.MEDIUM
    if ToolCapability.NETWORK in capabilities:
        return RiskLevel.LOW
    return RiskLevel.LOW