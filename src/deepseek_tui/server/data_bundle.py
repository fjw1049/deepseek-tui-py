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
import os
import re
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from deepseek_tui.config.paths import (
    settings_path,
    user_config_path,
    user_deepseek_dir,
    user_mcp_config_path,
    user_media_dir,
    user_sessions_dir,
    user_threads_dir,
)
from deepseek_tui.utils import read_json_or_none, write_json_atomic

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
    raw = read_json_or_none(path)
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
    from deepseek_tui.config.layout import user_home_lease

    with user_home_lease():
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
            "media": include_conversations,
            "config": include_settings,
            "mcp": include_settings,
            "workbench_settings": include_settings,
        },
    }

    for root in (threads_root, sessions_root):
        if include_conversations and dest.resolve().is_relative_to(root.resolve()):
            raise ValueError("Export destination must be outside conversation storage")
    fd, name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    os.close(fd)
    tmp_zip = Path(name)
    try:
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            bytes_written = 0
            files_written = 1
            if include_conversations:
                n, b = _zip_tree(zf, threads_root, arc_prefix="threads")
                files_written += n
                bytes_written += b
                for asset in _referenced_media(threads_root, sessions_root):
                    zf.write(asset, arcname=f"media/{asset.name}")
                    files_written += 1
                    bytes_written += asset.stat().st_size
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
                        if path.is_symlink():
                            raise ValueError(f"Cannot export symlink: {path}")
                        zf.write(path, arcname=label)
                        files_written += 1
                        bytes_written += path.stat().st_size

        tmp_zip.replace(dest)
    finally:
        tmp_zip.unlink(missing_ok=True)
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
        _validate_bundle(tmp_root, includes)
        report: dict[str, Any] = {
            "mode": mode,
            "scope": manifest.get("scope"),
            "threads_imported": 0,
            "threads_skipped": 0,
            "sessions_restored": False,
            "settings_restored": [],
        }

        roots = []
        if includes.get("threads"):
            roots.append(threads_root)
        if includes.get("sessions") or (mode == "replace" and includes.get("threads")):
            roots.append(sessions_root)
        if import_settings:
            roots.extend((user_config_path(), user_mcp_config_path(), settings_path()))
        from deepseek_tui.workspace.project_lease import FileLease, ThreadLease

        lease = FileLease(threads_root.parent / f".{threads_root.name}.events.lock")
        lease.acquire_blocking()
        thread_leases = []
        try:
            # A live engine owns its thread across all record writes. Do not
            # replace that history while another runtime is still using it.
            if includes.get("threads"):
                for path in sorted((threads_root / "threads").glob("*.json")):
                    thread_lease = ThreadLease(path.stem)
                    if not thread_lease.acquire_blocking(nonblocking=True):
                        raise ValueError(f"Cannot import while thread is active: {path.stem}")
                    thread_leases.append(thread_lease)
            with _staged_import(roots) as targets:
                threads_root = targets.get(threads_root, threads_root)
                sessions_root = targets.get(sessions_root, sessions_root)
                if includes.get("media"):
                    import hashlib

                    from deepseek_tui.media import MAX_IMAGE_BYTES, import_image

                    for asset in (tmp_root / "media").glob("*"):
                        if not asset.is_file() or asset.is_symlink():
                            raise ValueError("Invalid image asset in conversation bundle")
                        with asset.open("rb") as stream:
                            data = stream.read(MAX_IMAGE_BYTES + 1)
                        if hashlib.sha256(data).hexdigest() != asset.name:
                            raise ValueError("Image asset hash mismatch in conversation bundle")
                        import_image(data)

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
                    _validate_bundle(tmp_root, includes, threads_root=threads_root)
                    from deepseek_tui.server.threads.store import RuntimeThreadStore

                    RuntimeThreadStore(threads_root)  # Recover imported legacy sequence high-water.

                bundle_sessions = tmp_root / "sessions"
                if includes.get("sessions") and bundle_sessions.is_dir():
                    if mode == "replace" and sessions_root.exists():
                        shutil.rmtree(sessions_root, ignore_errors=True)
                    sessions_root.mkdir(parents=True, exist_ok=True)
                    _copy_tree_merge(bundle_sessions, sessions_root, overwrite=(mode == "replace"))
                    report["sessions_restored"] = True

                if import_settings:
                    for arcnames, target, key in (
                        (("config.toml",), targets[user_config_path()], "config"),
                        (("mcp.json",), targets[user_mcp_config_path()], "mcp"),
                        # New exports store settings.json flat; older ones under workbench/.
                        (
                            ("settings.json", "workbench/settings.json"),
                            targets[settings_path()],
                            "workbench_settings",
                        ),
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

        finally:
            for thread_lease in reversed(thread_leases):
                thread_lease.release()
            lease.release()

        return report


def create_backup(
    *,
    directory: str | Path | None = None,
    threads_dir: Path | None = None,
    sessions_dir: Path | None = None,
) -> dict[str, Any]:
    """Copy conversations into a timestamped folder under the backup directory."""
    meta = read_backup_meta()
    raw_dir = str(directory or meta.get("directory") or "").strip()
    if not raw_dir:
        raise ValueError("backup directory is not set")
    backup_root = Path(raw_dir).expanduser()
    backup_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_root / f"deepseek-backup-{stamp}"
    target.mkdir(parents=False, exist_ok=False)

    threads_root = threads_dir or user_threads_dir()
    sessions_root = sessions_dir or user_sessions_dir()
    for root in (threads_root, sessions_root):
        _reject_symlinks(root)
        if target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Backup destination must be outside conversation storage")
    files = 0
    bytes_copied = 0
    if threads_root.exists():
        dest = target / "threads"
        shutil.copytree(threads_root, dest)
        files, bytes_copied = _count_tree(dest)
    for asset in _referenced_media(threads_root, sessions_root):
        dest = target / "media" / asset.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset, dest)
        files += 1
        bytes_copied += asset.stat().st_size
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


