"""Portable, immutable single-thread snapshots. Never carry machine permissions."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field

from deepseek_tui.config.paths import user_media_dir
from deepseek_tui.server.threads.items import _ordered_turn_items
from deepseek_tui.server.threads.models import (
    RuntimeTurnStatus,
    ThreadRecord,
    TurnItemRecord,
    TurnRecord,
)
from deepseek_tui.server.threads.store import RuntimeThreadStore

MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024


class SnapshotFile(BaseModel):
    path: str
    content: str | None = None  # base64; None means deletion
    executable: bool = False


class ProjectSnapshot(BaseModel):
    commit: str
    files: list[SnapshotFile] = Field(default_factory=list)


class SessionSnapshot(BaseModel):
    format: Literal["deepseek-session-share"] = "deepseek-session-share"
    version: Literal[1] = 1
    created_at: datetime
    title: str
    source_thread_id: str
    source_workspace: str
    model: str
    provider: str
    mode: str
    goal: dict[str, Any] | None = None
    goal_queue: list[dict[str, Any]] = Field(default_factory=list)
    turns: list[TurnRecord]
    items: list[TurnItemRecord]
    media: dict[str, str] = Field(default_factory=dict)
    project: ProjectSnapshot | None = None


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip() or "Git operation failed")
    return result.stdout


def safe_path(root: Path, name: str) -> Path:
    parts = PurePosixPath(name).parts
    if (
        not parts
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or any(p in {".", ".."} or p.lower() == ".git" for p in parts)
    ):
        raise ValueError(f"Unsafe snapshot path: {name}")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Snapshot cannot traverse a symlink: {name}")
    return path


def capture_project(root: Path) -> ProjectSnapshot:
    top = Path(git(root, "rev-parse", "--show-toplevel").decode().strip())
    if top.resolve() != root.resolve():
        raise ValueError("Select the Git repository root before including project changes")
    commit = git(root, "rev-parse", "HEAD").decode().strip()
    changed = git(root, "diff", "--no-renames", "--name-only", "-z", "HEAD", "--").split(b"\0")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    files = []
    size = 0
    for raw in sorted(set(changed + untracked) - {b""}):
        name = raw.decode("utf-8")
        path = safe_path(root, name)
        if path.is_dir() and (path / ".git").exists():
            raise ValueError(f"Submodules cannot be shared: {name}")
        content = None
        if path.is_file():
            size += path.stat().st_size
            if size > MAX_SNAPSHOT_BYTES // 2:
                raise ValueError("Project changes exceed 16 MiB")
            content = base64.b64encode(path.read_bytes()).decode()
        files.append(
            SnapshotFile(
                path=name,
                content=content,
                executable=path.is_file() and bool(path.stat().st_mode & 0o111),
            )
        )
    return ProjectSnapshot(commit=commit, files=files)


def build_snapshot(
    store: RuntimeThreadStore, thread: ThreadRecord, *, include_project: bool = False
) -> SessionSnapshot:
    turns = store.list_turns_for_thread(thread.id)
    if not turns:
        raise ValueError("There is no conversation to share")
    if any(t.status in {RuntimeTurnStatus.QUEUED, RuntimeTurnStatus.IN_PROGRESS} for t in turns):
        raise ValueError("Wait for the current turn to finish before sharing")
    items = []
    for turn in turns:
        ordered = _ordered_turn_items(store, turn)
        turn.item_ids = [item.id for item in ordered]
        items.extend(ordered)
    snapshot = SessionSnapshot(
        created_at=datetime.now(timezone.utc),
        title=thread.title or "Shared conversation",
        source_thread_id=thread.id,
        source_workspace=thread.worktree_path or thread.workspace,
        model=thread.model,
        provider=thread.provider,
        mode=thread.mode,
        goal=thread.goal,
        goal_queue=thread.goal_queue,
        turns=turns,
        items=items,
        project=capture_project(Path(thread.worktree_path or thread.workspace))
        if include_project
        else None,
    )
    asset_ids = re.findall(r'"asset_id"\s*:\s*"([a-f0-9]{64})"', snapshot.model_dump_json())
    for asset_id in set(asset_ids):
        path = user_media_dir() / asset_id
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing image attachment: {asset_id}")
        snapshot.media[asset_id] = base64.b64encode(path.read_bytes()).decode()
    validate_snapshot(snapshot)
    return snapshot


def validate_snapshot(snapshot: SessionSnapshot) -> None:
    if len(snapshot.model_dump_json().encode()) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Session snapshot exceeds 32 MiB")
    turns = {t.id: t for t in snapshot.turns}
    items = {i.id: i for i in snapshot.items}
    if not turns or len(turns) != len(snapshot.turns) or len(items) != len(snapshot.items):
        raise ValueError("Invalid or duplicate conversation records")
    if any(
        t.thread_id != snapshot.source_thread_id
        or t.status in {RuntimeTurnStatus.QUEUED, RuntimeTurnStatus.IN_PROGRESS}
        for t in snapshot.turns
    ):
        raise ValueError("Snapshot contains an unfinished or unrelated turn")
    for turn in snapshot.turns:
        if len(set(turn.item_ids)) != len(turn.item_ids) or any(
            key not in items or items[key].turn_id != turn.id for key in turn.item_ids
        ):
            raise ValueError("Invalid turn item references")
    if any(i.turn_id not in turns for i in snapshot.items):
        raise ValueError("Invalid item turn reference")
    for asset_id, content in snapshot.media.items():
        data = base64.b64decode(content, validate=True)
        if hashlib.sha256(data).hexdigest() != asset_id:
            raise ValueError("Image attachment checksum mismatch")
    references = set(
        re.findall(
            r'"asset_id"\s*:\s*"([a-f0-9]{64})"',
            json.dumps([i.model_dump(mode="json") for i in snapshot.items]),
        )
    )
    if references - snapshot.media.keys():
        raise ValueError("Snapshot is missing image attachments")
    if snapshot.project:
        if not re.fullmatch(r"[0-9a-f]{40,64}", snapshot.project.commit):
            raise ValueError("Invalid project commit")
        names = set()
        for file in snapshot.project.files:
            # Validate lexical paths without consulting the recipient filesystem.
            normalized = safe_path(Path("/nonexistent-snapshot-validation"), file.path)
            if normalized in names:
                raise ValueError("Duplicate project path")
            names.add(normalized)
            if file.content is not None:
                base64.b64decode(file.content, validate=True)


def restore_project(project: ProjectSnapshot, repository: Path, destination: Path) -> None:
    """Use a fresh detached worktree, leaving the selected checkout untouched."""
    git(repository, "cat-file", "-e", f"{project.commit}^{{commit}}")
    git(repository, "worktree", "add", "--detach", str(destination), project.commit)
    try:
        # Delete descendants first so directory/file replacements can be recreated.
        deletions = sorted(
            (f for f in project.files if f.content is None),
            key=lambda f: len(PurePosixPath(f.path).parts),
            reverse=True,
        )
        for file in deletions:
            path = safe_path(destination, file.path)
            path.unlink(missing_ok=True)
            parent = path.parent
            while parent != destination:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        for file in project.files:
            if file.content is None:
                continue
            path = safe_path(destination, file.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(file.content, validate=True))
            path.chmod(0o755 if file.executable else 0o644)
    except Exception:
        git(repository, "worktree", "remove", "--force", str(destination))
        raise


def import_snapshot(
    store: RuntimeThreadStore, snapshot: SessionSnapshot, workspace: Path, share_id: str
) -> ThreadRecord:
    validate_snapshot(snapshot)
    from deepseek_tui.media import import_image

    for content in snapshot.media.values():
        import_image(base64.b64decode(content, validate=True))
    now = datetime.now(timezone.utc)
    thread = ThreadRecord(
        id=f"thr_{uuid.uuid4().hex}",
        created_at=now,
        updated_at=now,
        title=snapshot.title,
        workspace=str(workspace),
        model=snapshot.model,
        provider=snapshot.provider,
        mode=snapshot.mode,
        goal=snapshot.goal,
        goal_queue=snapshot.goal_queue,
        source_share_id=share_id,
        source_workspace=snapshot.source_workspace,
    )
    turn_ids = {t.id: f"turn_{uuid.uuid4().hex}" for t in snapshot.turns}
    item_ids = {i.id: f"item_{uuid.uuid4().hex}" for i in snapshot.items}
    try:
        for item in snapshot.items:
            store.save_item(
                item.model_copy(update={"id": item_ids[item.id], "turn_id": turn_ids[item.turn_id]})
            )
        for turn in snapshot.turns:
            store.save_turn(
                turn.model_copy(
                    update={
                        "id": turn_ids[turn.id],
                        "thread_id": thread.id,
                        "item_ids": [item_ids[key] for key in turn.item_ids],
                    }
                )
            )
        thread.latest_turn_id = turn_ids[snapshot.turns[-1].id]
        store.save_thread(thread)
    except Exception:
        for key in item_ids.values():
            store.delete_item(key)
        for key in turn_ids.values():
            store.delete_turn(key)
        store.delete_thread(thread.id)
        raise
    return thread
