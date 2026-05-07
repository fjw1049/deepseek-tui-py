"""Command safety analysis for shell execution.

Mirrors `crates/tui/src/command_safety.rs` (1,200 lines).
Detects potentially dangerous shell command patterns and assigns safety levels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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


# Arity dictionary: maps command prefix (space-separated, lowercase) to the
# number of positional (non-flag) words, including the base command word,
# that form the canonical prefix. Flags (tokens starting with -) are never
# counted toward arity.
COMMAND_ARITY: dict[str, int] = {
    # git
    "git add": 2,
    "git am": 2,
    "git apply": 2,
    "git bisect": 2,
    "git blame": 2,
    "git branch": 2,
    "git cat-file": 2,
    "git checkout": 2,
    "git cherry-pick": 2,
    "git clean": 2,
    "git clone": 2,
    "git commit": 2,
    "git config": 2,
    "git describe": 2,
    "git diff": 2,
    "git fetch": 2,
    "git format-patch": 2,
    "git grep": 2,
    "git init": 2,
    "git log": 2,
    "git ls-files": 2,
    "git merge": 2,
    "git mv": 2,
    "git notes": 2,
    "git pull": 2,
    "git push": 2,
    "git rebase": 2,
    "git reflog": 2,
    "git remote": 2,
    "git reset": 2,
    "git restore": 2,
    "git revert": 2,
    "git rm": 2,
    "git show": 2,
    "git stash": 2,
    "git status": 2,
    "git submodule": 2,
    "git switch": 2,
    "git tag": 2,
    "git worktree": 2,
    # npm
    "npm audit": 2,
    "npm build": 2,
    "npm cache": 2,
    "npm ci": 2,
    "npm dedupe": 2,
    "npm fund": 2,
    "npm help": 2,
    "npm info": 2,
    "npm init": 2,
    "npm install": 2,
    "npm link": 2,
    "npm list": 2,
    "npm ls": 2,
    "npm outdated": 2,
    "npm pack": 2,
    "npm prune": 2,
    "npm publish": 2,
    "npm rebuild": 2,
    "npm repo": 2,
    "npm restart": 2,
    "npm run": 2,
    "npm search": 2,
    "npm shrinkwrap": 2,
    "npm start": 2,
    "npm stop": 2,
    "npm test": 2,
    "npm uninstall": 2,
    "npm update": 2,
    "npm view": 2,
    # cargo
    "cargo add": 2,
    "cargo bench": 2,
    "cargo build": 2,
    "cargo check": 2,
    "cargo clean": 2,
    "cargo clippy": 2,
    "cargo doc": 2,
    "cargo fetch": 2,
    "cargo fix": 2,
    "cargo fmt": 2,
    "cargo init": 2,
    "cargo install": 2,
    "cargo metadata": 2,
    "cargo new": 2,
    "cargo publish": 2,
    "cargo remove": 2,
    "cargo run": 2,
    "cargo search": 2,
    "cargo test": 2,
    "cargo tree": 2,
    "cargo update": 2,
    "cargo vendor": 2,
    # python
    "python -m": 2,
    "python3 -m": 2,
    # docker
    "docker run": 2,
    "docker build": 2,
    "docker ps": 2,
    "docker pull": 2,
    "docker push": 2,
    "docker compose": 2,
    # node
    "node --version": 2,
    "node -e": 2,
}

# Known safe commands that only read data
SAFE_COMMANDS = {
    "ls", "dir", "pwd", "cat", "head", "tail", "less", "more", "grep", "rg", "ag",
    "find", "fd", "which", "whereis", "type", "echo", "printf", "date", "cal",
    "uptime", "whoami", "id", "hostname", "uname", "env", "printenv", "set", "ps",
    "top", "htop", "df", "du", "free", "vmstat", "wc", "sort", "uniq", "cut", "tr",
    "sed", "awk", "gawk", "perl", "ruby", "python", "python3", "node", "deno",
    "stat", "file", "tree", "lsof", "lsblk", "blkid", "mount", "systemctl", "service",
}

# Commands that are safe within the workspace but may modify files
WORKSPACE_SAFE_COMMANDS = {
    "cargo", "npm", "python", "python3", "node", "ruby", "go", "rustc", "javac",
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
    """Analyze a shell command for safety.

    Mirrors Rust `analyze_command()` (command_safety.rs:515-650).
    """
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


def classify_command(tokens: list[str]) -> str:
    """Classify a command from token list to canonical prefix.

    The prefix is determined by COMMAND_ARITY: for each known prefix,
    concatenate the first N tokens (skipping flags) to get the canonical form.
    """
    if not tokens:
        return ""

    # Build the command by joining non-flag tokens
    cmd_parts = []
    for token in tokens:
        if token.startswith("-"):
            continue
        cmd_parts.append(token)

        # Check if current prefix is in COMMAND_ARITY
        prefix = " ".join(cmd_parts).lower()
        if prefix in COMMAND_ARITY:
            arity = COMMAND_ARITY[prefix]
            if len(cmd_parts) >= arity:
                return prefix

    # Return joined tokens if no match
    return " ".join(tokens).lower()
