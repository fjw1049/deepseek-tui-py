"""Tool approval gate — mirrors Rust ``turn_loop`` + ``ToolSpec::approval_requirement``.

Single source of truth for *whether* to prompt/block. Presentation lives in
``approval_present``; legacy ``ExecPolicyEngine.evaluate`` delegates here.

See ``docs/APPROVAL_CODE_AUDIT.md`` for naming rationale (Tool vs MCP mirrors).
"""

from __future__ import annotations

from enum import Enum

from deepseek_tui.engine.dispatch import is_mcp_tool, mcp_tool_is_read_only
from deepseek_tui.execpolicy.engine import _assess_risk, _classify_category
from deepseek_tui.execpolicy.models import ApprovalRequest
from deepseek_tui.tools.base import ApprovalRequirement, ToolCapability, ToolSpec

_AUTO_POLICIES = frozenset({"auto", "never-ask", "yolo"})
_PROMPT_POLICIES = frozenset({"on-request", "suggest", "untrusted"})
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
    """Mirror ``ToolSpec.approval_requirement`` default (for legacy evaluate API)."""
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


def _mcp_requirement(tool_name: str) -> ApprovalRequirement:
    if not is_mcp_tool(tool_name) or mcp_tool_is_read_only(tool_name):
        return ApprovalRequirement.AUTO
    return ApprovalRequirement.REQUIRED


def needs_mcp_approval_prompt(tool_name: str, policy: str | None) -> bool:
    return _gate_action(_mcp_requirement(tool_name), policy) is GateAction.PROMPT


def should_block_mcp_on_never(tool_name: str, policy: str | None) -> bool:
    return _gate_action(_mcp_requirement(tool_name), policy) is GateAction.BLOCK_NEVER


def plan_requires_mcp_approval(tool_name: str, policy: str | None) -> bool:
    return _gate_action(_mcp_requirement(tool_name), policy) is not GateAction.SKIP


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


def approval_request_for_mcp(tool_name: str, policy: str | None) -> ApprovalRequest | None:
    if should_block_mcp_on_never(tool_name, policy):
        caps = [ToolCapability.REQUIRES_APPROVAL, ToolCapability.NETWORK]
        return build_approval_request(tool_name, caps, blocked_never=True)
    if needs_mcp_approval_prompt(tool_name, policy):
        from deepseek_tui.engine.dispatch import mcp_tool_approval_description

        caps = [ToolCapability.REQUIRES_APPROVAL, ToolCapability.NETWORK]
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
        return mode in _PROMPT_POLICIES
    return False
