"""Export / import / manual backup for Workbench Data settings.

Bundle format is a zip with ``manifest.json`` plus optional directory trees.
Scopes:

* ``conversations`` — ``threads/`` (canonical) + ``sessions/`` (TUI legacy)
* ``settings`` — ``config.toml`` + ``mcp.json`` + ``settings.json``
  (may contain secrets / API keys)
* ``all`` — conversations + settings
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from deepseek_tui.config.paths import (
    settings_path,
    user_config_path,
    user_deepseek_dir,
    user_mcp_config_path,
    user_sessions_dir,
    user_threads_dir,
)
from deepseek_tui.utils import write_json_atomic

logger = logging.getLogger(__name__)

BUNDLE_FORMAT = "deepseek-data-export"
BUNDLE_VERSION = 1
ExportScope = Literal["conversations", "settings", "all"]
ImportMode = Literal["merge", "replace"]

_SCOPES: frozenset[str] = frozenset({"conversations", "settings", "all"})


_EMPTY_BACKUP_META = {"directory": None, "last_backup_at": None, "last_backup_path": None}


def _read_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def read_backup_meta() -> dict[str, Any]:
    """Backup bookkeeping now lives under ``settings.json`` → ``backup`` (à la ``.claude``)."""
    backup = _read_settings().get("backup")
    if not isinstance(backup, dict):
        return dict(_EMPTY_BACKUP_META)
    return {
        "directory": backup.get("directory"),
        "last_backup_at": backup.get("last_backup_at"),
        "last_backup_path": backup.get("last_backup_path"),
    }


def write_backup_meta(
    *,
    directory: str | None = None,
    last_backup_at: str | None = None,
    last_backup_path: str | None = None,
) -> dict[str, Any]:
    current = read_backup_meta()
    if directory is not None:
        current["directory"] = directory or None
    if last_backup_at is not None:
        current["last_backup_at"] = last_backup_at
    if last_backup_path is not None:
        current["last_backup_path"] = last_backup_path
    settings = _read_settings()
    settings["backup"] = current
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, settings)
    return current


def export_bundle(
    destination: Path,
    *,
    scope: ExportScope = "conversations",
    threads_dir: Path | None = None,
    sessions_dir: Path | None = None,
) -> dict[str, Any]:
    """Write a zip export to ``destination``. Returns a small report."""
    if scope not in _SCOPES:
        raise ValueError(f"unsupported export scope: {scope}")
    dest = Path(destination).expanduser()
    if dest.suffix.lower() != ".zip":
        dest = dest.with_suffix(".zip")
    dest.parent.mkdir(parents=True, exist_ok=True)

    threads_root = threads_dir or user_threads_dir()
    sessions_root = sessions_dir or user_sessions_dir()
    include_conversations = scope in ("conversations", "all")
    include_settings = scope in ("settings", "all")

    manifest: dict[str, Any] = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "scope": scope,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "includes": {
            "threads": include_conversations,
            "sessions": include_conversations,
            "config": include_settings,
            "mcp": include_settings,
            "workbench_settings": include_settings,
        },
    }

    tmp_zip = dest.with_suffix(dest.suffix + ".tmp")
    if tmp_zip.exists():
        tmp_zip.unlink()
    with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        bytes_written = 0
        files_written = 1
        if include_conversations:
            n, b = _zip_tree(zf, threads_root, arc_prefix="threads")
            files_written += n
            bytes_written += b
            n, b = _zip_tree(zf, sessions_root, arc_prefix="sessions")
            files_written += n
            bytes_written += b
        if include_settings:
            for label, path in (
                ("config.toml", user_config_path()),
                ("mcp.json", user_mcp_config_path()),
                ("settings.json", settings_path()),
            ):
                if path.is_file():
                    zf.write(path, arcname=label)
                    files_written += 1
                    bytes_written += path.stat().st_size

    tmp_zip.replace(dest)
    return {
        "path": str(dest),
        "scope": scope,
        "files": files_written,
        "bytes": dest.stat().st_size,
        "uncompressed_bytes": bytes_written,
    }


def import_bundle(
    source: Path,
    *,
    mode: ImportMode = "merge",
    threads_dir: Path | None = None,
    sessions_dir: Path | None = None,
    import_settings: bool = True,
) -> dict[str, Any]:
    """Import a zip export. ``merge`` skips colliding thread ids; ``replace`` clears first."""
    if mode not in ("merge", "replace"):
        raise ValueError(f"unsupported import mode: {mode}")
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"export file not found: {src}")

    threads_root = threads_dir or user_threads_dir()
    sessions_root = sessions_dir or user_sessions_dir()

    with tempfile.TemporaryDirectory(prefix="deepseek-import-") as tmp:
        tmp_root = Path(tmp)
        with zipfile.ZipFile(src, "r") as zf:
            _safe_extract(zf, tmp_root)
        manifest_path = tmp_root / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("invalid export: missing manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != BUNDLE_FORMAT:
            raise ValueError("invalid export: unknown format")
        version = int(manifest.get("version") or 0)
        if version > BUNDLE_VERSION:
            raise ValueError(f"export schema v{version} is newer than supported v{BUNDLE_VERSION}")

        includes = manifest.get("includes") or {}
        report: dict[str, Any] = {
            "mode": mode,
            "scope": manifest.get("scope"),
            "threads_imported": 0,
            "threads_skipped": 0,
            "sessions_restored": False,
            "settings_restored": [],
        }

        if mode == "replace" and includes.get("threads"):
            from deepseek_tui.server.data_inventory import clear_conversation_history
            from deepseek_tui.server.threads.store import RuntimeThreadStore
            from deepseek_tui.workspace.turn_checkpoints import TurnCheckpointStore

            store = RuntimeThreadStore(threads_root)
            checkpoints = TurnCheckpointStore(threads_root / "checkpoints")
            clear_conversation_history(
                store, checkpoints, sessions_dir=sessions_root, clear_sessions=True
            )

        bundle_threads = tmp_root / "threads"
        if includes.get("threads") and bundle_threads.is_dir():
            imported, skipped = _merge_threads_tree(bundle_threads, threads_root)
            report["threads_imported"] = imported
            report["threads_skipped"] = skipped

        bundle_sessions = tmp_root / "sessions"
        if includes.get("sessions") and bundle_sessions.is_dir():
            if mode == "replace" and sessions_root.exists():
                shutil.rmtree(sessions_root, ignore_errors=True)
            sessions_root.mkdir(parents=True, exist_ok=True)
            _copy_tree_merge(bundle_sessions, sessions_root, overwrite=(mode == "replace"))
            report["sessions_restored"] = True

        if import_settings:
            for arcnames, target, key in (
                (("config.toml",), user_config_path(), "config"),
                (("mcp.json",), user_mcp_config_path(), "mcp"),
                # New exports store settings.json flat; older ones under workbench/.
                (("settings.json", "workbench/settings.json"), settings_path(), "workbench_settings"),
            ):
                candidate = next(
                    (tmp_root / name for name in arcnames if (tmp_root / name).is_file()),
                    None,
                )
                if candidate is None:
                    continue
                # Older exports omit workbench_settings in includes — still restore
                # when the file is present in the zip.
                if includes and key in includes and not includes.get(key):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if mode == "merge" and target.is_file():
                    # Keep existing settings on merge; only replace on replace mode.
                    continue
                shutil.copy2(candidate, target)
                report["settings_restored"].append(target.name)

        return report


def create_backup(
    *,
    directory: str | Path | None = None,
    threads_dir: Path | None = None,
    sessions_dir: Path | None = None,
) -> dict[str, Any]:
    """Copy conversations into a timestamped folder under the backup directory."""
    meta = read_backup_meta()
    raw_dir = (directory or meta.get("directory") or "").strip()
    if not raw_dir:
        raise ValueError("backup directory is not set")
    backup_root = Path(raw_dir).expanduser()
    backup_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_root / f"deepseek-backup-{stamp}"
    target.mkdir(parents=False, exist_ok=False)

    threads_root = threads_dir or user_threads_dir()
    sessions_root = sessions_dir or user_sessions_dir()
    files = 0
    bytes_copied = 0
    if threads_root.exists():
        dest = target / "threads"
        shutil.copytree(threads_root, dest)
        files, bytes_copied = _count_tree(dest)
    if sessions_root.exists():
        dest = target / "sessions"
        shutil.copytree(sessions_root, dest)
        n, b = _count_tree(dest)
        files += n
        bytes_copied += b

    manifest = {
        "format": "deepseek-data-backup",
        "version": BUNDLE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "home": str(user_deepseek_dir()),
    }
    write_json_atomic(target / "manifest.json", manifest)
    at = datetime.now(timezone.utc).isoformat()
    write_backup_meta(
        directory=str(backup_root),
        last_backup_at=at,
        last_backup_path=str(target),
    )
    return {
        "path": str(target),
        "directory": str(backup_root),
        "files": files + 1,
        "bytes": bytes_copied,
        "last_backup_at": at,
    }


def _zip_tree(zf: zipfile.ZipFile, root: Path, *, arc_prefix: str) -> tuple[int, int]:
    if not root.exists():
        return 0, 0
    count = 0
    total = 0
    root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        zf.write(path, arcname=f"{arc_prefix}/{rel}")
        count += 1
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return count, total


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for info in zf.infolist():
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"unsafe path in archive: {name}")
        target = (dest / name).resolve()
        try:
            target.relative_to(dest)
        except ValueError as exc:
            raise ValueError(f"unsafe path in archive: {name}") from exc
    zf.extractall(dest)


def _merge_threads_tree(src: Path, dest: Path) -> tuple[int, int]:
    """Copy thread JSON trees; skip thread ids that already exist. Returns (imported, skipped)."""
    dest.mkdir(parents=True, exist_ok=True)
    src_threads = src / "threads"
    if not src_threads.is_dir():
        # Bundle may store the store root directly under threads/
        if (src / "state.json").is_file() or any(src.glob("*.json")):
            src_threads = src
        else:
            return 0, 0

    dest_threads = dest / "threads"
    dest_threads.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in dest_threads.glob("*.json")}
    imported = 0
    skipped = 0
    keep_ids: set[str] = set()
    for path in src_threads.glob("*.json"):
        tid = path.stem
        if tid in existing:
            skipped += 1
            continue
        shutil.copy2(path, dest_threads / path.name)
        keep_ids.add(tid)
        imported += 1

    # Copy turns/items/events/checkpoints that belong to imported threads only.
    # Turns reference thread_id inside JSON — filter by parsing when possible.
    _copy_related(src, dest, "turns", keep_ids, id_field="thread_id")
    _copy_related_items(src, dest, keep_ids)
    _copy_events(src, dest, keep_ids)
    _copy_checkpoints(src, dest, keep_ids)

    # state.json: keep destination next_seq high-water; bump if needed.
    _merge_state_json(src / "state.json", dest / "state.json")
    return imported, skipped


def _copy_related(
    src: Path, dest: Path, folder: str, keep_thread_ids: set[str], *, id_field: str
) -> None:
    src_dir = src / folder
    if not src_dir.is_dir() or not keep_thread_ids:
        return
    dest_dir = dest / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in src_dir.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(raw.get(id_field) or "") not in keep_thread_ids:
            continue
        target = dest_dir / path.name
        if target.exists():
            continue
        shutil.copy2(path, target)


def _copy_related_items(src: Path, dest: Path, keep_thread_ids: set[str]) -> None:
    """Copy items whose turn belongs to an imported thread."""
    src_turns = src / "turns"
    src_items = src / "items"
    if not src_items.is_dir() or not src_turns.is_dir() or not keep_thread_ids:
        return
    turn_ids: set[str] = set()
    for path in src_turns.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(raw.get("thread_id") or "") in keep_thread_ids:
            turn_ids.add(path.stem)
    dest_items = dest / "items"
    dest_items.mkdir(parents=True, exist_ok=True)
    for path in src_items.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(raw.get("turn_id") or "") not in turn_ids:
            continue
        target = dest_items / path.name
        if target.exists():
            continue
        shutil.copy2(path, target)


def _copy_events(src: Path, dest: Path, keep_thread_ids: set[str]) -> None:
    src_dir = src / "events"
    if not src_dir.is_dir() or not keep_thread_ids:
        return
    dest_dir = dest / "events"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in src_dir.glob("*.jsonl"):
        if path.stem not in keep_thread_ids:
            continue
        target = dest_dir / path.name
        if target.exists():
            continue
        shutil.copy2(path, target)


def _copy_checkpoints(src: Path, dest: Path, keep_thread_ids: set[str]) -> None:
    src_dir = src / "checkpoints"
    if not src_dir.is_dir() or not keep_thread_ids:
        return
    dest_dir = dest / "checkpoints"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in src_dir.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(raw.get("thread_id") or "") not in keep_thread_ids:
            continue
        target = dest_dir / path.name
        if target.exists():
            continue
        shutil.copy2(path, target)


def _merge_state_json(src: Path, dest: Path) -> None:
    if not src.is_file():
        return
    try:
        src_state = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    dest_state: dict[str, Any] = {"schema_version": 2, "next_seq": 1}
    if dest.is_file():
        try:
            dest_state = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    dest_state["next_seq"] = max(
        int(dest_state.get("next_seq") or 1),
        int(src_state.get("next_seq") or 1),
    )
    write_json_atomic(dest, dest_state)


def _copy_tree_merge(src: Path, dest: Path, *, overwrite: bool) -> None:
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        target = dest / rel
        if target.exists() and not overwrite:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _count_tree(root: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            files += 1
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return files, total
