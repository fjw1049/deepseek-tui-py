"""Mini-Starlark parser for execpolicy rule files.

Rust uses the ``starlark`` crate to evaluate policy files that look
like this::

    prefix_rule(pattern=["git", "status"], decision="allow")
    prefix_rule(
        pattern=["git", ["log", "diff"]],
        decision="allow",
        justification="read-only git inspection",
        match=["git log", "git diff HEAD"],
        not_match=["git push"],
    )

Rust's Starlark is a full Python-like DSL with ``def`` / ``if`` / ``for``
/ ``import`` / f-strings. We don't need that surface — only ``prefix_rule``
calls with literal-list / literal-string arguments.

This module implements a ~200 LOC subset sufficient to parse the
default policy ships with the Rust repo. Grammar:

    module     := statement*
    statement  := COMMENT | call | blank
    call       := IDENT '(' args ')' NEWLINE
    args       := (arg (',' arg)*)?
    arg        := IDENT '=' expr | expr
    expr       := STRING | LIST
    LIST       := '[' (expr (',' expr)*)? ']'

The goal is byte-for-byte equivalence with Rust's ``prefix_rule``
behaviour — not general Starlark compatibility. Unsupported syntax
(``def`` / ``if`` / f-strings / ``import``) surfaces via a clear
:class:`ExecPolicyError` so users notice when the Rust file uses
features beyond our subset.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from .decision import Decision
from .errors import ExecPolicyError
from .policy import Policy
from .rule import (
    PatternToken,
    PrefixPattern,
    PrefixRule,
    RuleRef,
    validate_match_examples,
    validate_not_match_examples,
)

__all__ = ["PolicyParser"]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class PolicyParser:
    """Parse one or more policy files into a :class:`Policy`.

    Mirrors Rust ``PolicyParser`` (parser.rs:28-69). Call :meth:`parse`
    for each file, then :meth:`build` to realise the :class:`Policy`.
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

    Positional args are not supported — Rust's Starlark signature
    accepts `pattern` as the sole required arg, but the real policy
    files always use keyword form. Enforcing kwargs keeps the parser
    simple and the error messages precise.
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

    Mirrors the Rust ``prefix_rule`` builtin (parser.rs:209-268). The
    first pattern token may be either a single string or a list of
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
    """Shlex-split a string example; mirror Rust's `parse_string_example`."""
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
