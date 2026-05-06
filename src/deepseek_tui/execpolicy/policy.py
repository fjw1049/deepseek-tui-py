"""Policy engine for the Rust-parity execpolicy system.

Mirrors ``crates/tui/src/execpolicy/policy.rs`` (145 LOC):

* :class:`Policy` — maps first-token (program) → list of :class:`Rule`;
  evaluates command-token lists with an optional heuristics fallback.
* :class:`Evaluation` — decision + matched-rules payload emitted for
  each evaluated command.

Rust's ``check`` takes ``heuristics_fallback: &F`` where ``F: Fn(&[String]) -> Decision``.
Python translation: any callable ``(list[str]) -> Decision``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .decision import Decision
from .errors import ExecPolicyError
from .rule import (
    HeuristicsRuleMatch,
    PatternToken,
    PrefixPattern,
    PrefixRule,
    PrefixRuleMatch,
    RuleMatch,
    RuleRef,
)

__all__ = [
    "Evaluation",
    "HeuristicsFallback",
    "Policy",
]


# Type alias for the heuristics-fallback callable.
HeuristicsFallback = Callable[[list[str]], Decision]


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Policy:
    """Indexed collection of :class:`Rule` keyed by command first-token.

    Rust ``Policy`` (policy.rs:16-117). The underlying storage is a
    multimap so several rules can share a first token (e.g. multiple
    ``git status`` prefix patterns with different justifications).
    """

    rules_by_program: dict[str, list[RuleRef]] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> Policy:
        """Construct an empty policy (Rust ``Policy::empty``)."""
        return cls()

    def rules(self) -> dict[str, list[RuleRef]]:
        """Expose the internal multimap (Rust ``Policy::rules``)."""
        return self.rules_by_program

    # --- Mutation ---------------------------------------------------

    def insert_rule(self, rule: RuleRef) -> None:
        """Index ``rule`` under its :meth:`program` key."""
        program = rule.program()
        self.rules_by_program.setdefault(program, []).append(rule)

    def add_prefix_rule(
        self, prefix: list[str], decision: Decision
    ) -> None:
        """Add a simple :class:`PrefixRule` from ``prefix`` tokens.

        Mirrors Rust ``Policy::add_prefix_rule`` (policy.rs:34-54).
        """
        if not prefix:
            raise ExecPolicyError.invalid_pattern("prefix cannot be empty")
        first_token = prefix[0]
        rest_tokens = tuple(
            PatternToken.single(token) for token in prefix[1:]
        )
        rule = PrefixRule(
            pattern=PrefixPattern(first=first_token, rest=rest_tokens),
            decision=decision,
            justification=None,
        )
        self.insert_rule(rule)

    # --- Evaluation -------------------------------------------------

    def check(
        self, cmd: list[str], heuristics_fallback: HeuristicsFallback
    ) -> Evaluation:
        """Evaluate ``cmd``, falling back to heuristics when no rule matches.

        Mirrors Rust ``Policy::check`` (policy.rs:56-62). Returns a
        non-empty :class:`Evaluation` because ``heuristics_fallback``
        always supplies a decision.
        """
        matched_rules = self.matches_for_command(cmd, heuristics_fallback)
        return Evaluation.from_matches(matched_rules)

    def check_multiple(
        self,
        commands: Iterable[list[str]],
        heuristics_fallback: HeuristicsFallback,
    ) -> Evaluation:
        """Evaluate several commands and aggregate matches.

        Mirrors Rust ``Policy::check_multiple`` (policy.rs:65-83).
        """
        aggregated: list[RuleMatch] = []
        for command in commands:
            aggregated.extend(
                self.matches_for_command(command, heuristics_fallback)
            )
        return Evaluation.from_matches(aggregated)

    def matches_for_command(
        self,
        cmd: list[str],
        heuristics_fallback: HeuristicsFallback | None = None,
    ) -> list[RuleMatch]:
        """Return all matches for ``cmd``, optionally with heuristics fallback.

        Mirrors Rust ``Policy::matches_for_command`` (policy.rs:92-116).
        """
        matched_rules: list[RuleMatch] = []
        if cmd:
            rules_for_program = self.rules_by_program.get(cmd[0], [])
            for rule in rules_for_program:
                match = rule.matches(cmd)
                if match is not None:
                    matched_rules.append(match)

        if not matched_rules and heuristics_fallback is not None:
            matched_rules.append(
                HeuristicsRuleMatch(
                    command=list(cmd),
                    decision=heuristics_fallback(list(cmd)),
                )
            )
        return matched_rules


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class Evaluation(BaseModel):
    """Aggregated evaluation result.

    Mirrors Rust ``Evaluation`` (policy.rs:119-145). The wire shape
    uses camelCase for ``matchedRules`` (Rust serde rename).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    decision: Decision
    matched_rules: list[RuleMatch] = Field(alias="matchedRules")

    def is_match(self) -> bool:
        """True iff any rule is a real prefix match (not a heuristics fallback).

        Mirrors Rust ``Evaluation::is_match`` (policy.rs:127-132).
        """
        return any(
            isinstance(rule, PrefixRuleMatch) for rule in self.matched_rules
        )

    @classmethod
    def from_matches(cls, matched_rules: list[RuleMatch]) -> Evaluation:
        """Build an Evaluation; aggregate decision is the max severity.

        Mirrors Rust ``Evaluation::from_matches`` (policy.rs:134-144).
        Caller must ensure ``matched_rules`` is non-empty; the Rust
        implementation panics otherwise, we mirror with an exception.
        """
        if not matched_rules:
            raise ExecPolicyError.invalid_rule(
                "Evaluation.from_matches: matched_rules must be non-empty"
            )
        decision = max(rule.decision for rule in matched_rules)
        return cls.model_validate(
            {"decision": decision, "matchedRules": _dump_rules(matched_rules)}
        )


def _dump_rules(rules: list[RuleMatch]) -> list[Any]:
    """Convert RuleMatch instances to dicts for Pydantic validation."""
    out: list[Any] = []
    for rule in rules:
        out.append(rule.model_dump(by_alias=True))
    return out
