"""One-shot migration of ``~/.deepseek`` into the lifecycle layout.

Safe to call repeatedly. Moves legacy directories/files into the L0–L5
structure documented in ``MANIFEST.toml`` / :mod:`deepseek_tui.config.paths`.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from deepseek_tui.config.paths import user_deepseek_dir
from deepseek_tui.utils import write_json_atomic, write_text_atomic

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
                actions.extend(
                    _quarantine(root, child, f"subagents-{child.name}")
                )
        _rm_if_empty(legacy_reg, actions, "subagents/")

    legacy_runs = root / "subagent-runs"
    if legacy_runs.is_dir():
        for child in list(legacy_runs.iterdir()):
            dest = runs / child.name
            if not dest.exists():
                shutil.move(str(child), str(dest))
                actions.append(f"moved {child.name} → agents/runs/")
            else:
                actions.extend(
                    _quarantine(root, child, f"subagent-runs-{child.name}")
                )
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
                    actions.extend(
                        _quarantine(root, child, f"plugin-host-{child.name}")
                    )
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
            actions.extend(
                _quarantine(root, child, f"automations-{child.name}")
            )
    _rm_if_empty(nested, actions, "automations/automations/")
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
    """Move a conflicting legacy file/dir aside instead of deleting it."""
    quarantine = legacy_root / ".migrated-dupes"
    quarantine.mkdir(parents=True, exist_ok=True)
    q_dest = quarantine / name
    suffix = 2
    while q_dest.exists():
        q_dest = quarantine / f"{name}.{suffix}"
        suffix += 1
    shutil.move(str(src), str(q_dest))
    rel = src.relative_to(legacy_root)
    return [f"quarantined conflicting {rel} → {q_dest.relative_to(legacy_root)}"]



def _fold_backup_meta(legacy_meta: Path, settings_dest: Path) -> list[str]:
    import json

    try:
        meta = json.loads(legacy_meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(meta, dict):
        return _quarantine(legacy_meta.parent, legacy_meta, "backup-meta.json")

    settings: dict = {}
    if settings_dest.is_file():
        try:
            loaded = json.loads(settings_dest.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                return _quarantine(
                    legacy_meta.parent, legacy_meta, "backup-meta.json"
                )
            settings = loaded
        except (OSError, json.JSONDecodeError):
            return _quarantine(legacy_meta.parent, legacy_meta, "backup-meta.json")
    if "backup" in settings:
        return _quarantine(legacy_meta.parent, legacy_meta, "backup-meta.json")

    settings["backup"] = meta
    write_json_atomic(settings_dest, settings)
    legacy_meta.unlink()
    return [
        "folded workbench/backup-meta.json → settings.json (backup)"
    ]


def _ensure_manifest(root: Path) -> list[str]:
    path = root / _MANIFEST_MARKER
    if path.is_file():
        # This file is documentation, not runtime state. Never overwrite a
        # user's customized retention/backup policy during startup migration.
        return []
    write_text_atomic(path, _DEFAULT_MANIFEST)
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
paths = ["config.toml", "AGENTS.md", "mcp.json"]
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
notes = "Canonical threads; legacy exports/recovery in sessions; active IM sandboxes in claw."

[layers.L3_jobs]
paths = [
  "tasks/",
  "automations/",
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
unit_secondary = ["tasks", "automations/runs"]
"""
