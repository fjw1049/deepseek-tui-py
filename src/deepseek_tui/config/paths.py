"""Path resolution for the ``.deepseek/`` data directories.

Two-layer layout, mirroring Rust ``crates/tui/src/config.rs:1690-1930``:

* **User-level** ``~/.deepseek/`` — cross-project state: credentials,
  long-term memory, session history, audit log, composer history,
  workspace trust, MCP config, user skills, task queue.
* **Project-level** ``<workspace>/.deepseek/`` — checkout-scoped state:
  project config overrides, current session handoff, active sub-agent
  state, auto-generated project instructions, project skills, logs.

Callers MUST go through the typed helpers below. Do not hardcode
``Path.home() / ".deepseek"`` or ``Path.cwd() / ".deepseek"``; do not
introduce new "layer-ambiguous" helpers. See
``memory/path-layout-contract.md``.
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


def user_managed_config_path() -> Path:
    """``~/.deepseek/managed_config.toml`` — enterprise admin config."""
    return user_deepseek_dir() / "managed_config.toml"


def user_requirements_path() -> Path:
    """``~/.deepseek/requirements.toml`` — enterprise hard requirements."""
    return user_deepseek_dir() / "requirements.toml"


def user_agents_path() -> Path:
    """``~/.deepseek/AGENTS.md`` — global fallback instructions."""
    return user_deepseek_dir() / "AGENTS.md"


def user_memory_path() -> Path:
    """``~/.deepseek/memory.md`` — cross-project long-term memory."""
    return user_deepseek_dir() / "memory.md"


def user_memory_data_dir() -> Path:
    """``~/.deepseek/memory_data/`` — native L0 JSONL + L1 SQLite store."""
    return user_deepseek_dir() / "memory_data"




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


def user_session_artifacts_dir(session_id: str) -> Path:
    """``~/.deepseek/sessions/<id>/artifacts/`` — large tool output blobs."""
    return user_session_dir(session_id) / "artifacts"


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


def user_stash_dir() -> Path:
    """``~/.deepseek/stash/`` — named markdown snippets (/stash command)."""
    return user_deepseek_dir() / "stash"


def user_skills_dir() -> Path:
    """``~/.deepseek/skills/`` — cross-project user skills."""
    return user_deepseek_dir() / "skills"


def user_skill_state_path() -> Path:
    """``~/.deepseek/skill_state.toml`` — skill enable/disable state."""
    return user_deepseek_dir() / "skill_state.toml"


def user_roles_dir() -> Path:
    """``~/.deepseek/roles/`` — custom sub-agent role TOML."""
    return user_deepseek_dir() / "roles"


def user_state_db_path() -> Path:
    """``~/.deepseek/state.db`` — CLI/daemon local SQLite state."""
    return user_deepseek_dir() / "state.db"


def user_execpolicy_path() -> Path:
    """``~/.deepseek/execpolicy.toml`` — exec policy ruleset.

    Mirrors Rust ``default_execpolicy_path`` (execpolicy/rules.rs:72-74).
    """
    return user_deepseek_dir() / "execpolicy.toml"


def user_onboarded_marker_path() -> Path:
    """``~/.deepseek/.onboarded`` — completion flag for first-run wizard."""
    return user_deepseek_dir() / ".onboarded"


def user_mcp_config_path() -> Path:
    """``~/.deepseek/mcp.json`` — user MCP server config."""
    return user_deepseek_dir() / "mcp.json"


def user_composer_history_path() -> Path:
    """``~/.deepseek/composer_history`` — input history (zsh-style)."""
    return user_deepseek_dir() / "composer_history"


def user_composer_stash_path() -> Path:
    """``~/.deepseek/composer_stash.jsonl`` — draft input stash."""
    return user_deepseek_dir() / "composer_stash.jsonl"


def user_workspace_trust_path() -> Path:
    """``~/.deepseek/workspace-trust.json`` — trusted workspace decisions."""
    return user_deepseek_dir() / "workspace-trust.json"


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


def project_handoff_path(workspace: Path | None = None) -> Path:
    """``<workspace>/.deepseek/handoff.md`` — current session handoff."""
    return project_deepseek_dir(workspace) / "handoff.md"


def project_subagent_state_path(workspace: Path | None = None) -> Path:
    """``<workspace>/.deepseek/subagents.v1.json`` — active sub-agents."""
    return project_deepseek_dir(workspace) / "subagents.v1.json"


def project_plan_path(workspace: Path | None = None) -> Path:
    """``<workspace>/.deepseek/plan.md`` — current task high-level plan."""
    return project_deepseek_dir(workspace) / "plan.md"


def project_skills_dir(workspace: Path | None = None) -> Path:
    """``<workspace>/.deepseek/skills/`` — project-level skills."""
    return project_deepseek_dir(workspace) / "skills"


def project_logs_dir(workspace: Path | None = None) -> Path:
    """``<workspace>/.deepseek/logs/`` — project runtime logs."""
    return project_deepseek_dir(workspace) / "logs"


# ---------------------------------------------------------------------------
# Project root (NOT inside .deepseek/)
# ---------------------------------------------------------------------------


def project_agents_md(workspace: Path | None = None) -> Path:
    """``<workspace>/AGENTS.md`` — first-priority project instructions."""
    return (workspace or Path.cwd()) / "AGENTS.md"


def project_claude_instructions(workspace: Path | None = None) -> Path:
    """``<workspace>/.claude/instructions.md`` — second-priority."""
    return (workspace or Path.cwd()) / ".claude" / "instructions.md"


def project_claude_md(workspace: Path | None = None) -> Path:
    """``<workspace>/CLAUDE.md`` — third-priority project instructions."""
    return (workspace or Path.cwd()) / "CLAUDE.md"


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
