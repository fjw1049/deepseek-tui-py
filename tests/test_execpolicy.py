from __future__ import annotations

from deepseek_tui.execpolicy.engine import ExecPolicyEngine
from deepseek_tui.execpolicy.models import (
    ApprovalDecision,
    PolicyRule,
    RiskLevel,
    ToolCategory,
)
from deepseek_tui.tools.base import ToolCapability


def test_low_risk_auto_approved() -> None:
    engine = ExecPolicyEngine()
    result = engine.evaluate("read_file", [ToolCapability.READ_ONLY])
    assert result is None


def test_medium_risk_requires_approval() -> None:
    engine = ExecPolicyEngine()
    result = engine.evaluate("write_file", [ToolCapability.WRITES_FILES])
    assert result is not None
    assert result.risk_level == RiskLevel.MEDIUM
    assert result.category == ToolCategory.FILE_WRITE


def test_high_risk_requires_approval() -> None:
    engine = ExecPolicyEngine()
    result = engine.evaluate(
        "github_close", [ToolCapability.NETWORK, ToolCapability.REQUIRES_APPROVAL]
    )
    assert result is not None
    assert result.risk_level == RiskLevel.HIGH
    assert result.category == ToolCategory.DESTRUCTIVE


def test_policy_rule_auto_approves() -> None:
    rule = PolicyRule(pattern="write_file", decision=ApprovalDecision.APPROVED)
    engine = ExecPolicyEngine(rules=[rule])
    result = engine.evaluate("write_file", [ToolCapability.WRITES_FILES])
    assert result is None


def test_policy_rule_denies() -> None:
    rule = PolicyRule(pattern="exec_shell", decision=ApprovalDecision.DENIED)
    engine = ExecPolicyEngine(rules=[rule])
    result = engine.evaluate("exec_shell", [ToolCapability.EXECUTES_CODE])
    assert result is not None
    assert result.reason == "denied by policy rule"


def test_session_cache_approves_after_decision() -> None:
    engine = ExecPolicyEngine()
    result = engine.evaluate("write_file", [ToolCapability.WRITES_FILES])
    assert result is not None

    engine.record_decision("write_file", ApprovalDecision.APPROVED_SESSION)
    result2 = engine.evaluate("write_file", [ToolCapability.WRITES_FILES])
    assert result2 is None


def test_clear_cache_resets() -> None:
    engine = ExecPolicyEngine()
    engine.record_decision("write_file", ApprovalDecision.APPROVED_SESSION)
    engine.clear_cache()
    result = engine.evaluate("write_file", [ToolCapability.WRITES_FILES])
    assert result is not None


def test_wildcard_rule() -> None:
    rule = PolicyRule(pattern="*", decision=ApprovalDecision.APPROVED)
    engine = ExecPolicyEngine(rules=[rule])
    result = engine.evaluate("anything", [ToolCapability.EXECUTES_CODE])
    assert result is None


def test_prefix_rule() -> None:
    rule = PolicyRule(pattern="git_*", decision=ApprovalDecision.APPROVED)
    engine = ExecPolicyEngine(rules=[rule])
    result = engine.evaluate("git_status", [ToolCapability.READ_ONLY])
    assert result is None
    result2 = engine.evaluate("github_close", [ToolCapability.REQUIRES_APPROVAL])
    assert result2 is not None
