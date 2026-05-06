"""Rule data model for the Rust-parity execpolicy system.

Mirrors ``crates/tui/src/execpolicy/rule.rs`` (160 LOC):

* :class:`PatternToken` — ``Single(str) | Alts(list[str])``
* :class:`PrefixPattern` — ``{first: str, rest: list[PatternToken]}``
  with :meth:`matches_prefix` returning the matched prefix slice
* :class:`RuleMatch` — discriminated variants ``prefix_rule_match`` /
  ``heuristics_rule_match`` with a :meth:`decision` accessor
* :class:`PrefixRule` — a concrete rule carrying a pattern + decision
  + optional justification, implementing :class:`Rule`
* :func:`validate_match_examples` / :func:`validate_not_match_examples`

The ``RuleMatch`` wire shape uses ``type`` discriminator values
``prefixRuleMatch`` / ``heuristicsRuleMatch`` to match Rust's
``#[serde(rename_all = "camelCase")]`` on the enum tag.
"""

from __future__ import annotations

import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .decision import Decision
from .errors import ExecPolicyError

__all__ = [
    "PatternToken",
    "PrefixPattern",
    "PrefixRule",
    "PrefixRuleMatch",
    "HeuristicsRuleMatch",
    "RuleMatch",
    "Rule",
    "RuleRef",
    "validate_match_examples",
    "validate_not_match_examples",
]


# ---------------------------------------------------------------------------
# PatternToken — closed ADT, not Pydantic (it's immutable and hashable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatternToken:
    """One position in a :class:`PrefixPattern`.

    Carries either a single literal string (``Single``) or a set of
    acceptable alternatives (``Alts``). Mirrors the Rust enum::

        enum PatternToken {
            Single(String),
            Alts(Vec<String>),
        }
    """

    # None means Alts; non-None means Single.
    value: str | None
    alternatives_: tuple[str, ...] = ()

    @classmethod
    def single(cls, value: str) -> PatternToken:
        return cls(value=value, alternatives_=())

    @classmethod
    def alts(cls, alternatives: list[str]) -> PatternToken:
        return cls(value=None, alternatives_=tuple(alternatives))

    @property
    def is_single(self) -> bool:
        return self.value is not None

    def matches(self, token: str) -> bool:
        """Mirror Rust ``PatternToken::matches`` (rule.rs:19-24)."""
        if self.value is not None:
            return self.value == token
        return token in self.alternatives_

    def alternatives(self) -> tuple[str, ...]:
        """Return the set of acceptable tokens at this position.

        Mirror Rust ``PatternToken::alternatives`` (rule.rs:26-31).
        For ``Single`` returns a single-element slice.
        """
        if self.value is not None:
            return (self.value,)
        return self.alternatives_


# ---------------------------------------------------------------------------
# PrefixPattern
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrefixPattern:
    """Prefix matcher keyed by a fixed first token.

    Mirrors Rust ``PrefixPattern`` (rule.rs:36-40). The first token
    is always a literal string — that's how :class:`Policy` indexes
    rules by the head of the command (its ``program``).
    """

    first: str
    rest: tuple[PatternToken, ...]

    def matches_prefix(self, cmd: list[str]) -> list[str] | None:
        """Return the matched prefix slice, or ``None``.

        Mirrors Rust ``PrefixPattern::matches_prefix`` (rule.rs:43-56).
        Checks length ≥ pattern length and the first token equals
        :attr:`first`, then validates each subsequent pattern position.
        """
        pattern_length = len(self.rest) + 1
        if len(cmd) < pattern_length or cmd[0] != self.first:
            return None
        for pattern_token, cmd_token in zip(self.rest, cmd[1:pattern_length], strict=True):
            if not pattern_token.matches(cmd_token):
                return None
        return list(cmd[:pattern_length])


# ---------------------------------------------------------------------------
# RuleMatch (discriminated Pydantic union)
# ---------------------------------------------------------------------------


class PrefixRuleMatch(BaseModel):
    """Rust variant ``RuleMatch::PrefixRuleMatch`` (rule.rs:61-71)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["prefixRuleMatch"] = "prefixRuleMatch"
    matched_prefix: list[str] = Field(alias="matchedPrefix")
    decision: Decision
    justification: str | None = None


class HeuristicsRuleMatch(BaseModel):
    """Rust variant ``RuleMatch::HeuristicsRuleMatch`` (rule.rs:72-76)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["heuristicsRuleMatch"] = "heuristicsRuleMatch"
    command: list[str]
    decision: Decision


RuleMatch = Annotated[
    PrefixRuleMatch | HeuristicsRuleMatch,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Rule interface + PrefixRule implementation
# ---------------------------------------------------------------------------


class Rule(ABC):
    """Rust ``Rule`` trait (rule.rs:95-99)."""

    @abstractmethod
    def program(self) -> str:
        """First token this rule can match."""

    @abstractmethod
    def matches(self, cmd: list[str]) -> PrefixRuleMatch | HeuristicsRuleMatch | None:
        """Return a :class:`RuleMatch` if the rule matches ``cmd``."""


# Python equivalent of ``type RuleRef = Arc<dyn Rule>``. We don't need
# reference-counting, so a plain Rule reference is enough.
RuleRef = Rule


@dataclass(frozen=True, slots=True)
class PrefixRule(Rule):
    """Concrete rule matching by :class:`PrefixPattern`.

    Mirrors Rust ``PrefixRule`` (rule.rs:88-93) + its ``Rule`` impl
    (rule.rs:103-117).
    """

    pattern: PrefixPattern
    decision: Decision
    justification: str | None = None

    def program(self) -> str:
        return self.pattern.first

    def matches(self, cmd: list[str]) -> PrefixRuleMatch | None:
        matched = self.pattern.matches_prefix(cmd)
        if matched is None:
            return None
        return PrefixRuleMatch.model_validate(
            {
                "matchedPrefix": matched,
                "decision": self.decision,
                "justification": self.justification,
            }
        )


# ---------------------------------------------------------------------------
# Example validation
# ---------------------------------------------------------------------------


def _render_example(example: list[str]) -> str:
    """Best-effort ``shlex.join``; falls back to a marker string on failure."""
    try:
        return shlex.join(example)
    except Exception:  # pragma: no cover — shlex.join never raises in practice
        return "unable to render example"


def validate_match_examples(
    rules: list[RuleRef], matches: list[list[str]]
) -> None:
    """Raise :class:`ExecPolicyError.example_did_not_match` if any
    example fails to match any rule.

    Mirrors Rust ``validate_match_examples`` (rule.rs:120-142).
    """
    unmatched: list[str] = []
    for example in matches:
        if any(rule.matches(example) is not None for rule in rules):
            continue
        unmatched.append(_render_example(example))
    if not unmatched:
        return
    raise ExecPolicyError.example_did_not_match(
        rules=[repr(r) for r in rules], examples=unmatched
    )


def validate_not_match_examples(
    rules: list[RuleRef], not_matches: list[list[str]]
) -> None:
    """Raise :class:`ExecPolicyError.example_did_match` if any rule
    matches one of the negative examples.

    Mirrors Rust ``validate_not_match_examples`` (rule.rs:145-160).
    """
    for example in not_matches:
        for rule in rules:
            if rule.matches(example) is not None:
                raise ExecPolicyError.example_did_match(
                    rule=repr(rule), example=_render_example(example)
                )
