"""Command execution policy — decision enum, matcher, and TOML rule engine.

The wire shape is camelCase ``"allow" | "prompt" | "forbidden"``. The
variant order ``Allow < Prompt < Forbidden`` is what aggregation relies on
when several matches combine (the most-restrictive decision wins).

Rules live in ``~/.deepseek/execpolicy.toml``::

    [rules.git]
    allow = ["git status", "git log *"]
    deny = ["git push --force"]

Evaluation semantics:

1. Scan every ``deny`` pattern in every group in insertion order.
   First match → ``Deny(reason)``.
2. Scan every ``allow`` pattern. First match → ``Allow``.
3. No match → ``AskUser("execpolicy: no matching allow rule")``.

(A historical Starlark ``prefix_rule(...)`` engine lived here too; it was
never wired into the tool layer and has been removed.)
"""

from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass, field
from enum import Enum
from functools import total_ordering
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Decision",
    "Evaluation",
    "ExecPolicyConfig",
    "ExecPolicyDecision",
    "ExecPolicyDecisionKind",
    "ExecPolicyError",
    "HeuristicsFallback",
    "RuleSet",
    "TomlBackedPolicy",
    "default_execpolicy_path",
    "load_default_policy",
    "load_user_policy",
    "normalize_command",
    "pattern_matches",
    "strip_heredoc_bodies",
]


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


class ExecPolicyError(Exception):
    """Base class for execpolicy parse / evaluate errors.

    Instances can carry structured context via :attr:`data` for callers
    that want to inspect the offending inputs.
    """

    data: dict[str, Any]

    def __init__(self, message: str, **data: Any) -> None:
        super().__init__(message)
        self.data = data


# Type alias for the heuristics-fallback callable used by
# :meth:`TomlBackedPolicy.check`.
HeuristicsFallback = Any


class Evaluation(BaseModel):
    """Aggregated evaluation result.

    The wire shape uses camelCase for ``matchedRules``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    decision: Decision
    matched_rules: list[Any] = Field(alias="matchedRules", default_factory=list)


# ---------------------------------------------------------------------------
# Command matching helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# TOML rule layer
# ---------------------------------------------------------------------------


if sys.version_info >= (3, 11):
    import tomllib as _toml_reader
else:  # pragma: no cover — py3.10 fallback
    import tomli as _toml_reader  # type: ignore[import-not-found]


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
