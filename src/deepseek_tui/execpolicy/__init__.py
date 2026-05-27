"""Execpolicy — Rust-parity command-execution policy + legacy tool-approval layer.

Two orthogonal subsystems live in this package:

1. **Rust-parity Policy** (``policy.py`` + ``parser.py`` + ``matcher.py`` +
   ``rule.py`` + ``rules.py`` + ``amend.py`` + ``decision.py``) evaluates
   *shell command token lists* (e.g. ``["git", "status"]``) against a
   set of prefix-matched rules, producing a :class:`Decision` of
   ``Allow`` / ``Prompt`` / ``Forbidden``. Designed to back the shell
   execution tool in Stage 3.

2. **Legacy tool-approval** (``engine.py`` + ``models.py``) evaluates
   *tool names + capability sets* (e.g. ``write_file`` with
   ``ToolCapability.WRITES_FILES``) to decide whether the engine
   should pause for user approval before running a tool. Designed to
   back the turn-loop's approval gate.

These are complementary, not competing — command-level execution and
tool-level approval are different concerns — so the two live in
parallel without being collapsed.
"""

from .amend import blocking_append_allow_prefix_rule
from .decision import Decision
from .engine import ExecPolicyEngine
from .errors import AmendError, ExecPolicyError
from .matcher import normalize_command, pattern_matches, strip_heredoc_bodies
from .models import (
    ApprovalDecision,
    ApprovalRequest,
    PolicyRule,
    RiskLevel,
    ToolCategory,
)
from .parser import PolicyParser
from .policy import Evaluation, HeuristicsFallback, Policy
from .rule import (
    HeuristicsRuleMatch,
    PatternToken,
    PrefixPattern,
    PrefixRule,
    PrefixRuleMatch,
    Rule,
    RuleMatch,
    RuleRef,
    validate_match_examples,
    validate_not_match_examples,
)
from .rules import (
    ExecPolicyConfig,
    ExecPolicyDecision,
    ExecPolicyDecisionKind,
    RuleSet,
    default_execpolicy_path,
    load_default_policy,
)
from .sandbox import (
    CommandSpec,
    ExecEnv,
    ExecutionSandboxPolicy,
    SANDBOX_MANAGER,
    SandboxManager,
    SandboxType,
    apply_sandbox_metadata,
    sandbox_policy_for_mode,
)

__all__ = [
    # Rust-parity core
    "AmendError",
    "Decision",
    "Evaluation",
    "ExecPolicyConfig",
    "ExecPolicyDecision",
    "ExecPolicyDecisionKind",
    "ExecPolicyError",
    "HeuristicsFallback",
    "HeuristicsRuleMatch",
    "PatternToken",
    "Policy",
    "PolicyParser",
    "PrefixPattern",
    "PrefixRule",
    "PrefixRuleMatch",
    "Rule",
    "RuleMatch",
    "RuleRef",
    "RuleSet",
    "blocking_append_allow_prefix_rule",
    "default_execpolicy_path",
    "load_default_policy",
    "normalize_command",
    "pattern_matches",
    "strip_heredoc_bodies",
    "validate_match_examples",
    "validate_not_match_examples",
    # Legacy tool-approval
    "ApprovalDecision",
    "ApprovalRequest",
    "ExecPolicyEngine",
    "PolicyRule",
    "RiskLevel",
    "CommandSpec",
    "ExecEnv",
    "ExecutionSandboxPolicy",
    "SANDBOX_MANAGER",
    "SandboxManager",
    "SandboxType",
    "ToolCategory",
    "apply_sandbox_metadata",
    "sandbox_policy_for_mode",
    "sync_execution_sandbox_policy",
]