def _referenced_media(*roots: Path) -> list[Path]:
    """Export only assets referenced by the exported conversations, never orphaned images."""
    asset_ids: set[str] = set()
    pattern = re.compile(rb'"asset_id"\s*:\s*"([a-f0-9]{64})"')
    for root in roots:
        for record in root.rglob("*.json"):
            if record.is_file() and not record.is_symlink():
                asset_ids.update(
                    value.decode("ascii") for value in pattern.findall(record.read_bytes())
                )
    assets = [user_media_dir() / asset_id for asset_id in sorted(asset_ids)]
    for asset in assets:
        if not asset.is_file() or asset.is_symlink():
            raise ValueError(f"Cannot export conversation: missing image {asset.name}")
    return assets


def _zip_tree(zf: zipfile.ZipFile, root: Path, *, arc_prefix: str) -> tuple[int, int]:
    _reject_symlinks(root)
    zf.writestr(f"{arc_prefix}/", b"")
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


# Limits apply to actual streamed bytes as well as archive metadata.
MAX_ARCHIVE_FILES = 100_000
MAX_ARCHIVE_MEMBER_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_FILES:
        raise ValueError("Archive contains too many entries")
    names = set()
    total = 0
    for info in infos:
        name = info.filename
        parts = Path(name).parts
        if (
            not name
            or name.startswith("/")
            or ".." in parts
            or "\\" in name
            or ":" in name
            or stat.S_ISLNK(info.external_attr >> 16)
        ):
            raise ValueError(f"unsafe path in archive: {name}")
        canonical = str(Path(name))
        if canonical in names:
            raise ValueError(f"duplicate archive path: {name}")
        names.add(canonical)
        total += info.file_size
        if info.file_size > MAX_ARCHIVE_MEMBER_BYTES or total > MAX_ARCHIVE_BYTES:
            raise ValueError("Archive exceeds extraction size limit")
    total = 0
    for info in infos:
        target = dest / info.filename
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        member_bytes = 0
        with zf.open(info) as source, target.open("xb") as output:
            while chunk := source.read(1024 * 1024):
                member_bytes += len(chunk)
                total += len(chunk)
                if member_bytes > MAX_ARCHIVE_MEMBER_BYTES or total > MAX_ARCHIVE_BYTES:
                    raise ValueError("Archive exceeds extraction size limit")
                output.write(chunk)


