"""Block shell commands that mutate source files outside an allowlist."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

# Paths relative to workspace (posix) or absolute /tmp that shell may write.
_ALLOWLIST_PREFIXES = (
    "scratch/",
    "tmp/",
    ".deepseek/tmp/",
    "node_modules/",
    "dist/",
    "build/",
    "target/",
    "coverage/",
    ".pytest_cache/",
    "__pycache__/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".turbo/",
    ".next/",
)

_ALLOWLIST_SUFFIXES = (".log", ".pyc", ".pyo")

_SOURCE_SUFFIXES = (
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".scala",
    ".vue",
    ".svelte",
    ".css",
    ".scss",
    ".less",
    ".html",
    ".htm",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".mdx",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".txt",
)

# sed -i / perl -pi / ruby -i (suffixes: -i.bak, -i'', -i""). Tool name
# case-insensitive; flag `i` stays lower-case so ruby -Ilib is not matched.
_INPLACE_EDIT = re.compile(
    r"(?i:(?:^|[;&|`]|\s)(?:sed|perl|ruby))(?:\s+[^\s;&|]+)*\s+"
    r"-(?:[a-z]*i[a-z]*|i)(?:\.[^\s'\"]*|''|\"\")?(?:\s|=|$)",
)
# Redirect anywhere in the command: `cmd args > file`, `1>`, `>>`
_REDIRECT_WRITE = re.compile(
    r"(?:^|[\s;&|])(?:\d*)(>>?)\s*([^\s;&|]+)",
)
_TEE = re.compile(
    r"(?:^|[;&|`]|\s)tee(?:\s+-a)?\s+([^\s;&|]+)",
    re.IGNORECASE,
)
_HEREDOC = re.compile(
    r"(?:cat|tee)\s*(?:>>?)\s*([^\s;&|]+)\s*<<",
    re.IGNORECASE,
)
_HEREDOC_REV = re.compile(
    r"(?:cat|tee)\s*<<[^\n]*\s*(?:>>?)\s*([^\s;&|]+)",
    re.IGNORECASE,
)
# Interpreter write APIs only — plain open(...).read() must stay allowed.
_PYTHON_WRITE = re.compile(
    r"(?:python3?|node)\b[^\n]*(?:"
    r"open\s*\([^;\n]*['\"][wa]|"
    r"write_text\s*\(|write_bytes\s*\(|"
    r"writeFileSync\s*\(|"
    r"\.write\s*\("
    r")",
    re.IGNORECASE,
)
_CP_MV_RM = re.compile(
    r"(?:^|[;&|`]|\s)(cp|mv|rm|unlink)\b",
    re.IGNORECASE,
)
_NESTED_SHELL = re.compile(
    r"(?:^|[;&|`]|\s)(?:ba)?sh\s+-c\s+([\"'])(.*?)\1",
    re.IGNORECASE | re.DOTALL,
)
_NESTED_SHELL_UNQUOTED = re.compile(
    r"(?:^|[;&|`]|\s)(?:ba)?sh\s+-c\s+(\S+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ShellWriteVerdict:
    allowed: bool
    reason: str = ""
    blocked_path: str | None = None


def is_allowlisted_path(path: str, *, workspace: Path | None = None) -> bool:
    raw = path.strip().strip("'\"")
    if not raw:
        return False
    if raw.startswith("/tmp/") or raw == "/tmp" or raw.startswith("/var/tmp/"):
        return True
    rel = raw
    if workspace is not None:
        try:
            abs_path = Path(raw).expanduser()
            if abs_path.is_absolute():
                rel = str(abs_path.resolve().relative_to(workspace.resolve()))
        except (OSError, ValueError):
            rel = raw
    rel = rel.replace("\\", "/").lstrip("./")
    lower = rel.lower()
    if any(lower.startswith(p) for p in _ALLOWLIST_PREFIXES):
        return True
    if any(lower.endswith(s) for s in _ALLOWLIST_SUFFIXES):
        return True
    return False


def looks_like_source_path(path: str, *, workspace: Path | None = None) -> bool:
    raw = path.strip().strip("'\"")
    if not raw or raw in ("-", "/dev/null", "/dev/stdin", "/dev/stdout"):
        return False
    if is_allowlisted_path(raw, workspace=workspace):
        return False
    lower = raw.replace("\\", "/").lower()
    if any(lower.endswith(s) for s in _SOURCE_SUFFIXES):
        return True
    if not lower.startswith("/") and "/" in lower and "$" not in lower:
        return True
    if not lower.startswith("/") and lower in {
        "makefile",
        "dockerfile",
        "gemfile",
        "rakefile",
        "procfile",
    }:
        return True
    return False


def _extract_redirect_targets(command: str) -> list[str]:
    targets: list[str] = []
    for match in _REDIRECT_WRITE.finditer(command):
        targets.append(match.group(2))
    for match in _TEE.finditer(command):
        targets.append(match.group(1))
    for match in _HEREDOC.finditer(command):
        targets.append(match.group(1))
    for match in _HEREDOC_REV.finditer(command):
        targets.append(match.group(1))
    return targets


def _quoted_path_tokens(command: str) -> list[str]:
    return re.findall(r"[\"']([^\"']+)[\"']", command)


def _deny(path: str | None, reason: str) -> ShellWriteVerdict:
    return ShellWriteVerdict(
        allowed=False,
        reason=reason,
        blocked_path=path.strip("'\"") if path else None,
    )


def check_shell_write(
    command: str,
    *,
    workspace: Path | None = None,
    _depth: int = 0,
) -> ShellWriteVerdict:
    """Return deny verdict when command would mutate non-allowlisted source files."""
    cmd = command.strip()
    if not cmd:
        return ShellWriteVerdict(allowed=True)
    if _depth > 3:
        return ShellWriteVerdict(allowed=True)

    # Recurse into nested `sh -c '…'` / `bash -c "…"`.
    for match in _NESTED_SHELL.finditer(cmd):
        nested = match.group(2)
        verdict = check_shell_write(nested, workspace=workspace, _depth=_depth + 1)
        if not verdict.allowed:
            return verdict
    for match in _NESTED_SHELL_UNQUOTED.finditer(cmd):
        # Avoid re-matching the quoted form.
        if match.group(1)[:1] in {"'", '"'}:
            continue
        verdict = check_shell_write(
            match.group(1), workspace=workspace, _depth=_depth + 1
        )
        if not verdict.allowed:
            return verdict

    if _INPLACE_EDIT.search(cmd):
        for token in re.findall(r"[^\s;&|]+", cmd):
            if token.startswith("-"):
                continue
            if looks_like_source_path(token, workspace=workspace):
                return _deny(
                    token,
                    f"Shell cannot mutate source files in-place ({token}). "
                    "Use edit_file / apply_patch / write_file.",
                )
        return _deny(
            None,
            "Shell cannot mutate source files in-place (sed/perl/ruby -i). "
            "Use edit_file / apply_patch / write_file.",
        )

    for target in _extract_redirect_targets(cmd):
        if looks_like_source_path(target, workspace=workspace):
            return _deny(
                target,
                f"Shell cannot write source file {target!r}. "
                "Use edit_file / apply_patch / write_file.",
            )

    if _PYTHON_WRITE.search(cmd):
        candidates = _quoted_path_tokens(cmd)
        candidates.extend(re.findall(r"[^\s;&|()\"']+", cmd))
        for token in candidates:
            if not token or token.startswith("-"):
                continue
            if looks_like_source_path(token, workspace=workspace):
                return _deny(
                    token,
                    f"Shell cannot mutate source files via interpreter write "
                    f"({token}). Use edit_file / apply_patch / write_file.",
                )
        # Matched write API but no path extracted — still deny (fail closed).
        return _deny(
            None,
            "Shell cannot mutate source files via interpreter write. "
            "Use edit_file / apply_patch / write_file.",
        )

    cp_mv = _CP_MV_RM.search(cmd)
    if cp_mv:
        tool = cp_mv.group(1).lower()
        try:
            tokens = shlex.split(cmd, posix=True)
        except ValueError:
            tokens = re.findall(r"[^\s;&|]+", cmd)
        # Drop the tool name and flags; remaining are operands.
        operands: list[str] = []
        seen_tool = False
        for tok in tokens:
            low = tok.lower()
            if not seen_tool and low in {"cp", "mv", "rm", "unlink"}:
                seen_tool = True
                continue
            if tok.startswith("-"):
                continue
            operands.append(tok)
        if tool in {"rm", "unlink"}:
            for op in operands:
                if looks_like_source_path(op, workspace=workspace):
                    return _deny(
                        op,
                        f"Shell cannot rm source path {op!r}. "
                        "Use edit_file / apply_patch / write_file (or git).",
                    )
        elif tool in {"cp", "mv"} and operands:
            # Only the destination matters for "writing source".
            dest = operands[-1]
            if looks_like_source_path(dest, workspace=workspace):
                return _deny(
                    dest,
                    f"Shell cannot {tool} onto source path {dest!r}. "
                    "Use edit_file / apply_patch / write_file.",
                )

    return ShellWriteVerdict(allowed=True)
