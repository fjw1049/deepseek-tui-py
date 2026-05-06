"""Errors raised by the Rust-parity execpolicy machinery.

Mirrors ``crates/tui/src/execpolicy/error.rs`` (28 LOC) plus the
``AmendError`` variants from ``amend.rs:12-55``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "AmendError",
    "ExecPolicyError",
]


class ExecPolicyError(Exception):
    """Base class for execpolicy parse / evaluate errors.

    Matches Rust ``execpolicy::Error`` (error.rs:7-28). Instances can
    carry structured context via :attr:`data` for callers that want to
    inspect the offending inputs.
    """

    data: dict[str, Any]

    def __init__(self, message: str, **data: Any) -> None:
        super().__init__(message)
        self.data = data

    # --- Constructors (one per Rust variant) ------------------------

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

    Mirrors Rust ``AmendError`` (amend.rs:12-55). Instances carry
    structured context via :attr:`data` (path / directory / source).
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
