"""Tool approval UI — gate, presentation, elevation.

Consolidates approval_gate.py, approval_present.py, elevation_present.py.
"""

from __future__ import annotations



# Tool approval gate.
#
# Single source of truth for *whether* to prompt/block. Presentation lives in
# ``approval_present``; legacy ``ExecPolicyEngine.evaluate`` delegates here.
#
# See ``docs/APPROVAL_CODE_AUDIT.md`` for naming rationale (Tool vs MCP mirrors).
#
from enum import Enum

from deepseek_tui.engine.dispatch import is_mcp_tool, mcp_tool_is_read_only
from deepseek_tui.policy.approval import _assess_risk, _classify_category
from deepseek_tui.policy.approval import ApprovalRequest
from deepseek_tui.tools.registry import ApprovalRequirement, ToolCapability, ToolSpec
import json
from typing import Any
from typing import TYPE_CHECKING

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


def plan_requires_approval(tool: ToolSpec, policy: str | None) -> bool:
    """True if batch must not parallelize (includes never-block, not only prompt)."""
    return _gate_action(tool.approval_requirement(), policy) is not GateAction.SKIP


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
) -> ApprovalRequest | None:
    """Build an :class:`ApprovalRequest` for the engine gate, or None to skip."""
    if should_block_tool_on_never(tool, policy):
        return build_approval_request(
            tool.name(),
            tool.capabilities(),
            blocked_never=True,
        )
    if needs_tool_approval_prompt(tool, policy):
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
    """Legacy/capability-only entry (``ExecPolicyEngine.evaluate`` delegates here)."""
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

from deepseek_tui.policy.approval import build_approval_key
from deepseek_tui.policy.command_safety import SafetyLevel, analyze_command

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
    if tool_name.startswith("agent_"):
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

if TYPE_CHECKING:
    from deepseek_tui.engine.events import ElevationRequiredEvent


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
