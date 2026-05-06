from __future__ import annotations

from deepseek_tui.execpolicy.models import (
    ApprovalDecision,
    ApprovalRequest,
    PolicyRule,
    RiskLevel,
    ToolCategory,
)
from deepseek_tui.tools.base import ToolCapability


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
        """Evaluate whether a tool call needs approval.

        Returns None if auto-approved, or an ApprovalRequest if user
        confirmation is needed.
        """
        category = _classify_category(capabilities)
        risk = _assess_risk(capabilities)

        cached = self._session_cache.get(tool_name)
        if cached == ApprovalDecision.APPROVED_SESSION:
            return None

        if self.approval_policy in {"auto", "never-ask", "yolo"}:
            return None
        if self.approval_policy == "never" and risk is not RiskLevel.LOW:
            return ApprovalRequest(
                tool_name=tool_name,
                risk_level=risk,
                category=category,
                reason="blocked by approval_policy=never",
            )

        for rule in self._rules:
            if rule.matches(tool_name, category):
                if rule.decision == ApprovalDecision.APPROVED:
                    return None
                if rule.decision == ApprovalDecision.DENIED:
                    return ApprovalRequest(
                        tool_name=tool_name,
                        risk_level=risk,
                        category=category,
                        reason="denied by policy rule",
                    )

        if risk in (RiskLevel.LOW,):
            return None

        return ApprovalRequest(
            tool_name=tool_name,
            risk_level=risk,
            category=category,
            reason=f"tool has {risk.value} risk level",
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