def _reject_symlinks(root: Path) -> None:
    for path in (root, *root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Cannot copy symlink: {path}")
        if path.exists() and not path.is_file() and not path.is_dir():
            raise ValueError(f"Cannot copy special file: {path}")


@contextmanager
def _staged_import(roots: list[Path]) -> Iterator[dict[Path, Path]]:
    """Prepare complete replacements, then publish with rollback on I/O failure.

    Backups deliberately survive if rollback itself fails; never discard the only
    remaining copy of user data. This is not a power-loss transaction.
    """
    staging = {}
    containers = []
    published = []
    preserve_backups = False
    try:
        for target in dict.fromkeys(roots):
            _reject_symlinks(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            container = Path(tempfile.mkdtemp(prefix=".deepseek-import-", dir=target.parent))
            containers.append(container)
            staged = container / target.name
            if target.is_dir():
                shutil.copytree(target, staged)
            elif target.is_file():
                shutil.copy2(target, staged)
            staging[target] = staged
        yield staging
        try:
            for target, staged in staging.items():
                if not staged.exists():
                    continue
                backup = staged.with_name(f"{staged.name}.previous")
                existed = target.exists()
                if existed:
                    target.rename(backup)
                published.append((target, backup, existed))
                staged.rename(target)
        except BaseException:
            for target, backup, existed in reversed(published):
                try:
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink(missing_ok=True)
                    if existed:
                        backup.rename(target)
                except OSError:
                    preserve_backups = True
                    logger.exception("Import rollback failed; recover backup from %s", backup)
            raise
    finally:
        if not preserve_backups:
            for container in containers:
                shutil.rmtree(container, ignore_errors=True)


def _validate_bundle(
    root: Path, includes: dict[str, Any], *, threads_root: Path | None = None
) -> None:
    from deepseek_tui.server.threads.models import (
        CURRENT_RUNTIME_SCHEMA_VERSION,
        RuntimeEventRecord,
        RuntimeStoreState,
        ThreadRecord,
        TurnItemRecord,
        TurnRecord,
    )
    from deepseek_tui.server.threads.store import validate_record_id

    for folder in ("threads", "sessions"):
        if includes.get(folder) and not (root / folder).is_dir():
            raise ValueError(f"invalid export: missing {folder} directory")
    threads_root = threads_root or root / "threads"
    records = {}
    for folder, model in (
        ("threads", ThreadRecord),
        ("turns", TurnRecord),
        ("items", TurnItemRecord),
    ):
        records[folder] = {}
        for path in (threads_root / folder).glob("*.json"):
            record = model.model_validate_json(path.read_text(encoding="utf-8"))
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION or record.id != path.stem:
                raise ValueError(f"Invalid record identity/schema: {path.name}")
            validate_record_id(record.id)
            records[folder][record.id] = record
    threads, turns, items = (records[k] for k in ("threads", "turns", "items"))
    for turn in turns.values():
        if turn.thread_id not in threads:
            raise ValueError("Turn refers to missing thread")
        for item_id in turn.item_ids:
            if item_id not in items or items[item_id].turn_id != turn.id:
                raise ValueError("Turn refers to missing or foreign item")
    for item in items.values():
        if item.turn_id not in turns:
            raise ValueError("Item refers to missing turn")
    for thread in threads.values():
        if thread.latest_turn_id and (
            thread.latest_turn_id not in turns
            or turns[thread.latest_turn_id].thread_id != thread.id
        ):
            raise ValueError("Thread refers to missing or foreign latest turn")
    for path in (threads_root / "events").glob("*.jsonl"):
        if path.stem not in threads:
            raise ValueError("Events refer to missing thread")
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                event = RuntimeEventRecord.model_validate_json(line)
                if event.thread_id != path.stem:
                    raise ValueError("Event thread does not match filename")
    from deepseek_tui.workspace.turn_checkpoints import TurnCheckpoint

    for path in (threads_root / "checkpoints").glob("*.json"):
        checkpoint = TurnCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))
        validate_record_id(checkpoint.turn_id)
        if checkpoint.turn_id != path.stem or checkpoint.thread_id not in threads:
            raise ValueError("Invalid checkpoint identity or owner")
    state = threads_root / "state.json"
    if state.exists():
        RuntimeStoreState.model_validate_json(state.read_text(encoding="utf-8"))
    for path in (root / "sessions").glob("*.json"):
        if not isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
            raise ValueError("Invalid session record")
    for path in (root / "mcp.json", root / "settings.json", root / "workbench/settings.json"):
        if path.exists() and not isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
            raise ValueError("Invalid settings record")
    config = root / "config.toml"
    if config.exists():
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        tomllib.loads(config.read_text(encoding="utf-8"))


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
        raw = read_json_or_none(path)
        if raw is None:
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
        raw = read_json_or_none(path)
        if raw is None:
            continue
        if str(raw.get("thread_id") or "") in keep_thread_ids:
            turn_ids.add(path.stem)
    dest_items = dest / "items"
    dest_items.mkdir(parents=True, exist_ok=True)
    for path in src_items.glob("*.json"):
        raw = read_json_or_none(path)
        if raw is None:
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
        raw = read_json_or_none(path)
        if raw is None:
            continue
        if str(raw.get("thread_id") or "") not in keep_thread_ids:
            continue
        target = dest_dir / path.name
        if target.exists():
            continue
        shutil.copy2(path, target)
        sidecars = src_dir / f"{path.stem}.raw"
        if sidecars.is_dir():
            shutil.copytree(sidecars, dest_dir / sidecars.name)


def _merge_state_json(src: Path, dest: Path) -> None:
    if not src.is_file():
        return
    src_state = read_json_or_none(src)
    if src_state is None:
        return
    dest_state: dict[str, Any] = {"schema_version": 2, "next_seq": 1}
    if dest.is_file():
        parsed_dest = read_json_or_none(dest)
        if parsed_dest is not None:
            dest_state = parsed_dest
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
