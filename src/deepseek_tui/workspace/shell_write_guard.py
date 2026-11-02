"""What a shell command would take from the user, and what it may do to managed worktrees."""

from __future__ import annotations

import glob
import os
import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import islice
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

FileId = tuple[int, int]  # st_dev, st_ino

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
    root = (workspace or Path.cwd()).expanduser().resolve()
    candidate = Path(raw).expanduser()
    target = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        # External temporary output is allowed, but a project located in /tmp
        # still gets the same source-file policy as any other project.
        if any(target.is_relative_to(Path(base).resolve()) for base in ("/tmp", "/var/tmp")):
            return True
        return False
    lower = rel.lower()
    # Trailing "/" so the allowlisted directory itself (`./scratch`) matches too.
    if any(f"{lower}/".startswith(p) for p in _ALLOWLIST_PREFIXES):
        return True
    if any(lower.endswith(s) for s in _ALLOWLIST_SUFFIXES):
        return True
    return False


_FILE_TOOLS = {"cp", "mv", "rm", "unlink"}
_CURRENT_DIRECTORY = {".", "$PWD", "${PWD}", "$(pwd)"}
# Wrappers that run the command after them, so `sudo rm x` still removes x.
_FILE_TOOL_PREFIXES = {"command", "env", "sudo", "xargs", "nohup", "time"}
_ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
_REDIRECT_OPERATOR = re.compile(r"\d*(?:>>?|<|&>)")


def _file_command_invocations(command: str) -> list[tuple[str, list[str], str | None]]:
    """Each cp/mv/rm/unlink call with its operands and directory, segment by segment.

    Operands stop at the next separator, so `rm -f a.db && python3 add.py`
    does not make `add.py` an rm target, and redirections are not operands.
    `cd inbox && rm a.txt` removes inbox/a.txt, so a leading cd moves the base;
    a directory only the shell can expand is None.
    """
    segments: list[list[str]] = [[]]
    for token in _shell_tokens(command):
        if token in _SHELL_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    invocations: list[tuple[str, list[str], str | None]] = []
    directory: str | None = "."
    for segment in segments:
        if len(segment) == 2 and segment[0] == "cd":
            if segment[1] in _CURRENT_DIRECTORY:
                continue
            target = None if "$" in segment[1] or segment[1] == "-" else segment[1]
            directory = target and directory and str(Path(directory, target))
            continue
        index = 0
        while index < len(segment):
            token = segment[index]
            if token.lower() in _FILE_TOOL_PREFIXES or _ENV_ASSIGNMENT.fullmatch(token):
                index += 1
            elif index and token.startswith("-"):
                index += 1  # option of a prefix, e.g. `xargs -0`
            else:
                break
        if index >= len(segment):
            continue
        tool = Path(segment[index]).name.lower()
        if tool not in _FILE_TOOLS:
            continue
        operands: list[str] = []
        options_done = False
        skip_next = False
        for token in segment[index + 1 :]:
            if skip_next:
                skip_next = False
                continue
            if _REDIRECT_OPERATOR.match(token):
                # A bare operator (`>`, `2>`) takes the next token as its target.
                skip_next = bool(_REDIRECT_OPERATOR.fullmatch(token))
                continue
            if token == "--" and not options_done:
                options_done = True
                continue
            if token.startswith("-") and not options_done:
                continue
            operands.append(token)
        invocations.append((tool, operands, directory))
    return invocations


def _deny(path: str | None, reason: str) -> ShellWriteVerdict:
    return ShellWriteVerdict(
        allowed=False,
        reason=reason,
        blocked_path=path.strip("'\"") if path else None,
    )


# Git inside a managed worktree is inspection-only. Unknown subcommands are
# denied so aliases and newly-added mutators cannot bypass the sandbox.
_GIT_READONLY_SUBCOMMANDS = {
    "blame",
    "cat-file",
    "check-attr",
    "check-ignore",
    "check-mailmap",
    "check-ref-format",
    "count-objects",
    "describe",
    "status",
    "diff",
    "diff-files",
    "diff-index",
    "diff-tree",
    "for-each-ref",
    "fsck",
    "grep",
    "help",
    "ls-files",
    "ls-tree",
    "log",
    "merge-base",
    "name-rev",
    "rev-list",
    "rev-parse",
    "shortlog",
    "show",
    "show-ref",
    "version",
}
_GIT_BRANCH_MUTATION_FLAGS = {
    "-c",
    "-C",
    "-d",
    "-D",
    "-f",
    "-m",
    "-M",
    "--copy",
    "--delete",
    "--edit-description",
    "--force",
    "--move",
    "--set-upstream-to",
    "--unset-upstream",
}
_GIT_BRANCH_READ_FLAGS = {
    "-l",
    "--list",
    "--show-current",
    "--contains",
    "--no-contains",
    "--merged",
    "--no-merged",
    "--points-at",
}
_GIT_CONFIG_MUTATION_FLAGS = {
    "--add",
    "--edit",
    "-e",
    "--remove-section",
    "--rename-section",
    "--replace-all",
    "--unset",
    "--unset-all",
}
_GIT_CONFIG_READ_FLAGS = {
    "--get",
    "--get-all",
    "--get-color",
    "--get-colorbool",
    "--get-regexp",
    "--get-urlmatch",
    "--list",
    "-l",
}
_GIT_GLOBAL_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}
_SHELL_SEPARATORS = {";", "&", "&&", "|", "||", "(", ")"}
_COMMAND_PREFIXES = {"command", "env", "sudo"}


