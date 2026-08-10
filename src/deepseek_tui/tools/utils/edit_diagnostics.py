"""Actionable diagnostics when ``edit_file`` cannot match ``old_string``.

Mirrors the stale-write message style: one primary cause, one next action.
Does not auto-repair or write — diagnosis only.
"""

from __future__ import annotations

import re
from pathlib import Path

# read_file emits ``{line_no}\\t{line}``. Models often paste that prefix into
# old_string. Also accept a few common "line number" shapes from other tools.
_LINE_PREFIX_RE = re.compile(r"(?m)^\s*\d+\t")
_LINE_PREFIX_LOOSE_RE = re.compile(r"(?m)^\s*\d+[:|]\s?")

# Narrow typography set — only high-confidence accidental substitutions.
_CONFUSABLE_MAP: dict[str, str] = {
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote
    "\u2014": "--",  # em dash
    "\u2013": "-",  # en dash
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",  # nbsp
}

_MAX_NEAREST_LINES = 3
_MAX_NEAREST_LINE_CHARS = 200
_MAX_KEYWORD_CHARS = 48


def strip_line_number_prefixes(text: str) -> str:
    """Remove leading ``N\\t`` / ``N:`` style prefixes from each line."""
    stripped = _LINE_PREFIX_RE.sub("", text)
    if stripped != text:
        return stripped
    return _LINE_PREFIX_LOOSE_RE.sub("", text)


def looks_like_line_numbered_read_output(text: str) -> bool:
    """True when most non-empty lines look like ``read_file`` output rows."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    hits = sum(1 for ln in lines if _LINE_PREFIX_RE.match(ln) or _LINE_PREFIX_LOOSE_RE.match(ln))
    return hits >= max(1, (len(lines) + 1) // 2)


def normalize_confusables(text: str) -> str:
    """Replace known typography confusables with ASCII equivalents."""
    if not text:
        return text
    return "".join(_CONFUSABLE_MAP.get(ch, ch) for ch in text)


def has_confusables(text: str) -> bool:
    return any(ch in _CONFUSABLE_MAP for ch in text)


def _clip_line(line: str) -> str:
    if len(line) <= _MAX_NEAREST_LINE_CHARS:
        return line
    return line[: _MAX_NEAREST_LINE_CHARS - 3] + "..."


def find_nearest_lines(content: str, old_string: str) -> list[str]:
    """Return up to a few file lines that look related to ``old_string``."""
    needle = old_string.strip()
    if not needle:
        return []
    # Prefer a stable identifier token from the first non-empty line so a
    # mistyped suffix (``unique_token XX``) still finds ``unique_token``.
    first = next((ln.strip() for ln in needle.splitlines() if ln.strip()), needle)
    tokens = re.findall(r"[A-Za-z0-9_]{3,}", first)
    keywords = tokens[:3] if tokens else [first[:_MAX_KEYWORD_CHARS]]
    keywords = [k for k in keywords if len(k) >= 2]
    if not keywords:
        return []

    matches: list[str] = []
    seen_lines: set[int] = set()
    for keyword in keywords:
        for idx, line in enumerate(content.splitlines(), start=1):
            if idx in seen_lines:
                continue
            if keyword in line or keyword.lower() in line.lower():
                matches.append(f"line {idx}: {_clip_line(line.rstrip())}")
                seen_lines.add(idx)
                if len(matches) >= _MAX_NEAREST_LINES:
                    return matches
    return matches


def build_edit_no_match_message(path: Path | str, old_string: str, content: str) -> str:
    """Build a model-facing error for an exact-match miss (non-stale)."""
    path_s = str(path)
    base = f"Search string not found in {path_s}."

    # 1) Line-number prefix pasted from read_file output.
    if looks_like_line_numbered_read_output(old_string):
        stripped = strip_line_number_prefixes(old_string)
        if stripped and stripped in content:
            return (
                f"{base} old_string looks like read_file output "
                f"(lines are `N\\tcontent`). Strip the leading line numbers "
                f"and tabs, then retry with only the file content. "
                f"Example: use the text after the tab, not `12\\tcode`."
            )
        return (
            f"{base} old_string looks like it includes read_file line-number "
            f"prefixes (`N\\t…`). read_file returns `LINE\\tCONTENT` — copy only "
            f"CONTENT into old_string (never the leading number or tab), then retry."
        )

    # 2) Newline normalization (\r\n vs \n).
    norm_old = old_string.replace("\r\n", "\n").replace("\r", "\n")
    norm_content = content.replace("\r\n", "\n").replace("\r", "\n")
    if norm_old != old_string and norm_old in norm_content:
        return (
            f"{base} A newline-normalized copy of old_string does match — "
            f"line endings likely differ (CRLF vs LF). Re-read the span with "
            f"read_file and copy old_string exactly from that output."
        )

    # 3) Typography confusables (smart quotes, dashes, nbsp).
    if has_confusables(content) or has_confusables(old_string):
        norm_c = normalize_confusables(norm_content)
        norm_o = normalize_confusables(norm_old)
        if norm_o and norm_o in norm_c:
            affected = [
                str(idx)
                for idx, line in enumerate(content.splitlines(), start=1)
                if has_confusables(line)
                and normalize_confusables(line) in norm_c
                and any(
                    normalize_confusables(part) in normalize_confusables(line)
                    for part in norm_old.splitlines()
                    if part.strip()
                )
            ][:8]
            where = (
                f" on line(s) {', '.join(affected)}" if affected else ""
            )
            return (
                f"{base} After normalizing typography (smart quotes / dashes / "
                f"non-breaking spaces), old_string matches the file{where}. "
                f"Re-read that region with read_file and copy old_string from the "
                f"file bytes — do not retype quotes or dashes from memory."
            )

    # 4) Nearest lines + generic re-read instruction.
    nearest = find_nearest_lines(content, old_string)
    parts = [base]
    if nearest:
        parts.append("Nearest match:")
        parts.extend(nearest)
    parts.append(
        "Run read_file on this path, then retry edit_file with old_string "
        "copied exactly from that output (indentation and characters)."
    )
    return "\n".join(parts)
