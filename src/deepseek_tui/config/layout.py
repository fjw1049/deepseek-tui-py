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
    actions.extend(_migrate_workbench(root))
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


def _migrate_workbench(root: Path) -> list[str]:
    """Flatten the legacy ``workbench/`` GUI-state umbrella to the top level.

    * ``workbench/settings.json``            → ``settings.json``
    * ``workbench/usage/ledger-v1.json``     → ``usage.json``
    * ``workbench/backup-meta.json``         → merged into ``settings.json`` (``backup`` key)
    * ``workbench/claw/``                    → ``claw/`` (active IM sandbox, not a cache)
    * ``workbench/{logs,pet-cache,marketplace-cache}/`` → ``caches/…``

    ``claw/`` holds IM sandbox workspaces the automation pipeline still uses, so it
    is promoted to the top level rather than filed under ``caches/`` (which the GUI
    treats as safely wipeable).
    """
    actions: list[str] = []
    legacy = root / "workbench"
    if not legacy.is_dir():
        return actions

    settings_dest = root / "settings.json"

    # 1) settings.json → top level. When a top-level file already exists, keep it
    #    and quarantine the legacy copy so workbench/ can still be emptied.
    legacy_settings = legacy / "settings.json"
    if legacy_settings.is_file():
        if not settings_dest.exists():
            shutil.move(str(legacy_settings), str(settings_dest))
            actions.append("moved workbench/settings.json → settings.json")
        else:
            actions.extend(_quarantine(legacy, legacy_settings, "settings.json"))

    # 2) usage/ledger-v1.json → usage.json (flat single file, no usage/ dir).
    legacy_ledger = legacy / "usage" / "ledger-v1.json"
    usage_dest = root / "usage.json"
    if legacy_ledger.is_file():
        if not usage_dest.exists():
            shutil.move(str(legacy_ledger), str(usage_dest))
            actions.append("moved workbench/usage/ledger-v1.json → usage.json")
        else:
            actions.extend(_quarantine(legacy, legacy_ledger, "usage-ledger-v1.json"))
    _rm_if_empty(legacy / "usage", actions, "workbench/usage/")

    # 3) backup-meta.json → settings.json["backup"].
    legacy_meta = legacy / "backup-meta.json"
    if legacy_meta.is_file():
        actions.extend(_fold_backup_meta(legacy_meta, settings_dest))

    # 4) claw → top level (active sandbox); caches → caches/.
    actions.extend(_move_dir(legacy, legacy / "claw", root / "claw", "workbench/claw", "claw"))
    for name in ("logs", "pet-cache", "marketplace-cache"):
        actions.extend(
            _move_dir(
                legacy,
                legacy / name,
                root / "caches" / name,
                f"workbench/{name}",
                f"caches/{name}",
            )
        )

    _rm_if_empty(legacy, actions, "workbench/")
    return actions


def _move_dir(
    legacy_root: Path, src: Path, dest: Path, src_label: str, dest_label: str
) -> list[str]:
    """Move ``src`` → ``dest`` when ``src`` exists and ``dest`` does not yet.

    When ``dest`` is already populated, quarantine the legacy copy under
    ``workbench/.migrated-dupes/`` rather than clobbering live data — so
    ``workbench/`` can still be emptied without losing the old tree.
    """
    if not src.is_dir():
        return []
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return [f"moved {src_label} → {dest_label}"]
    return _quarantine(legacy_root, src, src.name)


def _quarantine(legacy_root: Path, src: Path, name: str) -> list[str]:
    """Move a superseded legacy file/dir into ``workbench/.migrated-dupes/``."""
    quarantine = legacy_root / ".migrated-dupes"
    quarantine.mkdir(parents=True, exist_ok=True)
    q_dest = quarantine / name
    if q_dest.exists():
        q_dest = quarantine / f"{name}.{_unique_suffix()}"
    shutil.move(str(src), str(q_dest))
    rel = src.relative_to(legacy_root)
    return [f"quarantined superseded workbench/{rel} → workbench/.migrated-dupes/"]



def _fold_backup_meta(legacy_meta: Path, settings_dest: Path) -> list[str]:
    import json

    try:
        meta = json.loads(legacy_meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(meta, dict):
        legacy_meta.unlink(missing_ok=True)
        return []

    settings: dict = {}
    if settings_dest.is_file():
        try:
            loaded = json.loads(settings_dest.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except (OSError, json.JSONDecodeError):
            settings = {}
    if "backup" not in settings:
        settings["backup"] = {
            "directory": meta.get("directory"),
            "last_backup_at": meta.get("last_backup_at"),
            "last_backup_path": meta.get("last_backup_path"),
        }
        settings_dest.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    legacy_meta.unlink(missing_ok=True)
    return ["folded workbench/backup-meta.json → settings.json (backup)"]


def _unique_suffix() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _ensure_manifest(root: Path) -> list[str]:
    path = root / _MANIFEST_MARKER
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if "workflow-runs/" in text or "workbench/" in text:
            path.write_text(_DEFAULT_MANIFEST, encoding="utf-8")
            return [f"updated {_MANIFEST_MARKER} (workbench → flat layout)"]
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
paths_sandbox = ["claw/"]
retention = "archive_then_purge"
backup = "required"
notes = "threads/ is the source of truth; sessions/ is TUI legacy (current.json); claw/ holds active IM sandbox workspaces (not a cache)."

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
  "settings.json",
  "usage.json",
  "caches/",
  "runtime.token",
]
retention = "days_to_weeks"
backup = "skip"
notes = "GUI product state is flat (settings.json / usage.json); GUI caches under caches/. Electron userData is Chromium cache only."

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
