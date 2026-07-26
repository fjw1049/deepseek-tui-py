"""Tool approval — decision engine, cache, gate, presentation, elevation.

Single authoritative module for tool approval. Consolidates the former
``policy.approval`` (decision engine, fingerprint cache, policy amendment)
with the approval gate and presentation helpers. See
``docs/TOOL_OPTIMIZATION_PLAN.md`` (Phase 3) for the consolidation plan.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from deepseek_tui.policy.command_safety import SafetyLevel, analyze_command

# Single source of truth for the execpolicy Decision enum and error types
# lives in policy.exec_policy; re-exported here for callers that import
# them from tools.approval (e.g. tools/shell.py).
from deepseek_tui.policy.exec_policy import (  # noqa: F401
    AmendError,
    Decision,
    ExecPolicyError,
)
from deepseek_tui.tools.registry import ApprovalRequirement, ToolCapability, ToolSpec

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.events import ElevationRequiredEvent


# Approval data model — request, decision, risk, policy rules.


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
# - ``exec_shell*`` → ``shell:<positional tokens, flags dropped>``
#   so ``rm a.txt`` ≠ ``rm b.txt``, while ``git status -s`` ≡
#   ``git status --porcelain``.
# - ``write_file`` / ``edit_file`` → ``file:<name>:<path>``
# - ``fetch_url`` / ``web_fetch`` → ``net:<hostname>``
# - everything else → ``tool:<tool_name>``
#
# Entries carry an ``approved_for_session`` flag. When true, subsequent
# calls with the same fingerprint auto-approve for the rest of the
# session. When false, the grant is one-shot: the next call with the same
# key still has to re-prompt.


_SHELL_TOOLS = {
    "exec_shell",
    "exec_shell_interact",
}
_FETCH_TOOLS = {"fetch_url", "web.fetch", "web_fetch"}
_FILE_WRITE_TOOLS = {"write_file", "edit_file"}


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
    if tool_name in _SHELL_TOOLS:
        return ApprovalKey(f"shell:{_command_prefix(tool_input)}")
    if tool_name in _FETCH_TOOLS:
        return ApprovalKey(f"net:{_parse_host(tool_input)}")
    if tool_name in _FILE_WRITE_TOOLS:
        return ApprovalKey(f"file:{tool_name}:{_file_path_key(tool_input)}")
    if tool_name == "agent":
        # The merged ``agent`` tool dispatches by ``action`` — approving a
        # spawn for the session must not bleed into send_input/cancel, and
        # id-scoped actions (cancel/send_input/result) stay per-target.
        action = ""
        target = ""
        if isinstance(tool_input, dict):
            raw_action = tool_input.get("action")
            if isinstance(raw_action, str):
                action = raw_action
            for id_key in ("agent_id", "process_id"):
                raw_id = tool_input.get(id_key)
                if isinstance(raw_id, str) and raw_id:
                    target = raw_id
                    break
        suffix = f":{target}" if target else ""
        return ApprovalKey(f"agent:{action or '<unknown>'}{suffix}")
    return ApprovalKey(f"tool:{tool_name}")


def _command_prefix(tool_input: Any) -> str:
    """Fingerprint shell commands by positional tokens (flags dropped).

    ``git status -s`` and ``git status --porcelain`` fingerprint identical;
    ``rm a.txt`` and ``rm b.txt`` fingerprint differently so a session
    remember cannot cross paths. Flags (``-`` / ``--``) are ignored so
    cosmetic option differences do not re-prompt.
    """
    command = ""
    if isinstance(tool_input, dict):
        raw = tool_input.get("command")
        if isinstance(raw, str):
            command = raw
    tokens = command.split()
    if not tokens:
        return "<empty>"
    positional = [t.lower() for t in tokens if not t.startswith("-")]
    if not positional:
        return "<flags-only>"
    # Bound key size for very long argument lists while keeping identity.
    joined = " ".join(positional)
    if len(joined) <= 200:
        return joined
    digest = hashlib.blake2b(joined.encode("utf-8"), digest_size=8).hexdigest()
    head = " ".join(positional[:3])
    return f"{head}:{digest}"


def _file_path_key(tool_input: Any) -> str:
    """Normalize the path argument for write/edit approval fingerprints."""
    path = ""
    if isinstance(tool_input, dict):
        raw = tool_input.get("path")
        if isinstance(raw, str):
            path = raw.strip().replace("\\", "/")
    if not path:
        return "no_path"
    return path


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


# Exec policy engine — rule overrides and session decision cache.


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
        """Legacy API — uses the gate logic in this module.

        Engine tool execution uses ``approval_request_for_tool`` instead.
        Kept for ``PolicyRule`` overrides and contract tests.
        """
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


# Tool approval gate.
#
# Single source of truth for *whether* to prompt/block. Presentation lives
# in this module below; ``ExecPolicyEngine.evaluate`` (above) is the legacy
# entry point into the same gate.

_AUTO_POLICIES = frozenset({"auto", "never-ask", "yolo"})
# Policies that prompt for SUGGEST-tier tools (workspace writes).
# ``untrusted`` intentionally omits SUGGEST: only REQUIRED (shell/MCP write/
# spawn/…) prompts — matching the "sensitive only" product tier.
# REQUIRED still returns True below; ``auto`` / ``never`` short-circuit in
# ``_gate_action`` before this helper runs.
_SUGGEST_PROMPT_POLICIES = frozenset({"on-request", "suggest"})
NEVER_BLOCKED_PREFIX = "blocked by approval_policy=never"


class GateAction(str, Enum):
    SKIP = "skip"
    PROMPT = "prompt"
    BLOCK_NEVER = "block_never"


def normalize_approval_policy(policy: str | None) -> str:
    return (policy or "on-request").strip().lower()


def requirement_from_capabilities(
    capabilities: list[ToolCapability],
) -> ApprovalRequirement:
    """``approval_requirement`` default (for legacy evaluate API)."""
    if ToolCapability.EXECUTES_CODE in capabilities or (
        ToolCapability.REQUIRES_APPROVAL in capabilities
    ):
        return ApprovalRequirement.REQUIRED
    if ToolCapability.WRITES_FILES in capabilities:
        return ApprovalRequirement.SUGGEST
    return ApprovalRequirement.AUTO


def _gate_action(requirement: ApprovalRequirement, policy: str | None) -> GateAction:
    mode = normalize_approval_policy(policy)
    if mode in _AUTO_POLICIES or requirement == ApprovalRequirement.AUTO:
        return GateAction.SKIP
    if mode == "never":
        return GateAction.BLOCK_NEVER
    if _requirement_needs_prompt(requirement, mode):
        return GateAction.PROMPT
    return GateAction.SKIP


def needs_tool_approval_prompt(tool: ToolSpec, policy: str | None) -> bool:
    """True when the user should see an approval dialog (L1 prompt)."""
    return _gate_action(tool.approval_requirement(), policy) is GateAction.PROMPT


def should_block_tool_on_never(tool: ToolSpec, policy: str | None) -> bool:
    """True when ``never`` policy must reject without prompting."""
    return _gate_action(tool.approval_requirement(), policy) is GateAction.BLOCK_NEVER


def plan_requires_approval(
    tool: ToolSpec,
    policy: str | None,
    input_data: dict[str, Any] | None = None,
) -> bool:
    """True if batch must not parallelize (includes never-block, not only prompt)."""
    requirement = (
        tool.approval_requirement_for_input(input_data)
        if input_data is not None
        else tool.approval_requirement()
    )
    return _gate_action(requirement, policy) is not GateAction.SKIP


def _capabilities_from_declared(declared: list[str] | None) -> list[ToolCapability]:
    """Parse declared capability strings (plugin manifest permissions)."""
    if not declared:
        return []
    out: list[ToolCapability] = []
    for value in declared:
        try:
            cap = ToolCapability(value)
        except ValueError:
            continue
        if cap not in out:
            out.append(cap)
    return out


def _mcp_requirement(
    tool_name: str, declared_capabilities: list[str] | None = None
) -> ApprovalRequirement:
    # Lazy import: engine.dispatch pulls in engine.handle, which imports
    # this module — a module-level import here would create a cycle.
    from deepseek_tui.engine.dispatch import is_mcp_tool, mcp_tool_is_read_only

    if not is_mcp_tool(tool_name) or mcp_tool_is_read_only(tool_name):
        return ApprovalRequirement.AUTO
    # External declarations are claims, not authorization. They may improve
    # the approval description but must never lower the conservative default.
    # In particular, a plugin cannot self-declare ``read_only`` to bypass the
    # approval gate for an otherwise mutating/unknown MCP tool.
    return ApprovalRequirement.REQUIRED


def needs_mcp_approval_prompt(
    tool_name: str,
    policy: str | None,
    declared_capabilities: list[str] | None = None,
) -> bool:
    req = _mcp_requirement(tool_name, declared_capabilities)
    return _gate_action(req, policy) is GateAction.PROMPT


def should_block_mcp_on_never(
    tool_name: str,
    policy: str | None,
    declared_capabilities: list[str] | None = None,
) -> bool:
    req = _mcp_requirement(tool_name, declared_capabilities)
    return _gate_action(req, policy) is GateAction.BLOCK_NEVER


def plan_requires_mcp_approval(
    tool_name: str,
    policy: str | None,
    declared_capabilities: list[str] | None = None,
) -> bool:
    req = _mcp_requirement(tool_name, declared_capabilities)
    return _gate_action(req, policy) is not GateAction.SKIP


def build_approval_request(
    tool_name: str,
    capabilities: list[ToolCapability],
    *,
    reason: str | None = None,
    blocked_never: bool = False,
) -> ApprovalRequest:
    category = _classify_category(capabilities)
    risk = _assess_risk(capabilities)
    if blocked_never:
        msg = NEVER_BLOCKED_PREFIX
    elif reason:
        msg = reason
    else:
        msg = f"{tool_name} requires approval"
    return ApprovalRequest(
        tool_name=tool_name,
        risk_level=risk,
        category=category,
        reason=msg,
    )


def approval_request_for_tool(
    tool: ToolSpec,
    policy: str | None,
    input_data: dict[str, Any] | None = None,
) -> ApprovalRequest | None:
    """Build an :class:`ApprovalRequest` for the engine gate, or None to skip."""
    requirement = (
        tool.approval_requirement_for_input(input_data)
        if input_data is not None
        else tool.approval_requirement()
    )
    if _gate_action(requirement, policy) is GateAction.BLOCK_NEVER:
        return build_approval_request(
            tool.name(),
            tool.capabilities(),
            blocked_never=True,
        )
    if _gate_action(requirement, policy) is GateAction.PROMPT:
        return build_approval_request(
            tool.name(),
            tool.capabilities(),
            reason=tool.description(),
        )
    return None


def approval_request_for_capabilities(
    tool_name: str,
    capabilities: list[ToolCapability],
    policy: str | None,
    *,
    reason: str | None = None,
) -> ApprovalRequest | None:
    """Legacy/capability-only entry (``ExecPolicyEngine.evaluate`` calls here)."""
    req = requirement_from_capabilities(capabilities)
    action = _gate_action(req, policy)
    if action is GateAction.SKIP:
        return None
    if action is GateAction.BLOCK_NEVER:
        return build_approval_request(
            tool_name, capabilities, blocked_never=True
        )
    return build_approval_request(
        tool_name,
        capabilities,
        reason=reason or f"{tool_name} requires approval",
    )


def approval_request_for_mcp(
    tool_name: str,
    policy: str | None,
    declared_capabilities: list[str] | None = None,
) -> ApprovalRequest | None:
    declared = _capabilities_from_declared(declared_capabilities)
    if should_block_mcp_on_never(tool_name, policy, declared_capabilities):
        caps = declared or [ToolCapability.REQUIRES_APPROVAL, ToolCapability.NETWORK]
        return build_approval_request(tool_name, caps, blocked_never=True)
    if needs_mcp_approval_prompt(tool_name, policy, declared_capabilities):
        from deepseek_tui.engine.dispatch import mcp_tool_approval_description

        caps = declared or [ToolCapability.REQUIRES_APPROVAL, ToolCapability.NETWORK]
        return build_approval_request(
            tool_name,
            caps,
            reason=mcp_tool_approval_description(tool_name),
        )
    return None


def _requirement_needs_prompt(req: ApprovalRequirement, mode: str) -> bool:
    if req == ApprovalRequirement.REQUIRED:
        return True
    if req == ApprovalRequirement.SUGGEST:
        return mode in _SUGGEST_PROMPT_POLICIES
    return False


# Build human-readable approval presentation.

_PREVIEW_MAX = 4000
_LINE_MAX = 200


def enrich_approval_request(
    request: ApprovalRequest,
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    tool_description: str | None = None,
) -> None:
    """Fill presentation fields on ``request`` for UI / SSE."""
    args = arguments if isinstance(arguments, dict) else {}
    cat = classify_tool_category(tool_name)
    risk = classify_presentation_risk(tool_name, cat, args)
    impacts = build_impacts(tool_name, cat, args)
    preview = build_primary_preview(tool_name, cat, args)
    title = localized_title(cat, tool_name)

    if risk == "destructive" and cat == "shell":
        cmd = _param_preview(args, ("command", "cmd"), 96)
        if cmd:
            analysis = analyze_command(cmd)
            if analysis.level == SafetyLevel.DANGEROUS:
                detail = analysis.reasons[0] if analysis.reasons else "dangerous command"
                impacts = [*impacts, f"Warning: {detail}"]

    request.title = title
    request.impacts = impacts
    request.primary_preview = preview
    request.presentation_risk = risk
    request.approval_key = str(build_approval_key(tool_name, args))
    if preview:
        request.input_summary = preview[:500]
    elif tool_description and not request.input_summary:
        request.input_summary = tool_description[:500]
    if tool_description and (
        not request.reason or request.reason.startswith("tool has ")
    ):
        request.reason = tool_description


def approval_request_to_sse_payload(
    approval_id: str, request: ApprovalRequest
) -> dict[str, object]:
    """SSE ``approval.required`` payload with backward-compatible keys."""
    risk_level = (
        "low"
        if request.presentation_risk == "benign"
        else "high" if request.presentation_risk == "destructive"
        else request.risk_level.value
    )
    title = request.title or request.reason
    return {
        "id": approval_id,
        "approval_id": approval_id,
        "tool_name": request.tool_name,
        "title": title,
        "description": title,
        "impacts": list(request.impacts),
        "primary_preview": request.primary_preview or None,
        "input_summary": request.input_summary or request.primary_preview or "",
        "category": classify_tool_category(request.tool_name),
        "risk": request.presentation_risk or None,
        "risk_level": risk_level,
        "approval_key": request.approval_key or None,
    }


def classify_tool_category(tool_name: str) -> str:
    # Lazy import of engine.dispatch: see _mcp_requirement.
    from deepseek_tui.engine.dispatch import is_mcp_tool

    if tool_name in ("write_file", "edit_file"):
        return "file_write"
    if tool_name in ("web_search", "fetch_url"):
        return "network"
    if tool_name in ("exec_shell", "exec_shell_interact"):
        return "shell"
    if tool_name.startswith("list_mcp_") or tool_name.startswith("read_mcp_"):
        return "mcp_read"
    if tool_name.startswith("mcp_") or is_mcp_tool(tool_name):
        from deepseek_tui.engine.dispatch import mcp_tool_is_read_only

        return "mcp_action" if not mcp_tool_is_read_only(tool_name) else "mcp_read"
    if tool_name == "agent" or tool_name.startswith("agent_"):
        return "subagent"
    if tool_name.startswith("task_"):
        return "task"
    if tool_name.startswith("automation_"):
        return "automation"
    if tool_name in (
        "read_file",
        "list_dir",
        "grep_files",
        "file_search",
        "note",
        "update_plan",
        "checklist",
        "git",
    ) or tool_name.startswith(("read_", "list_", "get_")):
        return "safe"
    return "unknown"


def classify_presentation_risk(
    tool_name: str, category: str, args: dict[str, Any]
) -> str:
    if category in ("safe", "mcp_read"):
        return "benign"
    if category == "network":
        return "benign"
    if category == "shell":
        cmd = _param_preview(args, ("command", "cmd"), 96)
        if cmd and analyze_command(cmd).level == SafetyLevel.DANGEROUS:
            return "destructive"
        return "destructive"
    if category in (
        "file_write",
        "mcp_action",
        "subagent",
        "task",
        "automation",
        "unknown",
    ):
        return "destructive"
    return "destructive"


def build_impacts(tool_name: str, category: str, args: dict[str, Any]) -> list[str]:
    if category == "safe":
        lines = ["Read-only operation."]
        if path := _param_preview(args, ("path", "ref_id", "uri"), 72):
            lines.append(f"Reads: {path}")
        return lines
    if category == "file_write":
        lines = ["Writes files in the workspace or an approved write scope."]
        if path := _param_preview(args, ("path", "target", "destination"), 72):
            lines.append(f"Writes: {path}")
        return lines
    if category == "shell":
        lines = ["Executes a shell command."]
        if cmd := _param_preview(args, ("command", "cmd"), 96):
            lines.append(f"Command: {cmd}")
        if cwd := _param_preview(args, ("workdir", "cwd"), 72):
            lines.append(f"Working dir: {cwd}")
        return lines
    if category == "network":
        lines = ["May reach network services or remote content."]
        if target := _param_preview(args, ("url", "q", "query"), 96):
            lines.append(f"Target: {target}")
        return lines
    if category == "mcp_read":
        lines = ["Reads from an MCP server without an obvious local write."]
        if server := _mcp_server_hint(tool_name):
            lines.append(f"Server: {server}")
        return lines
    if category == "mcp_action":
        lines = ["Calls an MCP server action that may have side effects."]
        if server := _mcp_server_hint(tool_name):
            lines.append(f"Server: {server}")
        return lines
    if category == "subagent":
        lines = ["Spawns a sub-agent that may run tools in this workspace."]
        if prompt := _param_preview(
            args, ("prompt", "message", "objective"), 120
        ):
            lines.append(f"Task: {prompt}")
        for key, label in (
            ("type", "type"),
            ("model", "model"),
            ("allow_shell", "allow_shell"),
        ):
            if key in args:
                lines.append(f"{label}: {args[key]}")
        return lines
    if category in ("task", "automation"):
        lines = [f"Runs a {category} tool that may change durable state."]
        if prompt := _param_preview(args, ("prompt", "message", "name"), 96):
            lines.append(f"Detail: {prompt}")
        return lines
    lines = ["Tool is not classified. Review parameters before approving."]
    if target := _param_preview(
        args, ("path", "cmd", "command", "url", "q", "query"), 96
    ):
        lines.append(f"Primary input: {target}")
    return lines


def build_primary_preview(
    tool_name: str, category: str, args: dict[str, Any]
) -> str:
    if category == "shell":
        parts = []
        if cmd := _param_preview(args, ("command", "cmd"), _LINE_MAX):
            parts.append(cmd)
        if cwd := _param_preview(args, ("workdir", "cwd"), 72):
            parts.append(f"cwd: {cwd}")
        return "\n".join(parts)
    if category == "network":
        return _param_preview(args, ("url", "q", "query"), _LINE_MAX) or ""
    if category == "subagent":
        return _param_preview(args, ("prompt", "message", "objective"), _PREVIEW_MAX) or ""
    if category == "file_write":
        if content := _param_preview(args, ("content",), 800):
            path = _param_preview(args, ("path",), 72) or "?"
            return f"path: {path}\n\n{content}"
        if search := _param_preview(args, ("old_string", "new_string", "search", "replace"), 400):
            path = _param_preview(args, ("path",), 72) or "?"
            return f"path: {path}\nold_string/new_string:\n{search}"
    if args:
        try:
            return _truncate(json.dumps(args, ensure_ascii=False, indent=0), 1200)
        except (TypeError, ValueError):
            return _truncate(str(args), 1200)
    return ""


def localized_title(category: str, tool_name: str) -> str:
    titles = {
        "safe": "Read-only operation requested",
        "file_write": "File change requested",
        "shell": "Shell command requested",
        "network": "Network access requested",
        "mcp_read": "MCP read requested",
        "mcp_action": "MCP action requested",
        "subagent": "Sub-agent requested",
        "task": "Task operation requested",
        "automation": "Automation change requested",
        "unknown": f"Approval required for {tool_name}",
    }
    return titles.get(category, f"Approval required for {tool_name}")


def _mcp_server_hint(tool_name: str) -> str | None:
    remainder = tool_name.removeprefix("mcp_")
    if "__" in remainder:
        return remainder.split("__", 1)[0] or None
    if "_" in remainder:
        return remainder.split("_", 1)[0] or None
    return None


def _param_preview(
    args: dict[str, Any], keys: tuple[str, ...], max_len: int
) -> str | None:
    for key in keys:
        if key not in args:
            continue
        value = args[key]
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            return _truncate(text, max_len) if text else None
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list) and value:
            preview = ", ".join(
                _truncate(str(item), max_len // 2) for item in value[:3]
            )
            return _truncate(preview, max_len)
    return None


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# SSE payload for sandbox elevation (L3) — Workbench parity.


def elevation_request_to_sse_payload(
    elevation_id: str,
    event: ElevationRequiredEvent,
) -> dict[str, object]:
    return {
        "elevation_id": elevation_id,
        "tool_call_id": elevation_id,
        "tool_name": event.tool_name,
        "title": "Sandbox blocked this command",
        "description": event.reason,
        "reason": event.reason,
        "elevation_kind": event.elevation_kind,
        "primary_preview": event.command_preview or None,
        "risk": "destructive",
        "risk_level": "high",
    }
