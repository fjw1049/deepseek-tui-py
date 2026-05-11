"""Execpolicy rules loaded from TOML configuration.

Mirrors ``crates/tui/src/execpolicy/rules.rs`` (123 LOC). This is the
lightweight TOML-based rules layer — the parallel system to the
Starlark-based :mod:`deepseek_tui.execpolicy.parser` / :mod:`policy`.

Wire format::

    [rules.git]
    allow = ["git status", "git log *"]
    deny = ["git push --force"]

    [rules.danger]
    deny = ["rm -rf /", "rm -rf /*"]

Evaluation semantics (mirrors Rust ``ExecPolicyConfig::evaluate`` at
rules.rs:43-64):

1. Scan every ``deny`` pattern in every group in insertion order.
   First match → ``Deny(reason)``.
2. Scan every ``allow`` pattern. First match → ``Allow``.
3. No match → ``AskUser("execpolicy: no matching allow rule")``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from .matcher import pattern_matches

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
    ``Deny`` / ``AskUser`` carry a reason string, mirroring Rust's
    data-variant pattern.
    """

    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


@dataclass(frozen=True, slots=True)
class ExecPolicyDecision:
    """Mirrors Rust ``ExecPolicyDecision`` enum (rules.rs:11-16).

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
    scan order in :meth:`evaluate` is deterministic. Rust used
    ``BTreeMap`` (sorted) — we use ``dict`` (insertion-order) because
    that's more useful for Python users authoring custom policies
    (they can reason about match precedence by source order).
    """

    rules: dict[str, RuleSet] = field(default_factory=dict)

    # --- Parsing ----------------------------------------------------

    @classmethod
    def from_str(cls, contents: str) -> ExecPolicyConfig:
        """Parse a TOML string into an :class:`ExecPolicyConfig`.

        Mirrors Rust ``ExecPolicyConfig::from_str`` (rules.rs:33-35).
        """
        try:
            data = _toml_reader.loads(contents)
        except _toml_reader.TOMLDecodeError as err:
            raise ValueError(f"failed to parse execpolicy.toml: {err}") from err
        return cls._from_dict(data)

    @classmethod
    def from_path(cls, path: Path) -> ExecPolicyConfig:
        """Parse a TOML file path.

        Mirrors Rust ``ExecPolicyConfig::from_path`` (rules.rs:37-41).
        """
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

        Mirrors Rust ``ExecPolicyConfig::evaluate`` (rules.rs:43-64).
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
    """Return ``./.deepseek/execpolicy.toml`` or ``None`` if unavailable.

    Mirrors Rust ``default_execpolicy_path`` (rules.rs:67-69). Project-local
    since 2026-05-11 so policy files travel with the repo.
    """
    from deepseek_tui.config.paths import dot_deepseek_dir

    try:
        return dot_deepseek_dir() / "execpolicy.toml"
    except (RuntimeError, OSError):  # pragma: no cover — platform quirks
        return None


def load_default_policy() -> ExecPolicyConfig | None:
    """Load the default policy if it exists; return ``None`` otherwise.

    Mirrors Rust ``load_default_policy`` (rules.rs:71-79).
    """
    path = default_execpolicy_path()
    if path is None or not path.exists():
        return None
    return ExecPolicyConfig.from_path(path)
