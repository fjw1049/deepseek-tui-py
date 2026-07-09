"""Command safety analysis for shell execution.

Detects potentially dangerous shell command patterns and assigns safety levels.
"""

from __future__ import annotations



import re
from dataclasses import dataclass, field
from enum import Enum

# Matches output redirection (``>`` / ``>>``), optionally with a leading fd
# digit, capturing the redirect target. ``2>&1`` style fd-duplication and
# redirects to ``/dev/null`` are filtered out in :func:`_has_file_redirection`.
_REDIRECT_RE = re.compile(r"[0-9]*>>?\s*(&?[^\s|;&]+)")


class SafetyLevel(Enum):
    """Safety classification for a command."""

    SAFE = "safe"
    WORKSPACE_SAFE = "workspace_safe"
    REQUIRES_APPROVAL = "requires_approval"
    DANGEROUS = "dangerous"


@dataclass
class SafetyAnalysis:
    """Result of analyzing a command for safety."""

    level: SafetyLevel
    command: str
    reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    @staticmethod
    def safe(command: str) -> SafetyAnalysis:
        """Command is known to be safe (read-only operations)."""
        return SafetyAnalysis(
            level=SafetyLevel.SAFE,
            command=command,
            reasons=["Command is read-only"],
        )

    @staticmethod
    def workspace_safe(command: str, reason: str) -> SafetyAnalysis:
        """Command is safe within the workspace but may modify files."""
        return SafetyAnalysis(
            level=SafetyLevel.WORKSPACE_SAFE,
            command=command,
            reasons=[reason],
        )

    @staticmethod
    def requires_approval(command: str, reasons: list[str]) -> SafetyAnalysis:
        """Command may have system-wide effects and requires approval."""
        return SafetyAnalysis(
            level=SafetyLevel.REQUIRES_APPROVAL,
            command=command,
            reasons=reasons,
        )

    @staticmethod
    def dangerous(
        command: str, reasons: list[str], suggestions: list[str] | None = None
    ) -> SafetyAnalysis:
        """Command is potentially dangerous and should be blocked."""
        return SafetyAnalysis(
            level=SafetyLevel.DANGEROUS,
            command=command,
            reasons=reasons,
            suggestions=suggestions or [],
        )


# Known safe commands that only read data.
#
# Interpreters / code runners (python, node, perl, ruby, sed, awk, ...) and
# command wrappers (env) are intentionally EXCLUDED: they can execute
# arbitrary code (e.g. ``python -c "import os; os.system('rm -rf ~')"``) and
# must not be auto-allowed. System-state controls (mount, systemctl, service)
# are excluded too — they are not read-only.
SAFE_COMMANDS = {
    "ls", "dir", "pwd", "cat", "head", "tail", "less", "more", "grep", "rg", "ag",
    "find", "fd", "which", "whereis", "type", "echo", "printf", "date", "cal",
    "uptime", "whoami", "id", "hostname", "uname", "printenv", "set", "ps",
    "top", "htop", "df", "du", "free", "vmstat", "wc", "sort", "uniq", "cut", "tr",
    "stat", "file", "tree", "lsof", "lsblk", "blkid",
}

# Commands that are safe within the workspace but may modify files.
#
# Interpreters (python, node, ruby) are EXCLUDED here as well — running a
# script executes arbitrary code and must go through approval rather than
# being treated as a benign workspace file modification.
WORKSPACE_SAFE_COMMANDS = {
    "cargo", "npm", "go", "rustc", "javac",
    "make", "cmake", "ninja", "gcc", "clang", "cc", "chmod", "chown", "mkdir",
    "touch", "rm", "cp", "mv", "ln", "tar", "zip", "unzip", "gzip", "bzip2",
}

# Dangerous command patterns that should be blocked or warned
DANGEROUS_PATTERNS = [
    ("rm -rf /", "Attempts to recursively delete root filesystem"),
    ("rm -rf /*", "Attempts to recursively delete all root directories"),
    ("rm -rf ~", "Attempts to recursively delete home directory"),
    ("rm -rf $HOME", "Attempts to recursively delete home directory"),
    (":(){ :|:& };:", "Fork bomb — will crash the system"),
]

# Commands that require elevated privileges
PRIVILEGED_PATTERNS = ["sudo", "su ", "doas", "pkexec", "gksudo", "kdesudo"]

# Network-related commands
NETWORK_COMMANDS = {
    "curl", "wget", "fetch", "nc", "netcat", "ncat", "ssh", "scp", "sftp",
    "rsync", "ftp", "ping", "traceroute", "nslookup", "dig", "host", "nmap",
    "masscan", "tcpdump", "wireshark",
}


