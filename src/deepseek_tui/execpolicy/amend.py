"""Advisory file-locked append for policy amendments.

Mirrors ``crates/tui/src/execpolicy/amend.rs`` (225 LOC).

The invariant (and the Rust test fixtures): appending a new
``prefix_rule(...)`` line must

1. create the parent directory if it doesn't exist;
2. take an advisory lock on the policy file (``fcntl.flock`` on Unix);
3. ensure the existing content ends in ``\\n`` before appending;
4. release the lock via the standard context manager on exit.

macOS / Linux only (the current project scope). Windows support is
deferred — the audit noted the sandbox module is the real Windows
blocker, so we don't spend effort here on a Win-specific ``msvcrt``
lock path.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import AmendError

__all__ = ["blocking_append_allow_prefix_rule"]


def blocking_append_allow_prefix_rule(
    policy_path: Path, prefix: list[str]
) -> None:
    """Append a ``prefix_rule(pattern=..., decision="allow")`` to the file.

    Mirrors Rust ``blocking_append_allow_prefix_rule`` (amend.rs:59-91).
    The Rust version blocks on advisory locking and is meant to be
    wrapped in ``tokio::task::spawn_blocking``; the Python caller should
    similarly wrap this in ``asyncio.to_thread`` when called from async
    code.
    """
    if not prefix:
        raise AmendError.empty_prefix()

    tokens_json = [json.dumps(token) for token in prefix]
    pattern_literal = "[" + ", ".join(tokens_json) + "]"
    line = f'prefix_rule(pattern={pattern_literal}, decision="allow")'

    parent = policy_path.parent
    if str(parent) == "":
        raise AmendError.missing_parent(policy_path)
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise AmendError.create_policy_dir(parent, err) from err

    _append_locked_line(policy_path, line)


def _append_locked_line(policy_path: Path, line: str) -> None:
    """Open ``policy_path`` for append, lock, and append ``line``.

    Mirrors Rust ``append_locked_line`` (amend.rs:93-146).
    """
    import fcntl

    try:
        handle = open(  # noqa: SIM115 — lifetime is bounded by try/finally
            policy_path, "a+", encoding="utf-8"
        )
    except OSError as err:
        raise AmendError.open_policy_file(policy_path, err) from err

    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as err:
            raise AmendError.lock_policy_file(policy_path, err) from err

        # Ensure the file ends with a newline before we append. Seek to
        # the final byte (if any) and check.
        try:
            handle.seek(0, 2)  # SEEK_END
            size = handle.tell()
        except OSError as err:
            raise AmendError.read_policy_file(policy_path, err) from err

        needs_newline = False
        if size > 0:
            try:
                handle.seek(size - 1)
                last = handle.read(1)
            except OSError as err:
                raise AmendError.read_policy_file(policy_path, err) from err
            if last != "\n":
                needs_newline = True

        try:
            if needs_newline:
                handle.write("\n")
            handle.write(line + "\n")
            handle.flush()
        except OSError as err:
            raise AmendError.write_policy_file(policy_path, err) from err
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
