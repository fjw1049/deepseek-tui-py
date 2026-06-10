"""Session manager — multi-session persistence, resume, fork, archive.

Mirrors Rust ``crates/tui/src/core/session.rs`` (152 lines) for the Session
data model, and Rust ``crates/state/src/lib.rs`` session_index + ThreadMetadata
(~950 lines) for the persistence layer.

Responsibilities:
- Create / restore / fork / archive sessions via StateStore (SQLite)
- Maintain a JSONL session index file for fast name→id lookups
- Provide the in-memory Session object used by the Engine

Timestamp convention: all *_at fields are int (Unix epoch seconds), matching
Rust's i64 timestamps. This fixes the State timestamp incompatibility
(SUMMARY.md Phase A row 1).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from deepseek_tui.state.database import Database

# --- enums (Rust parity: state/lib.rs lines 12–31) --------------------------


class ThreadStatus(str, Enum):
    RUNNING = "running"
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    ARCHIVED = "archived"


class SessionSource(str, Enum):
    INTERACTIVE = "interactive"
    RESUME = "resume"
    FORK = "fork"
    API = "api"
    UNKNOWN = "unknown"


# --- expanded ThreadMetadata (Rust 19 fields → Python parity) ---------------


@dataclass(slots=True)
class ThreadMetadata:
    """Full thread metadata — mirrors Rust ``ThreadMetadata`` (state/lib.rs:33-56)."""

    id: str
    preview: str
    model_provider: str
    cwd: str
    cli_version: str
    source: SessionSource
    status: ThreadStatus
    created_at: int
    updated_at: int
    rollout_path: str | None = None
    ephemeral: bool = False
    path: str | None = None
    name: str | None = None
    sandbox_policy: str | None = None
    approval_mode: str | None = None
    archived: bool = False
    archived_at: int | None = None
    git_sha: str | None = None
    git_branch: str | None = None
    git_origin_url: str | None = None
    memory_mode: str | None = None


# --- Session in-memory model (Rust session.rs) -----------------------------


@dataclass(slots=True)
class SessionUsage:
    """Cumulative usage statistics — mirrors Rust ``SessionUsage``."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, usage: dict[str, Any]) -> None:
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        self.cache_creation_input_tokens += usage.get("prompt_cache_miss_tokens", 0)
        self.cache_read_input_tokens += usage.get("prompt_cache_hit_tokens", 0)