def _shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(
            command.replace("\n", ";"),
            posix=True,
            punctuation_chars=";&|()",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return re.findall(r"[^\s;&|()]+|&&|\|\||[;&|()]", command)


def _git_invocation(tokens: list[str], git_index: int) -> tuple[str | None, list[str]]:
    index = git_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token in _SHELL_SEPARATORS:
            return None, []
        option = token.split("=", 1)[0]
        if option in _GIT_GLOBAL_OPTIONS_WITH_VALUE:
            index += 1 if "=" in token else 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        end = index + 1
        while end < len(tokens) and tokens[end] not in _SHELL_SEPARATORS:
            end += 1
        return token.lower(), tokens[index + 1 : end]
    return None, []


def _git_branch_is_readonly(args: list[str]) -> bool:
    if any(arg.split("=", 1)[0] in _GIT_BRANCH_MUTATION_FLAGS for arg in args):
        return False
    positional = [arg for arg in args if not arg.startswith("-")]
    return not positional or any(
        arg.split("=", 1)[0] in _GIT_BRANCH_READ_FLAGS for arg in args
    )


def _git_config_is_readonly(args: list[str]) -> bool:
    flags = {arg.split("=", 1)[0] for arg in args if arg.startswith("-")}
    if flags.intersection(_GIT_CONFIG_MUTATION_FLAGS):
        return False
    if flags.intersection(_GIT_CONFIG_READ_FLAGS):
        return True
    positional = [arg for arg in args if not arg.startswith("-")]
    if positional and positional[0] in {
        "get",
        "get-all",
        "get-regexp",
        "get-urlmatch",
        "list",
    }:
        return True
    return len(positional) <= 1


def _git_remote_is_readonly(args: list[str]) -> bool:
    positional = [arg for arg in args if not arg.startswith("-")]
    return not positional or positional[0] in {"get-url", "show"}


def _git_symbolic_ref_is_readonly(args: list[str]) -> bool:
    if any(arg in {"-d", "--delete", "-m"} for arg in args):
        return False
    return len([arg for arg in args if not arg.startswith("-")]) <= 1


def _git_tag_is_readonly(args: list[str]) -> bool:
    mutation_flags = {
        "-a",
        "-d",
        "-f",
        "-m",
        "-s",
        "-u",
        "--annotate",
        "--delete",
        "--force",
        "--sign",
    }
    if any(arg.split("=", 1)[0] in mutation_flags for arg in args):
        return False
    positional = [arg for arg in args if not arg.startswith("-")]
    listing = any(
        arg.split("=", 1)[0]
        in {"-l", "--list", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"}
        for arg in args
    )
    return not positional or listing


def _git_command_is_readonly(subcommand: str, args: list[str]) -> bool:
    if subcommand in _GIT_READONLY_SUBCOMMANDS:
        return True
    if subcommand == "branch":
        return _git_branch_is_readonly(args)
    if subcommand == "config":
        return _git_config_is_readonly(args)
    if subcommand == "remote":
        return _git_remote_is_readonly(args)
    if subcommand == "symbolic-ref":
        return _git_symbolic_ref_is_readonly(args)
    if subcommand == "tag":
        return _git_tag_is_readonly(args)
    return False


def check_managed_worktree_git(command: str, *, _depth: int = 0) -> ShellWriteVerdict:
    """Allow only read-only Git commands in a managed task workspace."""
    if _depth > 3:
        return ShellWriteVerdict(allowed=True)
    for match in _NESTED_SHELL.finditer(command):
        verdict = check_managed_worktree_git(match.group(2), _depth=_depth + 1)
        if not verdict.allowed:
            return verdict
    for match in _NESTED_SHELL_UNQUOTED.finditer(command):
        if match.group(1)[:1] in {"'", '"'}:
            continue
        verdict = check_managed_worktree_git(match.group(1), _depth=_depth + 1)
        if not verdict.allowed:
            return verdict

    tokens = _shell_tokens(command)
    segment_start = 0
    for index, token in enumerate(tokens):
        if token in _SHELL_SEPARATORS:
            segment_start = index + 1
            continue
        if Path(token).name.lower() != "git":
            continue
        prefix = tokens[segment_start:index]
        if any(
            part not in _COMMAND_PREFIXES
            and not part.startswith("-")
            and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", part)
            for part in prefix
        ):
            continue
        subcommand, args = _git_invocation(tokens, index)
        if subcommand is not None and not _git_command_is_readonly(subcommand, args):
            return _deny(
                None,
                f"Git {subcommand} is disabled in this isolated task workspace. "
                "Edit and test files here; commit and sync from the project workspace.",
            )
    return ShellWriteVerdict(allowed=True)


_UNWATCHED_DIRS = {".git", ".deepseek", ".venv", "venv", "__pycache__", "node_modules",
                   "dist", "build", "target", ".next", ".turbo"}
_MAX_WATCHED_FILES = 20_000


def _operands(command: str, *, _depth: int = 0) -> list[tuple[str, list[str], str | None]]:
    invocations = _file_command_invocations(command)
    if _depth < 3:
        for pattern, group in ((_NESTED_SHELL, 2), (_NESTED_SHELL_UNQUOTED, 1)):
            for match in pattern.finditer(command):
                if match.group(group)[:1] not in {"'", '"'}:
                    invocations += _operands(match.group(group), _depth=_depth + 1)
    return invocations


def _targets(operand: str, base: Path | None) -> list[Path]:
    """Concrete paths for an operand; a shell variable cannot be resolved here."""
    raw = operand.strip("'\"")
    if base is None or not raw or "$" in raw or raw.startswith(("/dev/", "-")):
        return []
    pattern = Path(raw).expanduser()
    pattern = pattern if pattern.is_absolute() else base / pattern
    return [Path(hit) for hit in glob.glob(str(pattern))] if glob.has_magic(str(pattern)) else [pattern]


def _predates(path: Path, session_started_at: float) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    # Creation time where the platform has it: an edit must not make a file the agent's.
    return getattr(info, "st_birthtime", info.st_mtime) < session_started_at


def _walk_files(root: Path) -> Iterator[Path]:
    """Files under ``root``, bounded so a huge tree costs missed files, never a slow command."""
    def files() -> Iterator[Path]:
        for base, directories, names in os.walk(root):
            directories[:] = [d for d in directories if d not in _UNWATCHED_DIRS]
            for name in names:
                yield Path(base, name)

    return islice(files(), _MAX_WATCHED_FILES)


def _predating(path: Path, session_started_at: float) -> list[Path]:
    """What the session did not create at ``path``. A new folder can hold older files."""
    if _predates(path, session_started_at):
        return [path]
    if path.is_symlink() or not path.is_dir():
        return []
    return [file for file in _walk_files(path) if _predates(file, session_started_at)]


def existing_file_removals(
    command: str, *, workspace: Path, session_started_at: float,
) -> list[str]:
    """Files from before this session that the command would delete or move out of reach.

    Files the session created are the agent's to clean up, and regenerable output
    stays allowlisted. Moves inside the workspace remain possible: that is the way
    out when deletion is refused. ``python -c os.remove`` is not visible here.
    """
    root = workspace.expanduser().resolve()
    removed: list[str] = []
    for tool, operands, directory in _operands(command):
        base = None if directory is None else (root / directory).resolve()
        if tool in {"rm", "unlink"}:
            sources = operands
        elif tool == "mv" and len(operands) > 1:
            destination = _targets(operands[-1], base)
            if destination and destination[0].resolve().is_relative_to(root):
                continue
            sources = operands[:-1]
        else:
            continue
        for operand in sources:
            for target in _targets(operand, base):
                for path in _predating(target, session_started_at):
                    if (not is_allowlisted_path(str(path), workspace=root)
                            and str(path) not in removed):
                        removed.append(str(path))
    return removed


def _file_id(path: Path) -> FileId | None:
    try:
        info = path.lstat()
    except OSError:
        return None
    return info.st_dev, info.st_ino


def existing_files(workspace: Path, session_started_at: float) -> dict[str, FileId]:
    """Files that predate the session, to notice what any command removes.

    Parsing cannot see ``python -c os.remove``; comparing disk before and after can.
    """
    root = workspace.expanduser().resolve()
    found: dict[str, FileId] = {}
    for path in _walk_files(root):
        if _predates(path, session_started_at) and (identity := _file_id(path)):
            found[str(path)] = identity
    return found


def gone_files(
    watched: dict[str, FileId], workspace: Path, session_started_at: float,
) -> set[str]:
    """Paths whose file no longer exists; ``watched`` follows files that only moved.

    Files are tracked by identity because a path says nothing about a folder that
    was renamed, or about a file moved aside and deleted by a later command.
    """
    missing = {path: watched.pop(path) for path in list(watched) if not os.path.lexists(path)}
    if not missing:
        return set()
    wanted = set(missing.values())
    for path in _walk_files(workspace.expanduser().resolve()):
        identity = _file_id(path)
        # A new file can take a freed inode, so it must also be as old as the one it replaces.
        if identity in wanted and _predates(path, session_started_at):
            watched[str(path)] = identity
            wanted.discard(identity)
            if not wanted:
                break
    return {path for path, identity in missing.items() if identity in wanted}
