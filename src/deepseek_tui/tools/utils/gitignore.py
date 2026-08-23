"""Best-effort .gitignore matching for search tools.

Fail-open: an unreadable or unparseable rule is skipped so a broken
gitignore cannot disable grep/file_search. Only walks up from the search
root when a ``.git`` directory is found (avoids picking up ``/tmp/.gitignore``
in tests and scratch dirs). Nested ``.gitignore`` files found during the
walk are added as they are encountered.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class _Rule:
    pattern: str
    negated: bool
    dir_only: bool
    anchored: bool
    base: Path
    regex: re.Pattern[str]


class GitIgnoreMatcher:
    """Match paths against gitignore rules collected for a walk root."""

    def __init__(self, walk_root: Path) -> None:
        self.walk_root = walk_root.resolve()
        self._rules: list[_Rule] = []
        self._loaded_files: set[Path] = set()
        for base in _gitignore_bases(self.walk_root):
            self.add_dir(base)

    def add_dir(self, directory: Path) -> None:
        """Load ``directory/.gitignore`` if present and not already loaded."""
        path = directory / ".gitignore"
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in self._loaded_files or not path.is_file():
            return
        self._loaded_files.add(resolved)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        for raw in text.splitlines():
            rule = _parse_rule(raw, directory.resolve())
            if rule is not None:
                self._rules.append(rule)

    def ignored(self, path: Path, *, is_dir: bool) -> bool:
        """True when *path* is ignored by the accumulated rules."""
        ignored = False
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for rule in self._rules:
            try:
                rel = resolved.relative_to(rule.base).as_posix()
            except ValueError:
                continue
            if _rule_matches(rule, rel, is_dir=is_dir):
                ignored = not rule.negated
        return ignored


def _gitignore_bases(walk_root: Path) -> list[Path]:
    """Directories whose ``.gitignore`` applies at the start of a walk.

    Always includes ``walk_root``. If ``walk_root`` sits inside a git repo,
    also includes every ancestor up to (and including) the repo root.
    """
    if (walk_root / ".git").exists():
        return [walk_root]
    current = walk_root
    for _ in range(16):
        parent = current.parent
        if parent == current:
            break
        if (parent / ".git").exists():
            chain: list[Path] = []
            cursor = walk_root
            while True:
                chain.append(cursor)
                if cursor == parent:
                    break
                nxt = cursor.parent
                if nxt == cursor:
                    break
                cursor = nxt
            chain.reverse()
            return chain
        current = parent
    return [walk_root]


def _parse_rule(raw: str, base: Path) -> _Rule | None:
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    negated = line.startswith("!")
    if negated:
        line = line[1:]
    if not line:
        return None
    dir_only = line.endswith("/")
    if dir_only:
        line = line.rstrip("/")
    if not line:
        return None
    anchored = line.startswith("/")
    if anchored:
        line = line.lstrip("/")
    if not line:
        return None
    return _Rule(
        pattern=line,
        negated=negated,
        dir_only=dir_only,
        anchored=anchored,
        base=base,
        regex=_glob_to_regex(line),
    )


@functools.lru_cache(maxsize=128)
def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate one gitignore pattern, keeping ``*`` inside a path component.

    ``fnmatch`` is the obvious matcher here and the wrong one: its ``*`` also
    matches ``/``, so ``src/*.tmp`` excluded ``src/deep/nested.tmp``, which
    ``git check-ignore`` keeps. Only ``**`` may span directories.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i + 1 : i + 2] == "*":
                i += 2
                if pattern[i : i + 1] == "/":
                    # `a/**/b` matches `a/b` too, so the separator is optional.
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
                i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            # A `]` immediately after `[` or `[!` is a literal, so start the
            # search past it.
            close = pattern.find("]", i + 2)
            if close < 0:
                out.append(re.escape(ch))
                i += 1
            else:
                body = pattern[i + 1 : close]
                if body[0] in "!^":
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = close + 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out))


def matches_path_glob(rel: str, pattern: str) -> bool:
    """True when *rel* matches *pattern*, with ``*`` staying in one component."""
    return _glob_to_regex(pattern).fullmatch(rel) is not None


def _rule_matches(rule: _Rule, rel: str, *, is_dir: bool) -> bool:
    parts = rel.split("/")
    if rule.anchored or "/" in rule.pattern:
        # A pattern containing a slash is relative to the directory holding the
        # .gitignore. Ancestors are candidates too: git ignores what is inside
        # an ignored directory, and the walk does not always prune it first.
        targets = ["/".join(parts[:depth]) for depth in range(1, len(parts) + 1)]
    else:
        # A bare name applies at any depth, so every component is a candidate.
        targets = parts
    last = len(targets) - 1
    for index, target in enumerate(targets):
        # An ancestor is a directory by definition; the path itself may not be,
        # and a `build/` rule only matches directories.
        if rule.dir_only and index == last and not is_dir:
            continue
        if rule.regex.fullmatch(target):
            return True
    return False
