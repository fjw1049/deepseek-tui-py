"""One-shot migration of ``~/.deepseek`` into the lifecycle layout.

Safe to call repeatedly. Moves legacy directories/files into the L0–L5
structure documented in ``MANIFEST.toml`` / :mod:`deepseek_tui.config.paths`.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from deepseek_tui.config.paths import user_deepseek_dir

logger = logging.getLogger(__name__)

_MANIFEST_MARKER = "MANIFEST.toml"


def ensure_user_home_layout(home: Path | None = None) -> list[str]:
    """Migrate legacy paths under ``home`` (default ``~/.deepseek``).

    Returns a list of human-readable migration actions performed.
    """
    root = home or user_deepseek_dir()
    root.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []

    actions.extend(_migrate_agents(root))
    actions.extend(_migrate_plugin_host(root))
    actions.extend(_migrate_automations_defs(root))
    actions.extend(_migrate_workflow_dir(root))
    actions.extend(_ensure_manifest(root))
    actions.extend(_drop_empty_dirs(root))

    for path in (
        root / "agents" / "registries",
        root / "agents" / "runs",
        root / "logs",
        root / "tool_outputs",
        root / "threads",
        root / "sessions",
        root / "workflow",
        root / "automations" / "runs",
        root / "plugins" / ".host",
        # workbench/usage only — do NOT pre-create workbench/claw/; an empty
        # claw/ would block GUI migration of legacy ~/.deepseekgui/claw.
        root / "workbench" / "usage",
    ):
        path.mkdir(parents=True, exist_ok=True)

    return actions


def _migrate_agents(root: Path) -> list[str]:
    actions: list[str] = []
    agents = root / "agents"
    registries = agents / "registries"
    runs = agents / "runs"
    registries.mkdir(parents=True, exist_ok=True)
    runs.mkdir(parents=True, exist_ok=True)

    legacy_reg = root / "subagents"
    if legacy_reg.is_dir():
        for child in list(legacy_reg.iterdir()):
            if not child.is_file():
                continue
            dest = registries / child.name
            if not dest.exists():
                shutil.move(str(child), str(dest))
                actions.append(f"moved {child.name} → agents/registries/")
            else:
                child.unlink(missing_ok=True)
                actions.append(f"dropped duplicate subagents/{child.name}")
        _rm_if_empty(legacy_reg, actions, "subagents/")

    legacy_runs = root / "subagent-runs"
    if legacy_runs.is_dir():
        for child in list(legacy_runs.iterdir()):
            dest = runs / child.name
            if not dest.exists():
                shutil.move(str(child), str(dest))
                actions.append(f"moved {child.name} → agents/runs/")
            else:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                actions.append(f"dropped duplicate subagent-runs/{child.name}")
        _rm_if_empty(legacy_runs, actions, "subagent-runs/")

    return actions


def _migrate_plugin_host(root: Path) -> list[str]:
    actions: list[str] = []
    legacy = root / "plugin-host"
    dest = root / "plugins" / ".host"
    if not legacy.exists():
        return actions
    if dest.exists():
        # Prefer existing new location; drop leftover legacy if empty-ish.
        if legacy.is_dir():
            for child in list(legacy.iterdir()):
                target = dest / child.name
                if not target.exists():
                    shutil.move(str(child), str(target))
                    actions.append(f"merged plugin-host/{child.name} → plugins/.host/")
                else:
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
            _rm_if_empty(legacy, actions, "plugin-host/")
        return actions
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy), str(dest))
    actions.append("moved plugin-host/ → plugins/.host/")
    return actions


def _migrate_automations_defs(root: Path) -> list[str]:
    """Flatten ``automations/automations/*.json`` up to ``automations/*.json``."""
    actions: list[str] = []
    auto_root = root / "automations"
    nested = auto_root / "automations"
    if not nested.is_dir():
        return actions
    auto_root.mkdir(parents=True, exist_ok=True)
    for child in list(nested.iterdir()):
        if child.suffix != ".json" or not child.is_file():
            continue
        dest = auto_root / child.name
        if not dest.exists():
            shutil.move(str(child), str(dest))
            actions.append(f"moved automations/automations/{child.name} → automations/")
        else:
            child.unlink(missing_ok=True)
            actions.append(f"dropped duplicate automations/automations/{child.name}")
    _rm_if_empty(nested, actions, "automations/automations/")
    return actions


def _migrate_workflow_dir(root: Path) -> list[str]:
    """Rename ``workflow-runs/`` → ``workflow/``.

    When both trees exist and a ``run_id`` collides, keep the destination copy
    and quarantine the legacy tree under ``workflow/.migrated-dupes/`` instead
    of deleting it — resume safety over aggressive cleanup.
    """
    actions: list[str] = []
    legacy = root / "workflow-runs"
    dest = root / "workflow"
    if not legacy.exists():
        return actions
    if dest.exists():
        if legacy.is_dir():
            quarantine = dest / ".migrated-dupes"
            for child in list(legacy.iterdir()):
                target = dest / child.name
                if not target.exists():
                    shutil.move(str(child), str(target))
                    actions.append(f"merged workflow-runs/{child.name} → workflow/")
                    continue
                quarantine.mkdir(parents=True, exist_ok=True)
                q_dest = quarantine / child.name
                if q_dest.exists():
                    q_dest = quarantine / f"{child.name}.{_unique_suffix()}"
                shutil.move(str(child), str(q_dest))
                actions.append(
                    f"quarantined duplicate workflow-runs/{child.name} → "
                    f"workflow/.migrated-dupes/"
                )
            _rm_if_empty(legacy, actions, "workflow-runs/")
        return actions
    shutil.move(str(legacy), str(dest))
    actions.append("moved workflow-runs/ → workflow/")
    return actions


def _unique_suffix() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _ensure_manifest(root: Path) -> list[str]:
    path = root / _MANIFEST_MARKER
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if "workflow-runs/" in text:
            path.write_text(_DEFAULT_MANIFEST, encoding="utf-8")
            return [f"updated {_MANIFEST_MARKER} (workflow-runs → workflow)"]
        return []
    path.write_text(_DEFAULT_MANIFEST, encoding="utf-8")
    return [f"wrote {_MANIFEST_MARKER}"]


def _drop_empty_dirs(root: Path) -> list[str]:
    actions: list[str] = []
    for name in ("automation",):
        path = root / name
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            actions.append(f"removed empty {name}/")
    return actions


def _rm_if_empty(path: Path, actions: list[str], label: str) -> None:
    if not path.exists():
        return
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            actions.append(f"removed empty {label}")
    except OSError:
        logger.debug("could not remove %s", path, exc_info=True)


_DEFAULT_MANIFEST = """# ~/.deepseek layout — lifecycle layers for backup / archive / GC
# Principle: own by lifecycle, index by id.

schema_version = 1

[layers.L0_identity]
paths = ["config.toml", "AGENTS.md", "mcp.json", "secrets/"]
retention = "permanent"
backup = "required"

[layers.L1_capabilities]
paths = ["skills/", "plugins/", "plugins/.host/"]
retention = "permanent"
backup = "custom_only"

[layers.L2_conversations]
paths_canonical = ["threads/"]
paths_legacy = ["sessions/"]
retention = "archive_then_purge"
backup = "required"
notes = "threads/ is the source of truth; sessions/ is TUI legacy (current.json)."

[layers.L3_jobs]
paths = [
  "tasks/",
  "automations/",
  "workflow/",
  "agents/registries/",
  "agents/runs/",
]
retention = "hot_30_to_90_days"
backup = "optional_completed"

[layers.L4_ephemeral]
paths = [
  "logs/",
  "hooks/",
  "tool_outputs/",
  "mcp-tools-cache.json",
  "workbench/settings.json",
  "workbench/claw/",
  "workbench/usage/",
  "workbench/logs/",
  "workbench/pet-cache/",
  "workbench/marketplace-cache/",
  "runtime.token",
]
retention = "days_to_weeks"
backup = "skip"
notes = "GUI product state under workbench/; Electron userData is Chromium cache only."

[layers.L5_scratch]
paths = ["workspace/", "notes.txt"]
retention = "user_managed"
backup = "skip"

[gc]
logs_keep_hours = 168
tool_outputs_max_age_days = 7
completed_jobs_hot_days = 60
hooks_events_max_mb = 50

[archive]
unit_primary = "threads"
unit_secondary = ["tasks", "workflow", "automations/runs"]
"""
