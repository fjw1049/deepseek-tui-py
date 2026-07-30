"""Path resolution for the ``.deepseek/`` data directories.

User home ``~/.deepseek/`` is layered by lifecycle (see ``MANIFEST.toml``):

* **L0 identity** — config, AGENTS.md, mcp.json, secrets
* **L1 capabilities** — skills, plugins (+ ``plugins/.host``)
* **L2 conversations** — ``threads/`` is canonical; ``sessions/`` is TUI legacy
* **L3 jobs** — tasks, automations, workflow, ``agents/{registries,runs}``
* **L4 ephemeral** — logs, hooks, tool_outputs, caches
* **L5 scratch** — default ``workspace/``, notes.txt

Indexed by id (or workspace key for subagent registries), not by living
inside a git checkout.

Project-level ``<workspace>/.deepseek/`` is optional override only
(e.g. ``config.toml``). Not created by default; team guidance belongs in
repo-root ``AGENTS.md``.

Callers MUST go through the typed helpers below. Do not hardcode
``Path.home() / ".deepseek"`` or ``Path.cwd() / ".deepseek"``; do not
introduce new "layer-ambiguous" helpers.
"""

from __future__ import annotations

import hashlib
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
    """Resolve ``~/.deepseek/`` (or ``$DEEPSEEK_HOME``)."""
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
    """``~/.deepseek/notes.txt`` — user scratch notes."""
    return user_deepseek_dir() / "notes.txt"


def user_audit_log_path() -> Path:
    """``~/.deepseek/audit.log`` — cross-project approval audit log."""
    return user_deepseek_dir() / "audit.log"


def user_sessions_dir() -> Path:
    """``~/.deepseek/sessions/`` — TUI legacy session JSON (not Workbench SoT).

    Workbench conversations live in :func:`user_threads_dir`. TUI still
    persists ``current.json`` / picker dumps here for crash recovery.
    """
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
    """``~/.deepseek/tasks/`` (or ``$DEEPSEEK_TASKS_DIR``)."""
    override = os.getenv("DEEPSEEK_TASKS_DIR")
    if override:
        return expand_path(override)
    return user_deepseek_dir() / "tasks"


def user_threads_dir() -> Path:
    """``~/.deepseek/threads/`` — canonical conversation ledger (Workbench)."""
    return user_deepseek_dir() / "threads"


def user_skills_dir() -> Path:
    """``~/.deepseek/skills/`` — cross-project user skills."""
    return user_deepseek_dir() / "skills"


def user_state_db_path() -> Path:
    """``~/.deepseek/state.db`` — CLI/daemon local SQLite state."""
    return user_deepseek_dir() / "state.db"


def user_execpolicy_path() -> Path:
    """``~/.deepseek/execpolicy.toml`` — exec policy ruleset."""
    return user_deepseek_dir() / "execpolicy.toml"


def user_mcp_config_path() -> Path:
    """``~/.deepseek/mcp.json`` — user MCP server config."""
    return user_deepseek_dir() / "mcp.json"


def user_logs_dir() -> Path:
    """``~/.deepseek/logs/`` — application rotating logs."""
    return user_deepseek_dir() / "logs"


def user_workflow_runs_dir() -> Path:
    """``~/.deepseek/workflow/`` — workflow checkpoints by ``run_id``."""
    return user_deepseek_dir() / "workflow"


def user_agent_runtime_dir() -> Path:
    """``~/.deepseek/agents/`` — sub-agent registries + run transcripts."""
    return user_deepseek_dir() / "agents"


def user_subagents_registries_dir() -> Path:
    """``~/.deepseek/agents/registries/`` — SubAgentManager state files."""
    return user_agent_runtime_dir() / "registries"


def user_subagent_runs_dir() -> Path:
    """``~/.deepseek/agents/runs/`` — sub-agent transcripts by ``agent_id``."""
    return user_agent_runtime_dir() / "runs"


def workspace_storage_key(workspace: Path | None = None) -> str:
    """Stable short key for a workspace path (manager isolation, not a project asset)."""
    root = (workspace or Path.cwd()).resolve()
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]


def user_subagents_state_path(workspace: Path | None = None) -> Path:
    """``~/.deepseek/agents/registries/<workspace_key>.json`` — SubAgentManager registry.

    One file per workspace so concurrent engines on different checkouts do not
    clobber each other. Storage stays under the user home, not the git tree.
    """
    return (
        user_subagents_registries_dir()
        / f"{workspace_storage_key(workspace)}.json"
    )


def user_automations_dir() -> Path:
    """``~/.deepseek/automations/`` — defs (``*.json``) + ``runs/``."""
    return user_deepseek_dir() / "automations"


def user_plugin_host_dir() -> Path:
    """``~/.deepseek/plugins/.host/`` — content-addressed plugin store."""
    return user_deepseek_dir() / "plugins" / ".host"


def workbench_dir() -> Path:
    """``~/.deepseek/workbench/`` — GUI settings, Claw, usage, logs, caches."""
    return user_deepseek_dir() / "workbench"


def workbench_settings_path() -> Path:
    """``~/.deepseek/workbench/settings.json`` — Workbench GUI settings."""
    return workbench_dir() / "settings.json"


def workbench_usage_dir() -> Path:
    """``~/.deepseek/workbench/usage/`` — Workbench model usage ledger."""
    return workbench_dir() / "usage"


def workbench_usage_ledger_path() -> Path:
    """``~/.deepseek/workbench/usage/ledger-v1.json`` — daily model usage."""
    return workbench_usage_dir() / "ledger-v1.json"


# ---------------------------------------------------------------------------
# Project-level: <workspace>/.deepseek/ (optional override only)
# ---------------------------------------------------------------------------


def project_deepseek_dir(workspace: Path | None = None) -> Path:
    """Resolve ``<workspace>/.deepseek/`` (optional; not created by default)."""
    root = workspace or Path.cwd()
    return root / DOT_DEEPSEEK


def project_config_path(workspace: Path | None = None) -> Path:
    """``<workspace>/.deepseek/config.toml`` — optional project override config."""
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