@dataclass(slots=True)
class Session:
    """In-memory session state — mirrors Rust ``Session`` (session.rs:14-73)."""

    id: str
    model: str
    workspace: Path
    allow_shell: bool
    trust_mode: bool
    auto_approve: bool = False
    reasoning_effort: str | None = None
    system_prompt: str | None = None
    compaction_summary_prompt: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    total_usage: SessionUsage = field(default_factory=SessionUsage)
    notes_path: Path = field(default_factory=lambda: Path(".deepseek/notes.txt"))
    mcp_config_path: Path = field(default_factory=lambda: Path(".deepseek/mcp.json"))
    project_context: dict[str, Any] | None = None
    cycle_count: int = 0
    current_cycle_started: int = field(default_factory=lambda: _epoch_now())
    cycle_briefings: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def new(
        model: str,
        workspace: Path,
        allow_shell: bool,
        trust_mode: bool,
        notes_path: Path | None = None,
        mcp_config_path: Path | None = None,
    ) -> Session:
        return Session(
            id=uuid.uuid4().hex,
            model=model,
            workspace=workspace,
            allow_shell=allow_shell,
            trust_mode=trust_mode,
            notes_path=notes_path or Path(".deepseek/notes.txt"),
            mcp_config_path=mcp_config_path or Path(".deepseek/mcp.json"),
        )

    def add_message(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


# --- session index (JSONL append file) --------------------------------------


@dataclass(slots=True)
class SessionIndexEntry:
    """One line in session_index.jsonl — mirrors Rust ``SessionIndexEntry``."""

    thread_id: str
    thread_name: str | None
    updated_at: int
    rollout_path: str | None = None


class SessionIndex:
    """JSONL-based session name index — mirrors Rust ``append_thread_name``."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: SessionIndexEntry) -> None:
        line = json.dumps(
            {
                "thread_id": entry.thread_id,
                "thread_name": entry.thread_name,
                "updated_at": entry.updated_at,
                "rollout_path": entry.rollout_path,
            },
            ensure_ascii=False,
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_map(self) -> dict[str, SessionIndexEntry]:
        if not self._path.exists():
            return {}
        latest: dict[str, SessionIndexEntry] = {}
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            # A single corrupt line must not take down the whole index.
            try:
                data = json.loads(line)
                latest[data["thread_id"]] = SessionIndexEntry(
                    thread_id=data["thread_id"],
                    thread_name=data.get("thread_name"),
                    updated_at=data.get("updated_at", 0),
                    rollout_path=data.get("rollout_path"),
                )
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return latest

    def find_name(self, thread_id: str) -> str | None:
        entries = self.load_map()
        entry = entries.get(thread_id)
        return entry.thread_name if entry else None

    def find_path_by_name(self, name: str) -> str | None:
        entries = self.load_map()
        matched = [
            e
            for e in entries.values()
            if e.thread_name and e.thread_name.lower() == name.lower()
        ]
        if not matched:
            return None
        best = max(matched, key=lambda e: e.updated_at)
        return best.rollout_path


# --- SessionManager (orchestration layer) -----------------------------------


class SessionManager:
    """Multi-session lifecycle manager.

    Wraps Database + SessionIndex to provide:
    - create_session → Session + ThreadMetadata persisted
    - resume_session → reload from DB
    - fork_session → clone thread + fresh session
    - archive / unarchive / delete
    - list sessions with filtering
    - touch (update updated_at)

    Mirrors the combined behavior of Rust StateStore session methods +
    the TUI's session handling (~1,339 LOC across state + session + commands).
    """

    def __init__(self, database: Database, index_path: Path | None = None) -> None:
        self._db = database
        db_parent = database.path.parent
        self._index = SessionIndex(
            index_path or db_parent / "session_index.jsonl"
        )

    async def create_session(
        self,
        model: str,
        workspace: Path,
        *,
        allow_shell: bool = False,
        trust_mode: bool = False,
        source: SessionSource = SessionSource.INTERACTIVE,
        name: str | None = None,
        sandbox_policy: str | None = None,
        approval_mode: str | None = None,
    ) -> tuple[Session, ThreadMetadata]:
        """Create a new session and persist its thread metadata."""
        session = Session.new(
            model=model, workspace=workspace, allow_shell=allow_shell, trust_mode=trust_mode
        )
        now = _epoch_now()
        meta = ThreadMetadata(
            id=session.id,
            preview="",
            model_provider=model,
            cwd=str(workspace),
            cli_version=_cli_version(),
            source=source,
            status=ThreadStatus.RUNNING,
            created_at=now,
            updated_at=now,
            name=name,
            sandbox_policy=sandbox_policy,
            approval_mode=approval_mode,
        )
        await self._upsert_thread(meta)
        self._index.append(
            SessionIndexEntry(
                thread_id=meta.id,
                thread_name=name,
                updated_at=now,
            )
        )
        return session, meta

    async def resume_session(self, thread_id: str) -> ThreadMetadata | None:
        """Load thread metadata for resuming a session."""
        meta = await self._get_thread(thread_id)
        if meta is None:
            return None
        now = _epoch_now()
        meta.status = ThreadStatus.RUNNING
        meta.updated_at = now
        meta.source = SessionSource.RESUME
        await self._upsert_thread(meta)
        return meta

    async def fork_session(self, source_thread_id: str) -> ThreadMetadata | None:
        """Fork a session — creates a new thread based on an existing one."""
        source = await self._get_thread(source_thread_id)
        if source is None:
            return None
        now = _epoch_now()
        forked = ThreadMetadata(
            id=uuid.uuid4().hex,
            preview=source.preview,
            model_provider=source.model_provider,
            cwd=source.cwd,
            cli_version=_cli_version(),
            source=SessionSource.FORK,
            status=ThreadStatus.RUNNING,
            created_at=now,
            updated_at=now,
            name=None,
            sandbox_policy=source.sandbox_policy,
            approval_mode=source.approval_mode,
        )
        await self._upsert_thread(forked)
        self._index.append(
            SessionIndexEntry(thread_id=forked.id, thread_name=None, updated_at=now)
        )
        return forked

    async def archive(self, thread_id: str) -> None:
        """Archive a session."""
        conn = await self._db.connect()
        now = _epoch_now()
        await conn.execute(
            "UPDATE threads SET archived = 1, archived_at = ?, status = ? WHERE id = ?",
            (now, ThreadStatus.ARCHIVED.value, thread_id),
        )
        await conn.commit()

    async def unarchive(self, thread_id: str) -> None:
        """Unarchive a session — restore status (archive() set it to 'archived')."""
        conn = await self._db.connect()
        await conn.execute(
            "UPDATE threads SET archived = 0, archived_at = NULL, status = ? WHERE id = ?",
            (ThreadStatus.IDLE.value, thread_id),
        )
        await conn.commit()

    async def delete(self, thread_id: str) -> None:
        """Delete a session and all its data (CASCADE)."""
        conn = await self._db.connect()
        await conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        await conn.commit()

    async def touch(self, thread_id: str, preview: str | None = None) -> None:
        """Update the updated_at timestamp and optionally the preview."""
        conn = await self._db.connect()
        now = _epoch_now()
        if preview is not None:
            await conn.execute(
                "UPDATE threads SET updated_at = ?, preview = ? WHERE id = ?",
                (now, preview, thread_id),
            )
        else:
            await conn.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (now, thread_id),
            )
        await conn.commit()

    async def set_name(self, thread_id: str, name: str) -> None:
        """Set / update the thread display name."""
        conn = await self._db.connect()
        now = _epoch_now()
        await conn.execute(
            "UPDATE threads SET title = ?, updated_at = ? WHERE id = ?",
            (name, now, thread_id),
        )
        await conn.commit()
        self._index.append(
            SessionIndexEntry(thread_id=thread_id, thread_name=name, updated_at=now)
        )

    async def list_sessions(
        self,
        *,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[ThreadMetadata]:
        """List sessions ordered by updated_at DESC."""
        conn = await self._db.connect()
        if include_archived:
            sql = (
                "SELECT id, preview, model_provider, cwd, cli_version, source, "
                "status, created_at, updated_at, rollout_path, ephemeral, path, "
                "title, sandbox_policy, approval_mode, archived, archived_at, "
                "git_sha, git_branch, git_origin_url, memory_mode "
                "FROM threads ORDER BY updated_at DESC LIMIT ?"
            )
        else:
            sql = (
                "SELECT id, preview, model_provider, cwd, cli_version, source, "
                "status, created_at, updated_at, rollout_path, ephemeral, path, "
                "title, sandbox_policy, approval_mode, archived, archived_at, "
                "git_sha, git_branch, git_origin_url, memory_mode "
                "FROM threads WHERE archived = 0 ORDER BY updated_at DESC LIMIT ?"
            )
        cursor = await conn.execute(sql, (limit,))
        rows = await cursor.fetchall()
        return [_row_to_thread_metadata(dict(row)) for row in rows]

    async def get_session(self, thread_id: str) -> ThreadMetadata | None:
        return await self._get_thread(thread_id)

    def find_name(self, thread_id: str) -> str | None:
        return self._index.find_name(thread_id)

    def find_path_by_name(self, name: str) -> str | None:
        return self._index.find_path_by_name(name)

    # --- internal -------------------------------------------------------

    async def _upsert_thread(self, meta: ThreadMetadata) -> None:
        conn = await self._db.connect()
        await conn.execute(
            """
            INSERT INTO threads (
                id, rollout_path, preview, ephemeral, model_provider, created_at,
                updated_at, status, path, cwd, cli_version, source, title,
                sandbox_policy, approval_mode, archived, archived_at,
                git_sha, git_branch, git_origin_url, memory_mode
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            ON CONFLICT(id) DO UPDATE SET
                rollout_path=excluded.rollout_path,
                preview=excluded.preview,
                ephemeral=excluded.ephemeral,
                model_provider=excluded.model_provider,
                updated_at=excluded.updated_at,
                status=excluded.status,
                path=excluded.path,
                cwd=excluded.cwd,
                cli_version=excluded.cli_version,
                source=excluded.source,
                title=excluded.title,
                sandbox_policy=excluded.sandbox_policy,
                approval_mode=excluded.approval_mode,
                archived=excluded.archived,
                archived_at=excluded.archived_at,
                git_sha=excluded.git_sha,
                git_branch=excluded.git_branch,
                git_origin_url=excluded.git_origin_url,
                memory_mode=excluded.memory_mode
            """,
            (
                meta.id,
                meta.rollout_path,
                meta.preview,
                int(meta.ephemeral),
                meta.model_provider,
                meta.created_at,
                meta.updated_at,
                meta.status.value,
                meta.path,
                meta.cwd,
                meta.cli_version,
                meta.source.value,
                meta.name,
                meta.sandbox_policy,
                meta.approval_mode,
                int(meta.archived),
                meta.archived_at,
                meta.git_sha,
                meta.git_branch,
                meta.git_origin_url,
                meta.memory_mode,
            ),
        )
        await conn.commit()

    async def _get_thread(self, thread_id: str) -> ThreadMetadata | None:
        conn = await self._db.connect()
        cursor = await conn.execute(
            """
            SELECT id, preview, model_provider, cwd, cli_version, source,
                   status, created_at, updated_at, rollout_path, ephemeral, path,
                   title, sandbox_policy, approval_mode, archived, archived_at,
                   git_sha, git_branch, git_origin_url, memory_mode
            FROM threads WHERE id = ?
            """,
            (thread_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_thread_metadata(dict(row))


# --- helpers ----------------------------------------------------------------


def _epoch_now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _cli_version() -> str:
    return "0.1.0-py"


def _row_to_thread_metadata(data: dict[str, Any]) -> ThreadMetadata:
    return ThreadMetadata(
        id=data["id"],
        preview=data.get("preview", ""),
        model_provider=data.get("model_provider", ""),
        cwd=data.get("cwd", "."),
        cli_version=data.get("cli_version", ""),
        source=SessionSource(data.get("source", "unknown")),
        status=ThreadStatus(data.get("status", "idle")),
        created_at=data.get("created_at", 0),
        updated_at=data.get("updated_at", 0),
        rollout_path=data.get("rollout_path"),
        ephemeral=bool(data.get("ephemeral", 0)),
        path=data.get("path"),
        name=data.get("title"),
        sandbox_policy=data.get("sandbox_policy"),
        approval_mode=data.get("approval_mode"),
        archived=bool(data.get("archived", 0)),
        archived_at=data.get("archived_at"),
        git_sha=data.get("git_sha"),
        git_branch=data.get("git_branch"),
        git_origin_url=data.get("git_origin_url"),
        memory_mode=data.get("memory_mode"),
    )
