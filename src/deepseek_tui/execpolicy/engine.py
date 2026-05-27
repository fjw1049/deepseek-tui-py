from __future__ import annotations

from deepseek_tui.execpolicy.models import (
    ApprovalDecision,
    ApprovalRequest,
    PolicyRule,
    RiskLevel,
    ToolCategory,
)
from typing import TYPE_CHECKING

from deepseek_tui.tools.base import ToolCapability

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
        from deepseek_tui.tools.approval_gate import approval_request_for_capabilities

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
