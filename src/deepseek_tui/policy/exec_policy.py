"""Command execution policy — rule engine, parser, and matcher."""

from __future__ import annotations

# Execpolicy decision enum.
#
# Wire shape: camelCase ``"allow" | "prompt" | "forbidden"`` when
# serialised as a string. The variant order ``Allow < Prompt <
# Forbidden`` is what :meth:`Policy.check` relies on when aggregating
# multiple matches (the most-restrictive decision wins). We preserve
# that ordering here.


from enum import Enum
from functools import total_ordering
from typing import cast
from pathlib import Path
from typing import Any
import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
import re
from collections.abc import Callable, Iterable
from dataclasses import field
import ast
import sys


__all__ = ["Decision"]


@total_ordering
class Decision(str, Enum):
    """Decision for a command evaluation.

    * ``ALLOW``      — run without further approval
    * ``PROMPT``     — request explicit user approval
    * ``FORBIDDEN``  — block outright
    """

    ALLOW = "allow"
    PROMPT = "prompt"
    FORBIDDEN = "forbidden"

    @classmethod
    def parse(cls, raw: str) -> Decision:
        """Parse a string; raise :class:`ExecPolicyError` on unknown values."""
        try:
            return cls(raw)
        except ValueError as err:
            raise ExecPolicyError.invalid_decision(raw) from err

    # --- Ordering (ALLOW < PROMPT < FORBIDDEN) ----------------------

    _RANKS: dict[str, int] = {}  # type: ignore[misc]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Decision):
            return NotImplemented
        ranks = _RANK
        return ranks[cast(str, self.value)] < ranks[cast(str, other.value)]


# Module-level rank table (kept separate from the enum class so the
# Enum machinery doesn't try to turn it into a member).
_RANK: dict[str, int] = {
    Decision.ALLOW.value: 0,
    Decision.PROMPT.value: 1,
    Decision.FORBIDDEN.value: 2,
}



# Errors raised by the execpolicy machinery.


__all__ = [
    "AmendError",
    "ExecPolicyError",
]


class ExecPolicyError(Exception):
    """Base class for execpolicy parse / evaluate errors.

    Instances can carry structured context via :attr:`data` for callers
    that want to inspect the offending inputs.
    """

    data: dict[str, Any]

    def __init__(self, message: str, **data: Any) -> None:
        super().__init__(message)
        self.data = data

    # --- Constructors -----------------------------------------------

    @classmethod
    def invalid_decision(cls, value: str) -> ExecPolicyError:
        return cls(f"invalid decision: {value}", value=value)

    @classmethod
    def invalid_pattern(cls, message: str) -> ExecPolicyError:
        return cls(f"invalid pattern element: {message}")

    @classmethod
    def invalid_example(cls, message: str) -> ExecPolicyError:
        return cls(f"invalid example: {message}")

    @classmethod
    def invalid_rule(cls, message: str) -> ExecPolicyError:
        return cls(f"invalid rule: {message}")

    @classmethod
    def example_did_not_match(
        cls, rules: list[str], examples: list[str]
    ) -> ExecPolicyError:
        return cls(
            "expected every example to match at least one rule. "
            f"rules: {rules!r}; unmatched examples: {examples!r}",
            rules=rules,
            unmatched_examples=examples,
        )

    @classmethod
    def example_did_match(cls, rule: str, example: str) -> ExecPolicyError:
        return cls(
            f"expected example to not match rule `{rule}`: {example}",
            rule=rule,
            example=example,
        )

    @classmethod
    def starlark(cls, message: str) -> ExecPolicyError:
        return cls(f"starlark error: {message}")


