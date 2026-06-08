"""Slash command registry and dispatcher.

Mirrors ``crates/tui/src/commands/mod.rs``. Central registry of slash
commands with description, aliases, and handler dispatch.
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.tui.app import DeepSeekTUI

__all__ = [
    "CommandCategory",
    "CommandEntry",
    "CommandResult",
    "REGISTRY",
    "dispatch",
    "get_completions",
]

_LOG = logging.getLogger(__name__)


class CommandCategory(str, enum.Enum):
    DISPLAY = "display"
    CONFIG = "config"
    SESSION = "session"
    ENGINE = "engine"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Return value from a slash command handler."""

    output: str = ""
    error: str = ""
    exit_app: bool = False


@dataclass(frozen=True, slots=True)
class CommandEntry:
    """A single registered slash command."""

    name: str
    description: str
    category: CommandCategory
    aliases: tuple[str, ...] = ()


# Helper to shorten definitions.
_D = CommandCategory.DISPLAY
_C = CommandCategory.CONFIG
_S = CommandCategory.SESSION
_E = CommandCategory.ENGINE
_T = CommandCategory.TOOL

# ── Registry ─────────────────────────────────────────────────────────────

REGISTRY: list[CommandEntry] = [
    CommandEntry("/help", "Show help information", _D, ("/?",)),
    CommandEntry("/clear", "Clear conversation history", _S),
    CommandEntry("/exit", "Exit the application", _S, ("/quit", "/q")),
    CommandEntry("/model", "Switch or view current model", _E),
    CommandEntry("/provider", "Switch LLM backend", _E),
    CommandEntry(
        "/hooks", "List lifecycle hooks",
        _D, ("/hook",),
    ),
    CommandEntry(
        "/subagents", "List sub-agent status",
        _T, ("/agents",),
    ),
    CommandEntry(
        "/task", "Manage background tasks",
        _T, ("/tasks",),
    ),
    CommandEntry(
        "/jobs", "Inspect shell jobs",
        _T, ("/job",),
    ),
    CommandEntry("/mcp", "Manage MCP servers", _T),
    CommandEntry("/save", "Save session to file", _S),
    CommandEntry("/load", "Load session from file", _S),
    CommandEntry(
        "/compact", "Trigger context compaction",
        _S,
    ),
    CommandEntry("/context", "Context inspector", _D, ("/ctx",)),
    CommandEntry("/export", "Export to markdown", _S),
    CommandEntry("/config", "Open configuration editor", _C),
    CommandEntry("/memory", "View or edit user memory file", _C),
    CommandEntry(
        "/mode",
        "Switch or cycle mode (agent / plan / yolo / ask / goal / workflow)",
        _C,
    ),
    CommandEntry("/yolo", "Enable YOLO mode", _C),
    CommandEntry("/agent", "Switch to agent mode", _C),
    CommandEntry("/plan", "Switch to plan mode", _C),
    CommandEntry("/workflow", "Switch to workflow mode", _C),
    CommandEntry("/logout", "Clear API key", _C),
    CommandEntry("/tokens", "Show token usage", _D),
    CommandEntry("/system", "Show system prompt", _D),
    CommandEntry(
        "/diff", "Show file changes",
        _D,
    ),
    CommandEntry("/init", "Generate AGENTS.md", _T),
    CommandEntry("/settings", "Show persistent settings", _D),
    CommandEntry(
        "/skills", "List local skills",
        _T,
    ),
    CommandEntry(
        "/skill", "Activate/install a skill",
        _T,
    ),
    CommandEntry("/cost", "Session cost breakdown", _D),
    CommandEntry(
        "/log", "Show log file path; '/log tail [N]' prints last N lines",
        _D,
    ),
    CommandEntry("/undo", "Undo last file-modifying tool", _E),
    CommandEntry("/goal", "Manage the active goal", _T),
]

# Build lookup dicts for fast dispatch.
_BY_NAME: dict[str, CommandEntry] = {}
_ALIAS_TO_NAME: dict[str, str] = {}
for _entry in REGISTRY:
    _BY_NAME[_entry.name] = _entry
    for _alias in _entry.aliases:
        _ALIAS_TO_NAME[_alias] = _entry.name


def resolve(input_name: str) -> CommandEntry | None:
    """Resolve a slash command name (including aliases)."""
    if input_name in _BY_NAME:
        return _BY_NAME[input_name]
    canonical = _ALIAS_TO_NAME.get(input_name)
    if canonical:
        return _BY_NAME[canonical]
    return None


def get_completions(prefix: str = "") -> list[tuple[str, str]]:
    """Return (name, description) pairs matching a prefix."""
    results: list[tuple[str, str]] = []
    for entry in REGISTRY:
        if entry.name.startswith(prefix):
            results.append((entry.name, entry.description))
    return results


def dispatch(raw_input: str, app: DeepSeekTUI) -> CommandResult:
    """Parse and dispatch a slash command.

    Mirrors ``commands::execute`` in Rust ``mod.rs``.
    """
    parts = raw_input.strip().split(maxsplit=1)
    if not parts:
        return CommandResult(error="empty command")

    cmd_name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    entry = resolve(cmd_name)
    if entry is None:
        return CommandResult(
            error=f"unknown command: {cmd_name}. Type /help",
        )

    from . import handlers
    handler_fn = handlers.get_handler(entry.name)
    if handler_fn is None:
        return CommandResult(error=f"{entry.name} has no handler")

    try:
        return handler_fn(args, app)
    except Exception as exc:
        _LOG.exception("slash command %s failed", entry.name)
        return CommandResult(error=f"{entry.name} failed: {exc}")
