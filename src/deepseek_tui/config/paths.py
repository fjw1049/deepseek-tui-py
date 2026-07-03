"""Path resolution for the ``.deepseek/`` data directories.

Two-layer layout, mirroring Rust ``crates/tui/src/config.rs:1690-1930``:

* **User-level** ``~/.deepseek/`` — cross-project state: credentials,
  session history, audit log, composer history,
  workspace trust, MCP config, user skills, task queue.
* **Project-level** ``<workspace>/.deepseek/`` — checkout-scoped state:
  project config overrides, current session handoff, active sub-agent
  state, auto-generated project instructions, project skills, logs.

Callers MUST go through the typed helpers below. Do not hardcode
``Path.home() / ".deepseek"`` or ``Path.cwd() / ".deepseek"``; do not
introduce new "layer-ambiguous" helpers.
"""

from __future__ import annotations

import os
from pathlib import Path

DOT_DEEPSEEK = ".deepseek"

DEFAULT_MANAGED_CONFIG_PATH = Path("/etc/deepseek/managed_config.toml")
DEFAULT_REQUIREMENTS_PATH = Path("/etc/deepseek/requirements.toml")


def expand_path(path: Path | str) -> Path:
    raw = os.path.expandvars(str(path))
    return Path(raw).expanduser()


# ---------------------------------------------------------------------------
# User-level: ~/.deepseek/
# ---------------------------------------------------------------------------


def user_deepseek_dir() -> Path:
    """Resolve ``~/.deepseek/`` (or ``$DEEPSEEK_HOME``).

    Mirrors Rust ``effective_home_dir()`` (tui/config.rs:1690-1722).
    """
    override = os.getenv("DEEPSEEK_HOME")
    if override:
        return expand_path(override)
    return Path.home() / DOT_DEEPSEEK


def user_config_path() -> Path:
    """``~/.deepseek/config.toml`` — global credentials & defaults."""
    override = os.getenv("DEEPSEEK_CONFIG_PATH")
    if override:
        return expand_path(override)
    return user_deepseek_dir() / "config.toml"


def user_agents_path() -> Path:
    """``~/.deepseek/AGENTS.md`` — global fallback instructions."""
    return user_deepseek_dir() / "AGENTS.md"


def user_notes_path() -> Path:
    """``~/.deepseek/notes.txt`` — user scratch notes (matches Rust .txt)."""
    return user_deepseek_dir() / "notes.txt"


def user_audit_log_path() -> Path:
    """``~/.deepseek/audit.log`` — cross-project approval audit log."""
    return user_deepseek_dir() / "audit.log"


def user_sessions_dir() -> Path:
    """``~/.deepseek/sessions/`` — all session history, cycles, artifacts."""
    return user_deepseek_dir() / "sessions"


def user_checkpoints_dir() -> Path:
    """``~/.deepseek/sessions/checkpoints/`` — crash recovery snapshots."""
    return user_sessions_dir() / "checkpoints"


def user_tool_outputs_dir() -> Path:
    """``~/.deepseek/tool_outputs/`` — spilled large tool results (#422)."""
    return user_deepseek_dir() / "tool_outputs"


def user_session_dir(session_id: str) -> Path:
    return user_sessions_dir() / session_id


def user_session_cycles_dir(session_id: str) -> Path:
    """``~/.deepseek/sessions/<id>/cycles/`` — archived cycle JSONL."""
    return user_session_dir(session_id) / "cycles"


def user_tasks_dir() -> Path:
    """``~/.deepseek/tasks/`` (or ``$DEEPSEEK_TASKS_DIR``).

    Mirrors Rust ``default_tasks_dir`` (task_manager.rs:1629).
    """
    override = os.getenv("DEEPSEEK_TASKS_DIR")
    if override:
        return expand_path(override)
    return user_deepseek_dir() / "tasks"


def user_threads_dir() -> Path:
    """``~/.deepseek/threads/`` — Python-only thread store (kept user-level)."""
    return user_deepseek_dir() / "threads"


def user_skills_dir() -> Path:
    """``~/.deepseek/skills/`` — cross-project user skills."""
    return user_deepseek_dir() / "skills"


def user_state_db_path() -> Path:
    """``~/.deepseek/state.db`` — CLI/daemon local SQLite state."""
    return user_deepseek_dir() / "state.db"


def user_execpolicy_path() -> Path:
    """``~/.deepseek/execpolicy.toml`` — exec policy ruleset.

    Mirrors Rust ``default_execpolicy_path`` (execpolicy/rules.rs:72-74).
    """
    return user_deepseek_dir() / "execpolicy.toml"


def user_mcp_config_path() -> Path:
    """``~/.deepseek/mcp.json`` — user MCP server config."""
    return user_deepseek_dir() / "mcp.json"


def workbench_usage_dir() -> Path:
    """``~/.deepseek/workbench/usage/`` — Workbench model usage ledger."""
    return user_deepseek_dir() / "workbench" / "usage"


def workbench_usage_ledger_path() -> Path:
    """``~/.deepseek/workbench/usage/ledger-v1.json`` — daily model usage."""
    return workbench_usage_dir() / "ledger-v1.json"


# ---------------------------------------------------------------------------
# Project-level: <workspace>/.deepseek/
# ---------------------------------------------------------------------------


def project_deepseek_dir(workspace: Path | None = None) -> Path:
    """Resolve ``<workspace>/.deepseek/``."""
    root = workspace or Path.cwd()
    return root / DOT_DEEPSEEK


def project_config_path(workspace: Path | None = None) -> Path:
    """``<workspace>/.deepseek/config.toml`` — project override config."""
    return project_deepseek_dir(workspace) / "config.toml"


def project_instructions_path(workspace: Path | None = None) -> Path:
    """``<workspace>/.deepseek/instructions.md`` — auto-generated fallback."""
    return project_deepseek_dir(workspace) / "instructions.md"


def dotenv_path(workspace: Path | None = None) -> Path:
    """``<workspace>/.env``."""
    return (workspace or Path.cwd()) / ".env"


# ---------------------------------------------------------------------------
# Dotenv loader (unchanged)
# ---------------------------------------------------------------------------


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# Module-level back-compat constants
# ---------------------------------------------------------------------------

# Some legacy callers import these top-level constants directly. Keep them
# pointing at the user-level ``.deepseek/`` location; ``config/loader.py``
# uses them as default search paths.

DEFAULT_DOT_DEEPSEEK_RELATIVE = Path(DOT_DEEPSEEK)
PROJECT_CONFIG_RELATIVE = DEFAULT_DOT_DEEPSEEK_RELATIVE / "config.toml"