class AmendError(Exception):
    """Errors specific to ``blocking_append_allow_prefix_rule``.

    Instances carry structured context via :attr:`data`
    (path / directory / source).
    """

    data: dict[str, Any]

    def __init__(self, message: str, **data: Any) -> None:
        super().__init__(message)
        self.data = data

    @classmethod
    def empty_prefix(cls) -> AmendError:
        return cls("prefix rule requires at least one token")

    @classmethod
    def missing_parent(cls, path: Path) -> AmendError:
        return cls(f"policy path has no parent: {path}", path=path)

    @classmethod
    def create_policy_dir(cls, directory: Path, source: Exception) -> AmendError:
        err = cls(
            f"failed to create policy directory {directory}: {source}",
            directory=directory,
        )
        err.__cause__ = source
        return err

    @classmethod
    def open_policy_file(cls, path: Path, source: Exception) -> AmendError:
        err = cls(f"failed to open policy file {path}: {source}", path=path)
        err.__cause__ = source
        return err

    @classmethod
    def write_policy_file(cls, path: Path, source: Exception) -> AmendError:
        err = cls(f"failed to write to policy file {path}: {source}", path=path)
        err.__cause__ = source
        return err

    @classmethod
    def lock_policy_file(cls, path: Path, source: Exception) -> AmendError:
        err = cls(f"failed to lock policy file {path}: {source}", path=path)
        err.__cause__ = source
        return err

    @classmethod
    def read_policy_file(cls, path: Path, source: Exception) -> AmendError:
        err = cls(f"failed to read policy file {path}: {source}", path=path)
        err.__cause__ = source
        return err



# Rule data model for the execpolicy system.
#
# * :class:`PatternToken` — ``Single(str) | Alts(list[str])``
# * :class:`PrefixPattern` — ``{first: str, rest: list[PatternToken]}``
#   with :meth:`matches_prefix` returning the matched prefix slice
# * :class:`RuleMatch` — discriminated variants ``prefix_rule_match`` /
#   ``heuristics_rule_match`` with a :meth:`decision` accessor
# * :class:`PrefixRule` — a concrete rule carrying a pattern + decision
#   + optional justification, implementing :class:`Rule`
# * :func:`validate_match_examples` / :func:`validate_not_match_examples`
#
# The ``RuleMatch`` wire shape uses ``type`` discriminator values
# ``prefixRuleMatch`` / ``heuristicsRuleMatch`` (camelCase on the tag).




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
    acceptable alternatives (``Alts``).
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
        """Whether ``token`` is accepted at this position."""
        if self.value is not None:
            return self.value == token
        return token in self.alternatives_

    def alternatives(self) -> tuple[str, ...]:
        """Return the set of acceptable tokens at this position.

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

    The first token is always a literal string — that's how
    :class:`Policy` indexes rules by the head of the command
    (its ``program``).
    """

    first: str
    rest: tuple[PatternToken, ...]

    def matches_prefix(self, cmd: list[str]) -> list[str] | None:
        """Return the matched prefix slice, or ``None``.

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
    """Prefix-rule match result."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["prefixRuleMatch"] = "prefixRuleMatch"
    matched_prefix: list[str] = Field(alias="matchedPrefix")
    decision: Decision
    justification: str | None = None