def analyze_command(command: str) -> SafetyAnalysis:
    """Analyze a shell command for safety."""
    command_lower = command.lower()
    command_trimmed = command.strip()

    # Check for multi-line commands
    if "\n" in command or "\r" in command:
        return SafetyAnalysis.dangerous(
            command,
            ["Command contains multiple lines"],
            ["Run one command at a time"],
        )

    # Check for dangerous patterns FIRST (before chaining detection)
    for pattern, reason in DANGEROUS_PATTERNS:
        if pattern.lower() in command_lower:
            return SafetyAnalysis.dangerous(
                command,
                [reason],
                ["Review the command carefully before execution"],
            )

    # Check for command chaining
    if "&&" in command or "||" in command or ";" in command:
        if _all_segments_known_safe(command):
            return SafetyAnalysis.requires_approval(
                command,
                ["Command chains known-safe segments (cargo/git/etc.)"],
            )
        return SafetyAnalysis.requires_approval(
            command,
            ["Command chaining detected"],
        )

    # Check for command substitution
    if "`" in command or "$(" in command:
        return SafetyAnalysis.requires_approval(
            command,
            ["Command substitution detected"],
        )

    # Check for output redirection to a file — even an otherwise read-only
    # command (``echo evil > ~/.zshrc``) writes when it redirects.
    if _has_file_redirection(command):
        return SafetyAnalysis.requires_approval(
            command,
            ["Command redirects output to a file"],
        )

    # Check for privileged commands
    for pattern in PRIVILEGED_PATTERNS:
        if (command_trimmed.startswith(pattern) or
                f" {pattern} " in command_lower):
            return SafetyAnalysis.requires_approval(
                command,
                [f"Command uses privileged execution ({pattern.strip()})"],
            )

    # Check for pipe to shell (RCE risk)
    if ("curl" in command_lower or "wget" in command_lower):
        if ("| sh" in command_lower or "| bash" in command_lower or
                "| zsh" in command_lower):
            return SafetyAnalysis.dangerous(
                command,
                ["Piping remote content directly to shell is dangerous"],
                ["Download the script first and review it before execution"],
            )

    # Check if it's a known safe command (read-only)
    first_word = command_trimmed.split()[0] if command_trimmed.split() else ""
    if _is_safe_command(command_trimmed):
        return SafetyAnalysis.safe(command)

    # Check for rm with -r or -f flags (before workspace-safe check)
    if first_word == "rm":
        if "-r" in command_lower or "-f" in command_lower or "-rf" in command_lower:
            return SafetyAnalysis.requires_approval(
                command,
                ["rm with recursive or force flags requires approval"],
            )

    # Check for workspace-safe commands
    if _is_workspace_safe_command(command_trimmed):
        return SafetyAnalysis.workspace_safe(
            command, "Command modifies files within workspace"
        )

    # Check for network commands
    if first_word in NETWORK_COMMANDS:
        return SafetyAnalysis.requires_approval(
            command,
            ["Command may make network requests"],
        )

    # Default to RequiresApproval for unknown commands
    return SafetyAnalysis.requires_approval(
        command,
        ["Unknown command — requires approval"],
    )


def _is_safe_command(command: str) -> bool:
    """Check if command is known to be safe (read-only)."""
    parts = command.split()
    if not parts:
        return False

    first_word = parts[0]

    # Single-word safe commands
    if first_word in SAFE_COMMANDS:
        return True

    # Multi-word safe commands (git/npm truly read-only operations only)
    if len(parts) >= 2:
        prefix = f"{parts[0]} {parts[1]}".lower()
        # Only include operations that are truly read-only (no modifications)
        # cargo build/test/clippy modify artifacts, so excluded
        read_only_prefixes = {
            "git status", "git log", "git diff", "git show", "git describe",
            "git grep", "git ls-files", "git branch", "git tag", "git reflog",
            "git cat-file", "git blame", "git shortlog", "git for-each-ref",
            "npm list", "npm view", "npm search", "npm info",
        }
        if prefix in read_only_prefixes:
            return True

    return False


def _has_file_redirection(command: str) -> bool:
    """True when the command redirects output to a file.

    Ignores fd-duplication (``2>&1``) and redirects to ``/dev/null`` since
    neither writes a real file. Conservative by design: a quoted ``>`` may
    trigger a false positive, which only costs one extra approval prompt.
    """
    for match in _REDIRECT_RE.finditer(command):
        target = match.group(1)
        if target.startswith("&") or target == "/dev/null":
            continue
        return True
    return False


def _is_workspace_safe_command(command: str) -> bool:
    """Check if command is safe within the workspace."""
    first_word = command.split()[0] if command.split() else ""
    return first_word in WORKSPACE_SAFE_COMMANDS


def _all_segments_known_safe(command: str) -> bool:
    """Check if all segments in a chained command are known-safe."""
    # Split on command chain operators
    segments = []
    current = ""
    for char in command:
        if char in "&|;":
            if current.strip():
                segments.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        segments.append(current.strip())

    # Check each segment
    for segment in segments:
        first_word = segment.split()[0] if segment.split() else ""
        if first_word not in SAFE_COMMANDS and first_word not in WORKSPACE_SAFE_COMMANDS:
            return False
    return True
