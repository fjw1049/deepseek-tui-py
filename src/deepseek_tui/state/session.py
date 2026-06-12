"""Session persistence — database, schema, session manager, and checkpoints.

Consolidates the former session_manager.py, database.py, schema.py, and checkpoint.py.
"""

from __future__ import annotations



import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import aiosqlite

from deepseek_tui.config.paths import user_checkpoints_dir


# ============================================================================
# Schema (formerly schema.py)
# ============================================================================

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        transcript_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS threads (
        id TEXT PRIMARY KEY,
        rollout_path TEXT,
        preview TEXT NOT NULL DEFAULT '',
        ephemeral INTEGER NOT NULL DEFAULT 0,
        model_provider TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'idle',
        path TEXT,
        cwd TEXT NOT NULL DEFAULT '.',
        cli_version TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'unknown',
        title TEXT,
        sandbox_policy TEXT,
        approval_mode TEXT,
        archived INTEGER NOT NULL DEFAULT 0,
        archived_at INTEGER,
        git_sha TEXT,
        git_branch TEXT,
        git_origin_url TEXT,
        memory_mode TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_threads_updated_at
    ON threads(updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_threads_archived_at
    ON threads(archived_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_threads_archived_updated
    ON threads(archived, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        item_json TEXT,
        created_at INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_messages_thread_created
    ON messages(thread_id, created_at ASC, id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS thread_dynamic_tools (
        thread_id TEXT NOT NULL,
        position INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        input_schema_json TEXT NOT NULL,
        PRIMARY KEY(thread_id, position),
        FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoints (
        thread_id TEXT NOT NULL,
        checkpoint_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        created_at INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(thread_id, checkpoint_id),
        FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_created_at
    ON checkpoints(thread_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        progress INTEGER,
        detail TEXT,
        created_at INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_jobs_updated
    ON jobs(updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS offline_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)
    """,
    """
    INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)
    """,
]


# ============================================================================
# Database (formerly database.py)
# ============================================================================


class Database:
    def __init__(self, path: Path):
        self.path = path.expanduser()
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = await aiosqlite.connect(self.path)
            self._connection.row_factory = aiosqlite.Row
            await self._connection.execute("PRAGMA journal_mode=WAL")
            await self._connection.execute("PRAGMA busy_timeout=5000")
            await self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    async def initialize(self) -> None:
        connection = await self.connect()
        for statement in SCHEMA_STATEMENTS:
            await connection.execute(statement)
        await connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None


# ============================================================================
# Checkpoint (formerly checkpoint.py)
# ============================================================================

CURRENT_SESSION_SCHEMA_VERSION = 1
CURRENT_QUEUE_SCHEMA_VERSION = 1


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


@dataclass(slots=True)
class OfflineQueueState:
    schema_version: int = CURRENT_QUEUE_SCHEMA_VERSION
    session_id: str | None = None
    queued_messages: list[str] = field(default_factory=list)
    draft: str | None = None


def checkpoint_path() -> Path:
    return user_checkpoints_dir() / "latest.json"


def offline_queue_path() -> Path:
    return user_checkpoints_dir() / "offline_queue.json"


def save_checkpoint(payload: dict[str, Any]) -> Path:
    data = {"schema_version": CURRENT_SESSION_SCHEMA_VERSION, **payload}
    path = checkpoint_path()
    _write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
    return path


def load_checkpoint() -> dict[str, Any] | None:
    path = checkpoint_path()
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = int(raw.get("schema_version", 0))
    if version > CURRENT_SESSION_SCHEMA_VERSION:
        raise ValueError(
            f"Checkpoint schema v{version} is newer than supported "
            f"v{CURRENT_SESSION_SCHEMA_VERSION}"
        )
    return raw


def clear_checkpoint() -> None:
    path = checkpoint_path()
    if path.is_file():
        path.unlink()


def save_offline_queue(
    state: OfflineQueueState,
    *,
    session_id: str | None = None,
) -> Path:
    state.session_id = session_id
    path = offline_queue_path()
    _write_atomic(
        path,
        json.dumps(
            {
                "schema_version": state.schema_version,
                "session_id": state.session_id,
                "queued_messages": state.queued_messages,
                "draft": state.draft,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return path


def load_offline_queue() -> OfflineQueueState | None:
    path = offline_queue_path()
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = int(raw.get("schema_version", 0))
    if version > CURRENT_QUEUE_SCHEMA_VERSION:
        raise ValueError(
            f"Offline queue schema v{version} is newer than supported "
            f"v{CURRENT_QUEUE_SCHEMA_VERSION}"
        )
    return OfflineQueueState(
        schema_version=version,
        session_id=raw.get("session_id"),
        queued_messages=list(raw.get("queued_messages") or []),
        draft=raw.get("draft"),
    )


def clear_offline_queue() -> None:
    path = offline_queue_path()
    if path.is_file():
        path.unlink()


# ============================================================================
# Session models (formerly session_manager.py)
# ============================================================================


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


@dataclass(slots=True)
class ThreadMetadata:
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


@dataclass(slots=True)
class SessionUsage:
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


# ============================================================================
# Session Index (JSONL)
# ============================================================================


@dataclass(slots=True)
class SessionIndexEntry:
    thread_id: str
    thread_name: str | None
    updated_at: int
    rollout_path: str | None = None


class SessionIndex:
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


# ============================================================================
# SessionManager
# ============================================================================


class SessionManager:
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
        conn = await self._db.connect()
        now = _epoch_now()
        await conn.execute(
            "UPDATE threads SET archived = 1, archived_at = ?, status = ? WHERE id = ?",
            (now, ThreadStatus.ARCHIVED.value, thread_id),
        )
        await conn.commit()

    async def unarchive(self, thread_id: str) -> None:
        conn = await self._db.connect()
        await conn.execute(
            "UPDATE threads SET archived = 0, archived_at = NULL, status = ? WHERE id = ?",
            (ThreadStatus.IDLE.value, thread_id),
        )
        await conn.commit()

    async def delete(self, thread_id: str) -> None:
        conn = await self._db.connect()
        await conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        await conn.commit()

    async def touch(self, thread_id: str, preview: str | None = None) -> None:
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


# ============================================================================
# Helpers
# ============================================================================


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