class HeuristicsRuleMatch(BaseModel):
    """Heuristics-rule match result."""

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
    """Base rule interface."""

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
    """Concrete rule matching by :class:`PrefixPattern`."""

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
    """
    for example in not_matches:
        for rule in rules:
            if rule.matches(example) is not None:
                raise ExecPolicyError.example_did_match(
                    rule=repr(rule), example=_render_example(example)
                )


# Command matching helpers for execpolicy rules.
#
# Three public functions:
#
# * :func:`normalize_command` — shlex-parse + re-join, with heredoc
#   bodies stripped first (issue #419) so ``cat <<EOF > file\\nbody\\nEOF``
#   collapses to ``cat > file`` before pattern matching.
# * :func:`pattern_matches` — ``*`` wildcards → regex. Both ``pattern``
#   and ``command`` run through :func:`normalize_command` first.
# * :func:`strip_heredoc_bodies` — exposed for unit tests / callers that
#   want the intermediate form.
#
# Note on the here-string placeholder:
#
# * ``<<<`` (here-string) is rewritten to a placeholder before running
#   the heredoc regex. Python's ``re`` supports lookbehind (``(?<!<)``),
#   so in theory we could skip the placeholder dance — but we preserve
#   it byte-identically so captured test fixtures round-trip cleanly.


__all__ = ["normalize_command", "pattern_matches", "strip_heredoc_bodies"]


_HERESTRING_PLACEHOLDER = "\x01HERESTRING\x01"

# Regex:  <<-?\s*(?:['"]?)([A-Za-z_][A-Za-z0-9_]*)(?:['"]?)
# Allows optional `-` after `<<`, optional surrounding quotes on the
# delimiter, delimiter is a typical shell identifier.
_HEREDOC_RE = re.compile(r"""<<-?\s*(?:['"]?)([A-Za-z_][A-Za-z0-9_]*)(?:['"]?)""")


def normalize_command(command: str) -> str:
    """Normalize a command string by shlex-parsing and re-joining tokens.

    Heredoc bodies are stripped first (issue #419).
    """
    stripped = strip_heredoc_bodies(command)
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        # shlex raises on unbalanced quotes; fall back to whitespace split.
        tokens = [t for t in stripped.split() if t]
    if not tokens:
        # Keep whitespace-split fallback even when shlex succeeded but
        # returned empty.
        tokens = [t for t in stripped.split() if t]
    return " ".join(tokens)


def strip_heredoc_bodies(command: str) -> str:
    """Strip heredoc bodies from a multi-line command string.

    Recognises ``<<DELIM`` / ``<<-DELIM`` / ``<<'DELIM'`` / ``<<"DELIM"``
    and consumes the body up to the matching delimiter line. The
    here-string operator ``<<<`` is intentionally left alone — its
    body is the next token on the same line.
    """
    if "<<" not in command:
        return command

    # Hide `<<<` to avoid false matches from the heredoc regex.
    protected = command.replace("<<<", _HERESTRING_PLACEHOLDER)

    out_lines: list[str] = []
    lines_iter = iter(protected.split("\n"))
    for line in lines_iter:
        # A line may have multiple heredoc starts (`cmd <<A <<B`); strip
        # each and remember the last delimiter for body consumption.
        matches = list(_HEREDOC_RE.finditer(line))
        redacted = line
        delim: str | None = None
        for match in matches:
            redacted = redacted.replace(match.group(0), "", 1)
            delim = match.group(1)
        # Normalize redundant spacing created by the removals.
        cleaned = " ".join(piece for piece in redacted.split() if piece)
        out_lines.append(cleaned)
        if delim is not None:
            # Consume body lines until we hit the delimiter alone.
            for body in lines_iter:
                if body.strip() == delim:
                    break

    joined = "\n".join(out_lines)
    # Append a trailing `\n` so the downstream shlex sees a consistent
    # shape regardless of whether the input ended in a newline.
    if not joined.endswith("\n"):
        joined += "\n"
    # Restore the here-string operator.
    return joined.replace(_HERESTRING_PLACEHOLDER, "<<<")


def pattern_matches(pattern: str, command: str) -> bool:
    """Return True if ``pattern`` matches ``command`` after normalization.

    Patterns support ``*`` wildcards that match any substring.
    """
    norm_pattern = normalize_command(pattern)
    norm_command = normalize_command(command)

    if norm_pattern == "*":
        return True

    escaped = re.escape(norm_pattern).replace(r"\*", ".*")
    try:
        regex = re.compile(f"^{escaped}$")
    except re.error:
        return False
    return bool(regex.fullmatch(norm_command))


# Policy engine for the execpolicy system.
#
# * :class:`Policy` — maps first-token (program) → list of :class:`Rule`;
#   evaluates command-token lists with an optional heuristics fallback.
# * :class:`Evaluation` — decision + matched-rules payload emitted for
#   each evaluated command.
#
# ``check`` takes a ``heuristics_fallback``: any callable
# ``(list[str]) -> Decision``.




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

    The underlying storage is a multimap so several rules can share a
    first token (e.g. multiple ``git status`` prefix patterns with
    different justifications).
    """

    rules_by_program: dict[str, list[RuleRef]] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> Policy:
        """Construct an empty policy."""
        return cls()

    def rules(self) -> dict[str, list[RuleRef]]:
        """Expose the internal multimap."""
        return self.rules_by_program

    # --- Mutation ---------------------------------------------------

    def insert_rule(self, rule: RuleRef) -> None:
        """Index ``rule`` under its :meth:`program` key."""
        program = rule.program()
        self.rules_by_program.setdefault(program, []).append(rule)

    def add_prefix_rule(
        self, prefix: list[str], decision: Decision
    ) -> None:
        """Add a simple :class:`PrefixRule` from ``prefix`` tokens."""
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

        Returns a non-empty :class:`Evaluation` because
        ``heuristics_fallback`` always supplies a decision.
        """
        matched_rules = self.matches_for_command(cmd, heuristics_fallback)
        return Evaluation.from_matches(matched_rules)

    def check_multiple(
        self,
        commands: Iterable[list[str]],
        heuristics_fallback: HeuristicsFallback,
    ) -> Evaluation:
        """Evaluate several commands and aggregate matches."""
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
        """Return all matches for ``cmd``, optionally with heuristics fallback."""
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

    The wire shape uses camelCase for ``matchedRules``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    decision: Decision
    matched_rules: list[RuleMatch] = Field(alias="matchedRules")

    def is_match(self) -> bool:
        """True iff any rule is a real prefix match (not a heuristics fallback)."""
        return any(
            isinstance(rule, PrefixRuleMatch) for rule in self.matched_rules
        )

    @classmethod
    def from_matches(cls, matched_rules: list[RuleMatch]) -> Evaluation:
        """Build an Evaluation; aggregate decision is the max severity.

        Caller must ensure ``matched_rules`` is non-empty; an empty list
        raises an exception rather than producing a decision.
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


# Mini-Starlark parser for execpolicy rule files.
#
# Policy files use a Starlark-flavoured syntax that looks like this::
#
#     prefix_rule(pattern=["git", "status"], decision="allow")
#     prefix_rule(
#         pattern=["git", ["log", "diff"]],
#         decision="allow",
#         justification="read-only git inspection",
#         match=["git log", "git diff HEAD"],
#         not_match=["git push"],
#     )
#
# Full Starlark is a Python-like DSL with ``def`` / ``if`` / ``for`` /
# ``import`` / f-strings. We don't need that surface — only
# ``prefix_rule`` calls with literal-list / literal-string arguments.
#
# This module implements a ~200 LOC subset sufficient to parse the
# default policy. Grammar:
#
#     module     := statement*
#     statement  := COMMENT | call | blank
#     call       := IDENT '(' args ')' NEWLINE
#     args       := (arg (',' arg)*)?
#     arg        := IDENT '=' expr | expr
#     expr       := STRING | LIST
#     LIST       := '[' (expr (',' expr)*)? ']'
#
# The goal is faithful ``prefix_rule`` behaviour — not general Starlark
# compatibility. Unsupported syntax (``def`` / ``if`` / f-strings /
# ``import``) surfaces via a clear :class:`ExecPolicyError` so users
# notice when a policy file uses features beyond our subset.



__all__ = ["PolicyParser"]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class PolicyParser:
    """Parse one or more policy files into a :class:`Policy`.

    Call :meth:`parse` for each file, then :meth:`build` to realise the
    :class:`Policy`.
    """

    def __init__(self) -> None:
        self._rules: list[RuleRef] = []

    def parse(self, identifier: str, contents: str) -> None:
        """Parse a single policy file. ``identifier`` is used in errors.

        We piggy-back on Python's own AST parser because the accepted
        subset is just Python call syntax; Python's error messages are
        good enough. On unsupported constructs (statements other than
        bare calls) we raise :class:`ExecPolicyError.starlark`.
        """
        try:
            module = ast.parse(contents, filename=identifier, mode="exec")
        except SyntaxError as err:
            raise ExecPolicyError.starlark(
                f"{identifier}: {err.msg} (line {err.lineno})"
            ) from err

        for stmt in module.body:
            if not isinstance(stmt, ast.Expr) or not isinstance(
                stmt.value, ast.Call
            ):
                raise ExecPolicyError.starlark(
                    f"{identifier} line {stmt.lineno}: "
                    "only bare function calls are supported at top level "
                    "(policies use prefix_rule(...) etc.)"
                )
            call = stmt.value
            if not isinstance(call.func, ast.Name):
                raise ExecPolicyError.starlark(
                    f"{identifier} line {call.lineno}: "
                    "call target must be a plain identifier"
                )
            func_name = call.func.id
            if func_name != "prefix_rule":
                raise ExecPolicyError.starlark(
                    f"{identifier} line {call.lineno}: "
                    f"unknown policy builtin '{func_name}' "
                    "(only 'prefix_rule' is supported)"
                )
            args = _extract_kwargs(call, identifier)
            self._rules.extend(_build_prefix_rule_rules(args, identifier))

    def build(self) -> Policy:
        """Realise the accumulated rules into a :class:`Policy`."""
        policy = Policy.empty()
        for rule in self._rules:
            policy.insert_rule(rule)
        return policy


# ---------------------------------------------------------------------------
# prefix_rule implementation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _PrefixRuleArgs:
    pattern: list[Any]
    decision: str
    match: list[Any]
    not_match: list[Any]
    justification: str | None


def _extract_kwargs(call: ast.Call, identifier: str) -> _PrefixRuleArgs:
    """Parse a ``prefix_rule(...)`` call into a typed argument bundle.

    Positional args are not supported — the Starlark signature accepts
    `pattern` as the sole required arg, but the real policy files always
    use keyword form. Enforcing kwargs keeps the parser simple and the
    error messages precise.
    """
    if call.args:
        raise ExecPolicyError.starlark(
            f"{identifier} line {call.lineno}: "
            "prefix_rule() does not accept positional arguments"
        )

    allowed = {"pattern", "decision", "match", "not_match", "justification"}
    seen: dict[str, ast.expr] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            raise ExecPolicyError.starlark(
                f"{identifier} line {call.lineno}: "
                "**kwargs is not supported in prefix_rule()"
            )
        if keyword.arg not in allowed:
            raise ExecPolicyError.starlark(
                f"{identifier} line {call.lineno}: "
                f"unknown prefix_rule argument '{keyword.arg}'"
            )
        if keyword.arg in seen:
            raise ExecPolicyError.starlark(
                f"{identifier} line {call.lineno}: "
                f"duplicate prefix_rule argument '{keyword.arg}'"
            )
        seen[keyword.arg] = keyword.value

    if "pattern" not in seen:
        raise ExecPolicyError.invalid_pattern(
            f"{identifier} line {call.lineno}: "
            "prefix_rule() requires a `pattern=` argument"
        )

    pattern = _eval_literal(seen["pattern"], identifier)
    if not isinstance(pattern, list):
        raise ExecPolicyError.invalid_pattern(
            f"{identifier} line {call.lineno}: "
            "pattern must be a list of strings or lists"
        )

    decision_node = seen.get("decision")
    decision = "allow"
    if decision_node is not None:
        decision_value = _eval_literal(decision_node, identifier)
        if not isinstance(decision_value, str):
            raise ExecPolicyError.starlark(
                f"{identifier} line {call.lineno}: "
                "decision must be a string"
            )
        decision = decision_value

    match_node = seen.get("match")
    match_val = _eval_literal(match_node, identifier) if match_node else []
    if match_val and not isinstance(match_val, list):
        raise ExecPolicyError.invalid_example(
            f"{identifier} line {call.lineno}: match must be a list"
        )

    not_match_node = seen.get("not_match")
    not_match_val = (
        _eval_literal(not_match_node, identifier) if not_match_node else []
    )
    if not_match_val and not isinstance(not_match_val, list):
        raise ExecPolicyError.invalid_example(
            f"{identifier} line {call.lineno}: not_match must be a list"
        )

    justification: str | None = None
    justification_node = seen.get("justification")
    if justification_node is not None:
        just_val = _eval_literal(justification_node, identifier)
        if not isinstance(just_val, str):
            raise ExecPolicyError.invalid_rule(
                "justification must be a string"
            )
        if not just_val.strip():
            raise ExecPolicyError.invalid_rule("justification cannot be empty")
        justification = just_val

    return _PrefixRuleArgs(
        pattern=pattern,
        decision=decision,
        match=match_val if match_val else [],
        not_match=not_match_val if not_match_val else [],
        justification=justification,
    )


def _eval_literal(node: ast.expr, identifier: str) -> Any:
    """Evaluate a literal Python expression (str / list / tuple / None).

    Uses :func:`ast.literal_eval` internally, which rejects function
    calls, attribute access, comprehensions — exactly what we want.
    """
    try:
        return ast.literal_eval(node)
    except ValueError as err:
        raise ExecPolicyError.starlark(
            f"{identifier} line {getattr(node, 'lineno', '?')}: "
            f"non-literal expression: {err}"
        ) from err


def _build_prefix_rule_rules(
    args: _PrefixRuleArgs, identifier: str
) -> list[RuleRef]:
    """Build one or more :class:`PrefixRule` instances from parsed args.

    The first pattern token may be either a single string or a list of
    alternatives; each alternative spawns a separate rule keyed on
    that first token.
    """
    decision = Decision.parse(args.decision)

    pattern_tokens = _parse_pattern(args.pattern, identifier)
    if not pattern_tokens:
        raise ExecPolicyError.invalid_pattern("pattern cannot be empty")

    first_token, *rest_tokens = pattern_tokens
    rest_tuple = tuple(rest_tokens)

    rules: list[RuleRef] = []
    for head in first_token.alternatives():
        rules.append(
            PrefixRule(
                pattern=PrefixPattern(first=head, rest=rest_tuple),
                decision=decision,
                justification=args.justification,
            )
        )

    matches = _parse_examples(args.match, identifier)
    not_matches = _parse_examples(args.not_match, identifier)
    validate_not_match_examples(rules, not_matches)
    validate_match_examples(rules, matches)
    return rules


def _parse_pattern(raw: list[Any], identifier: str) -> list[PatternToken]:
    """Convert the parsed list literal into a list of PatternTokens."""
    if not raw:
        raise ExecPolicyError.invalid_pattern("pattern cannot be empty")

    tokens: list[PatternToken] = []
    for elem in raw:
        if isinstance(elem, str):
            tokens.append(PatternToken.single(elem))
            continue
        if isinstance(elem, list):
            if not elem:
                raise ExecPolicyError.invalid_pattern(
                    "pattern alternatives cannot be empty"
                )
            alt_strings: list[str] = []
            for alt in elem:
                if not isinstance(alt, str):
                    raise ExecPolicyError.invalid_pattern(
                        "pattern alternative must be a string "
                        f"(got {type(alt).__name__})"
                    )
                alt_strings.append(alt)
            if len(alt_strings) == 1:
                tokens.append(PatternToken.single(alt_strings[0]))
            else:
                tokens.append(PatternToken.alts(alt_strings))
            continue
        raise ExecPolicyError.invalid_pattern(
            "pattern element must be a string or list of strings "
            f"(got {type(elem).__name__}) in {identifier}"
        )
    return tokens


def _parse_examples(raw: list[Any], identifier: str) -> list[list[str]]:
    """Parse the `match` / `not_match` example list."""
    out: list[list[str]] = []
    for elem in raw:
        if isinstance(elem, str):
            tokens = _tokenize_string_example(elem)
            out.append(tokens)
        elif isinstance(elem, list):
            as_list: list[str] = []
            for token in elem:
                if not isinstance(token, str):
                    raise ExecPolicyError.invalid_example(
                        "example tokens must be strings "
                        f"(got {type(token).__name__})"
                    )
                as_list.append(token)
            if not as_list:
                raise ExecPolicyError.invalid_example(
                    "example cannot be an empty list"
                )
            out.append(as_list)
        else:
            raise ExecPolicyError.invalid_example(
                "example must be a string or list of strings "
                f"(got {type(elem).__name__}) in {identifier}"
            )
    return out


def _tokenize_string_example(raw: str) -> list[str]:
    """Shlex-split a string example."""
    import shlex

    try:
        tokens = shlex.split(raw)
    except ValueError as err:
        raise ExecPolicyError.invalid_example(
            "example string has invalid shell syntax"
        ) from err
    if not tokens:
        raise ExecPolicyError.invalid_example(
            "example cannot be an empty string"
        )
    return tokens


# Execpolicy rules loaded from TOML configuration.
# This is the lightweight TOML-based rules layer — the parallel system to
# the Starlark-based :mod:`deepseek_tui.execpolicy.parser` / :mod:`policy`.
#
# Wire format::
#
#     [rules.git]
#     allow = ["git status", "git log *"]
#     deny = ["git push --force"]
#
#     [rules.danger]
#     deny = ["rm -rf /", "rm -rf /*"]
#
# Evaluation semantics:
#
# 1. Scan every ``deny`` pattern in every group in insertion order.
#    First match → ``Deny(reason)``.
# 2. Scan every ``allow`` pattern. First match → ``Allow``.
# 3. No match → ``AskUser("execpolicy: no matching allow rule")``.



__all__ = [
    "ExecPolicyConfig",
    "ExecPolicyDecision",
    "ExecPolicyDecisionKind",
    "RuleSet",
    "default_execpolicy_path",
    "load_default_policy",
]


if sys.version_info >= (3, 11):
    import tomllib as _toml_reader
else:  # pragma: no cover — py3.10 fallback
    import tomli as _toml_reader  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# ExecPolicyDecision
# ---------------------------------------------------------------------------


class ExecPolicyDecisionKind:
    """Tag constants for the :class:`ExecPolicyDecision` enum.

    Used with :func:`isinstance` — we don't use a real Enum because
    ``Deny`` / ``AskUser`` carry a reason string.
    """

    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


@dataclass(frozen=True, slots=True)
class ExecPolicyDecision:
    """Decision emitted by the TOML-based execpolicy layer.

    Use the class methods (:meth:`allow`, :meth:`deny`, :meth:`ask_user`)
    instead of the constructor for a clean call-site.
    """

    kind: str
    reason: str = ""

    @classmethod
    def allow(cls) -> ExecPolicyDecision:
        return cls(kind=ExecPolicyDecisionKind.ALLOW)

    @classmethod
    def deny(cls, reason: str) -> ExecPolicyDecision:
        return cls(kind=ExecPolicyDecisionKind.DENY, reason=reason)

    @classmethod
    def ask_user(cls, reason: str) -> ExecPolicyDecision:
        return cls(kind=ExecPolicyDecisionKind.ASK_USER, reason=reason)

    @property
    def is_allow(self) -> bool:
        return self.kind == ExecPolicyDecisionKind.ALLOW

    @property
    def is_deny(self) -> bool:
        return self.kind == ExecPolicyDecisionKind.DENY

    @property
    def is_ask_user(self) -> bool:
        return self.kind == ExecPolicyDecisionKind.ASK_USER


# ---------------------------------------------------------------------------
# TOML schema
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RuleSet:
    """``[rules.<group>]`` table: ``allow`` / ``deny`` pattern lists."""

    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecPolicyConfig:
    """Top-level TOML policy config.

    The key order of ``rules`` is preserved on insertion so that the
    scan order in :meth:`evaluate` is deterministic. We use ``dict``
    (insertion-order) rather than a sorted map because that's more
    useful for users authoring custom policies (they can reason about
    match precedence by source order).
    """

    rules: dict[str, RuleSet] = field(default_factory=dict)

    # --- Parsing ----------------------------------------------------

    @classmethod
    def from_str(cls, contents: str) -> ExecPolicyConfig:
        """Parse a TOML string into an :class:`ExecPolicyConfig`."""
        try:
            data = _toml_reader.loads(contents)
        except _toml_reader.TOMLDecodeError as err:
            raise ValueError(f"failed to parse execpolicy.toml: {err}") from err
        return cls._from_dict(data)

    @classmethod
    def from_path(cls, path: Path) -> ExecPolicyConfig:
        """Parse a TOML file path."""
        try:
            with path.open("rb") as fh:
                data = _toml_reader.load(fh)
        except OSError as err:
            raise ValueError(
                f"failed to read execpolicy file {path}: {err}"
            ) from err
        except _toml_reader.TOMLDecodeError as err:
            raise ValueError(
                f"failed to parse execpolicy file {path}: {err}"
            ) from err
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: object) -> ExecPolicyConfig:
        if not isinstance(data, dict):
            raise ValueError("top-level execpolicy.toml must be a table")
        rules_raw = data.get("rules", {})
        if not isinstance(rules_raw, dict):
            raise ValueError("`rules` must be a table")
        rules: dict[str, RuleSet] = {}
        for group, entry in rules_raw.items():
            if not isinstance(entry, dict):
                raise ValueError(
                    f"[rules.{group}] must be a table, got {type(entry).__name__}"
                )
            allow = entry.get("allow", [])
            deny = entry.get("deny", [])
            if not isinstance(allow, list) or not all(
                isinstance(p, str) for p in allow
            ):
                raise ValueError(
                    f"[rules.{group}].allow must be a list of strings"
                )
            if not isinstance(deny, list) or not all(
                isinstance(p, str) for p in deny
            ):
                raise ValueError(
                    f"[rules.{group}].deny must be a list of strings"
                )
            rules[group] = RuleSet(allow=list(allow), deny=list(deny))
        return cls(rules=rules)

    # --- Evaluation -------------------------------------------------

    def evaluate(self, command: str) -> ExecPolicyDecision:
        """Evaluate ``command`` against the deny- then allow-pattern lists.

        Deny wins over allow unconditionally; no match falls back to
        ``AskUser``.
        """
        for group, rule_set in self.rules.items():
            for pattern in rule_set.deny:
                if pattern_matches(pattern, command):
                    return ExecPolicyDecision.deny(
                        f"execpolicy denied by {group}: {pattern}"
                    )
        for rule_set in self.rules.values():
            for pattern in rule_set.allow:
                if pattern_matches(pattern, command):
                    return ExecPolicyDecision.allow()
        return ExecPolicyDecision.ask_user(
            "execpolicy: no matching allow rule"
        )


# ---------------------------------------------------------------------------
# Default path lookup
# ---------------------------------------------------------------------------


def default_execpolicy_path() -> Path | None:
    """``~/.deepseek/execpolicy.toml`` — or ``None`` if HOME unavailable.

    User-level — policy travels with the operator, not with each checkout.
    """
    from deepseek_tui.config.paths import user_execpolicy_path

    try:
        return user_execpolicy_path()
    except (RuntimeError, OSError):  # pragma: no cover — platform quirks
        return None


class TomlBackedPolicy:
    """Adapt :class:`ExecPolicyConfig` TOML rules to the ``check`` interface
    the shell tools expect from ``ToolContext.policy``.

    Mapping:

    * a matching ``deny`` pattern → :attr:`Decision.FORBIDDEN`
    * a matching ``allow`` pattern → :attr:`Decision.ALLOW`
    * no match → safety-heuristic fallback, but only its FORBIDDEN tier is
      enforced here. Interactive approval prompting is owned by the
      engine-level approval flow (``ExecPolicyEngine`` + approval handler),
      so a heuristic PROMPT must not re-block a command the user already
      approved — it maps to ALLOW at this layer.
    """

    def __init__(self, config: ExecPolicyConfig) -> None:
        self._config = config

    def check(
        self, cmd: list[str], heuristics_fallback: HeuristicsFallback
    ) -> Evaluation:
        command = " ".join(cmd)
        verdict = self._config.evaluate(command)
        if verdict.is_deny:
            decision = Decision.FORBIDDEN
        elif verdict.is_allow:
            decision = Decision.ALLOW
        elif heuristics_fallback(list(cmd)) == Decision.FORBIDDEN:
            decision = Decision.FORBIDDEN
        else:
            decision = Decision.ALLOW
        return Evaluation.model_validate(
            {"decision": decision, "matchedRules": []}
        )


def load_user_policy() -> TomlBackedPolicy | None:
    """Load ``~/.deepseek/execpolicy.toml`` as a shell-tool policy gate.

    Returns ``None`` when the file doesn't exist (the common case), so
    callers can leave ``ToolContext.policy`` unset and rely on the
    engine-level approval flow alone.
    """
    config = load_default_policy()
    if config is None:
        return None
    return TomlBackedPolicy(config)


def load_default_policy() -> ExecPolicyConfig | None:
    """Load the default policy if it exists; return ``None`` otherwise."""
    path = default_execpolicy_path()
    if path is None or not path.exists():
        return None
    return ExecPolicyConfig.from_path(path)