"""Command matching helpers for execpolicy rules.

Mirrors ``crates/tui/src/execpolicy/matcher.rs`` (198 LOC).

Three public functions:

* :func:`normalize_command` — shlex-parse + re-join, with heredoc
  bodies stripped first (issue #419) so ``cat <<EOF > file\\nbody\\nEOF``
  collapses to ``cat > file`` before pattern matching.
* :func:`pattern_matches` — ``*`` wildcards → regex. Both ``pattern``
  and ``command`` run through :func:`normalize_command` first.
* :func:`strip_heredoc_bodies` — exposed for unit tests / callers that
  want the intermediate form.

Differences vs. Rust:

* Rust's ``regex`` crate has no lookbehind, so Rust preprocesses
  ``<<<`` (here-string) to a placeholder before running the heredoc
  regex. Python's ``re`` supports lookbehind (``(?<!<)``), so in
  theory we could skip the placeholder dance — but we preserve it
  byte-identically so test fixtures captured from the Rust version
  round-trip cleanly.
"""

from __future__ import annotations

import re
import shlex

__all__ = ["normalize_command", "pattern_matches", "strip_heredoc_bodies"]


_HERESTRING_PLACEHOLDER = "\x01HERESTRING\x01"

# Mirror Rust's regex:  <<-?\s*(?:['"]?)([A-Za-z_][A-Za-z0-9_]*)(?:['"]?)
# Allows optional `-` after `<<`, optional surrounding quotes on the
# delimiter, delimiter is a typical shell identifier.
_HEREDOC_RE = re.compile(r"""<<-?\s*(?:['"]?)([A-Za-z_][A-Za-z0-9_]*)(?:['"]?)""")


def normalize_command(command: str) -> str:
    """Normalize a command string by shlex-parsing and re-joining tokens.

    Heredoc bodies are stripped first (issue #419). Mirrors Rust
    ``normalize_command`` (matcher.rs:12-23).
    """
    stripped = strip_heredoc_bodies(command)
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        # shlex raises on unbalanced quotes; Rust's shlex returns None
        # in the same case. Fall back to whitespace split.
        tokens = [t for t in stripped.split() if t]
    if not tokens:
        # Keep whitespace-split fallback even when shlex succeeded but
        # returned empty, matching Rust.
        tokens = [t for t in stripped.split() if t]
    return " ".join(tokens)


def strip_heredoc_bodies(command: str) -> str:
    """Strip heredoc bodies from a multi-line command string.

    Recognises ``<<DELIM`` / ``<<-DELIM`` / ``<<'DELIM'`` / ``<<"DELIM"``
    and consumes the body up to the matching delimiter line. The
    here-string operator ``<<<`` is intentionally left alone — its
    body is the next token on the same line.

    Mirrors Rust ``strip_heredoc_bodies`` (matcher.rs:38-100).
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
    # Rust appends a trailing `\n` per line; we match that shape so the
    # downstream shlex sees the same bytes.
    if not joined.endswith("\n"):
        joined += "\n"
    # Restore the here-string operator.
    return joined.replace(_HERESTRING_PLACEHOLDER, "<<<")


def pattern_matches(pattern: str, command: str) -> bool:
    """Return True if ``pattern`` matches ``command`` after normalization.

    Patterns support ``*`` wildcards that match any substring.
    Mirrors Rust ``pattern_matches`` (matcher.rs:105-118).
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
