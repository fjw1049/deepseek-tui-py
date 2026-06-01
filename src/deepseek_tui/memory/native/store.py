"""SQLite + FTS5 memory store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepseek_tui.memory.native.embedding import cosine_similarity, pack_embedding, unpack_embedding
from deepseek_tui.memory.native.fts_tokenize import build_fts_query, collect_query_tokens
from deepseek_tui.memory.native.hybrid_search import reciprocal_rank_fusion


@dataclass(slots=True)
class MemoryRow:
    id: str
    content: str
    type: str
    workspace: str | None
    thread_id: str | None
    confidence: float
    created_at: int
    updated_at: int
    last_recalled_at: int | None
    priority: int = 100
    scene_name: str = ""
    source_message_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None
    timestamps: list[str] | None = None
    session_key: str | None = None
    session_id: str = ""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _row_in_workspace_scope(row_workspace: str | None, workspace: str | None) -> bool:
    """Current workspace rows plus global (NULL) rows; exclude other projects."""
    if not workspace:
        return True
    return row_workspace is None or row_workspace == workspace


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_list(raw: object) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data]


def _json_dict(raw: object) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _memory_row(row: sqlite3.Row) -> MemoryRow:
    return MemoryRow(
        id=row["id"],
        content=row["content"],
        type=row["type"],
        workspace=row["workspace"],
        thread_id=row["thread_id"],
        confidence=float(row["confidence"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        last_recalled_at=row["last_recalled_at"],
        priority=int(row["priority"] if row["priority"] is not None else 100),
        scene_name=str(row["scene_name"] or ""),
        source_message_ids=_json_list(row["source_message_ids_json"]),
        metadata=_json_dict(row["metadata_json"]),
        timestamps=_json_list(row["timestamps_json"]),
        session_key=row["session_key"],
        session_id=str(row["session_id"] or ""),
    )


class MemoryStore:
    def __init__(self, db_path: Path, *, fts_tokenizer: str = "auto") -> None:
        self._db_path = db_path
        self._fts_tokenizer = fts_tokenizer
        self._conn: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._db_path

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _conn_required(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("MemoryStore is not open")
        return self._conn

    def _init_schema(self) -> None:
        conn = self._conn_required()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
              id TEXT PRIMARY KEY,
              content TEXT NOT NULL,
              type TEXT NOT NULL,
              workspace TEXT,
              thread_id TEXT,
              confidence REAL NOT NULL DEFAULT 1.0,
              priority INTEGER NOT NULL DEFAULT 100,
              scene_name TEXT NOT NULL DEFAULT '',
              source_message_ids_json TEXT NOT NULL DEFAULT '[]',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              timestamps_json TEXT NOT NULL DEFAULT '[]',
              session_key TEXT,
              session_id TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              last_recalled_at INTEGER,
              content_hash TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
              content,
              content='memories',
              content_rowid='rowid'
            );

            CREATE TABLE IF NOT EXISTS l0_cursors (
              thread_id TEXT PRIMARY KEY,
              last_timestamp_ms INTEGER NOT NULL,
              last_message_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
              INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
              INSERT INTO memories_fts(memories_fts, rowid, content)
                VALUES('delete', old.rowid, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
              INSERT INTO memories_fts(memories_fts, rowid, content)
                VALUES('delete', old.rowid, old.content);
              INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
            END;

            CREATE TABLE IF NOT EXISTS memory_embeddings (
              memory_id TEXT PRIMARY KEY,
              model TEXT NOT NULL,
              dims INTEGER NOT NULL,
              embedding BLOB NOT NULL,
              FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            );
            """
        )
        self._ensure_memory_columns(conn)
        conn.commit()

    def _ensure_memory_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        additions = {
            "priority": "INTEGER NOT NULL DEFAULT 100",
            "scene_name": "TEXT NOT NULL DEFAULT ''",
            "source_message_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "timestamps_json": "TEXT NOT NULL DEFAULT '[]'",
            "session_key": "TEXT",
            "session_id": "TEXT NOT NULL DEFAULT ''",
        }
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")

    def save_embedding(
        self, memory_id: str, *, model: str, vector: list[float]
    ) -> None:
        conn = self._conn_required()
        conn.execute(
            """
            INSERT INTO memory_embeddings (memory_id, model, dims, embedding)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
              model = excluded.model,
              dims = excluded.dims,
              embedding = excluded.embedding
            """,
            (memory_id, model, len(vector), pack_embedding(vector)),
        )
        conn.commit()

    def is_semantic_duplicate(
        self,
        vector: list[float],
        *,
        workspace: str | None,
        threshold: float,
    ) -> bool:
        hits = self._vector_search(vector, workspace=workspace, limit=32)
        return any(score >= threshold for _, score in hits)

    def _vector_search(
        self,
        query_vec: list[float],
        *,
        workspace: str | None,
        limit: int,
    ) -> list[tuple[MemoryRow, float]]:
        q = unpack_embedding(pack_embedding(query_vec))
        conn = self._conn_required()
        if workspace:
            rows = conn.execute(
                """
                SELECT m.*, e.embedding AS emb
                FROM memories m
                INNER JOIN memory_embeddings e ON e.memory_id = m.id
                WHERE m.workspace = ? OR m.workspace IS NULL
                """,
                (workspace,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT m.*, e.embedding AS emb
                FROM memories m
                INNER JOIN memory_embeddings e ON e.memory_id = m.id
                """
            ).fetchall()
        scored: list[tuple[MemoryRow, float]] = []
        for row in rows:
            blob = row["emb"]
            if not blob:
                continue
            sim = cosine_similarity(q, unpack_embedding(blob))
            mem = _memory_row(row)
            scored.append((mem, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def get_l0_cursor(self, thread_id: str) -> tuple[int, int]:
        conn = self._conn_required()
        row = conn.execute(
            "SELECT last_timestamp_ms, last_message_count FROM l0_cursors WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return 0, 0
        return int(row[0]), int(row[1])

    def set_l0_cursor(
        self, thread_id: str, *, last_timestamp_ms: int, last_message_count: int
    ) -> None:
        conn = self._conn_required()
        conn.execute(
            """
            INSERT INTO l0_cursors (thread_id, last_timestamp_ms, last_message_count)
            VALUES (?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
              last_timestamp_ms = excluded.last_timestamp_ms,
              last_message_count = excluded.last_message_count
            """,
            (thread_id, last_timestamp_ms, last_message_count),
        )
        conn.commit()

    def insert_memory(
        self,
        *,
        content: str,
        mem_type: str,
        workspace: str | None,
        thread_id: str | None,
        confidence: float,
        priority: int | None = None,
        scene_name: str = "",
        source_message_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        timestamps: list[str] | None = None,
        session_key: str | None = None,
        session_id: str = "",
        allow_duplicate: bool = False,
    ) -> str | None:
        text = content.strip()
        if not text:
            return None
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        conn = self._conn_required()
        if not allow_duplicate:
            dup = conn.execute(
                "SELECT id FROM memories WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
            if dup is not None:
                return None
            if len(text) >= 24:
                prefix = text[:48]
                near = conn.execute(
                    """
                    SELECT id FROM memories
                    WHERE content LIKE ? AND (workspace = ? OR workspace IS NULL)
                    LIMIT 1
                    """,
                    (f"%{prefix}%", workspace),
                ).fetchone()
                if near is not None:
                    return None
        now = _now_ms()
        effective_priority = (
            priority
            if priority is not None
            else max(0, min(100, int(round(confidence * 100))))
        )
        effective_timestamps = timestamps or [str(now)]
        mem_id = f"mem_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO memories (
              id, content, type, workspace, thread_id, confidence, priority,
              scene_name, source_message_ids_json, metadata_json, timestamps_json,
              session_key, session_id, created_at, updated_at, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mem_id,
                text,
                mem_type,
                workspace,
                thread_id,
                confidence,
                effective_priority,
                scene_name,
                _json_dumps(source_message_ids or []),
                _json_dumps(metadata or {}),
                _json_dumps(effective_timestamps),
                session_key or thread_id,
                session_id,
                now,
                now,
                content_hash,
            ),
        )
        conn.commit()
        return mem_id

    def get_memory(self, memory_id: str) -> MemoryRow | None:
        conn = self._conn_required()
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return _memory_row(row) if row else None

    def delete_memories(self, memory_ids: list[str]) -> int:
        if not memory_ids:
            return 0
        conn = self._conn_required()
        before = conn.total_changes
        conn.executemany("DELETE FROM memories WHERE id = ?", [(mid,) for mid in memory_ids])
        conn.commit()
        return conn.total_changes - before

    def _fetch_fts_rows(
        self, query: str, *, workspace: str | None, limit: int
    ) -> list[sqlite3.Row]:
        fts_q = build_fts_query(query, mode=self._fts_tokenizer)
        conn = self._conn_required()
        scope_sql = ""
        params: tuple[object, ...]
        if workspace:
            scope_sql = "AND (m.workspace = ? OR m.workspace IS NULL)"
            params = (fts_q, workspace, limit)
        else:
            params = (fts_q, limit)
        try:
            return conn.execute(
                f"""
                SELECT m.*, bm25(memories_fts) AS rank
                FROM memories_fts
                JOIN memories m ON m.rowid = memories_fts.rowid
                WHERE memories_fts MATCH ?
                {scope_sql}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    def _fetch_like_rows(
        self, query: str, *, workspace: str | None, limit: int
    ) -> list[sqlite3.Row]:
        needle = query.strip()[:80]
        if not needle:
            return []
        conn = self._conn_required()
        if workspace:
            return conn.execute(
                """
                SELECT m.*, -1.0 AS rank
                FROM memories m
                WHERE m.content LIKE ? AND (m.workspace = ? OR m.workspace IS NULL)
                LIMIT ?
                """,
                (f"%{needle}%", workspace, limit),
            ).fetchall()
        return conn.execute(
            """
            SELECT m.*, -1.0 AS rank
            FROM memories m
            WHERE m.content LIKE ?
            LIMIT ?
            """,
            (f"%{needle}%", limit),
        ).fetchall()

    def _score_rows(
        self,
        rows: list[sqlite3.Row],
        *,
        query_tokens: list[str],
        workspace: str | None,
        score_threshold: float,
        half_life_days: float,
        workspace_boost: float,
    ) -> list[tuple[MemoryRow, float]]:
        if not rows:
            return []
        ranks = [float(r["rank"]) for r in rows]
        min_rank = min(ranks)
        max_rank = max(ranks)
        span = max_rank - min_rank
        now_ms = _now_ms()
        scored: list[tuple[MemoryRow, float]] = []

        for row in rows:
            if not _row_in_workspace_scope(row["workspace"], workspace):
                continue
            content_lower = str(row["content"]).lower()
            matched_terms = sum(
                1 for token in query_tokens if token.lower() in content_lower
            )
            if len(query_tokens) >= 2 and matched_terms < 2:
                continue
            raw_rank = float(row["rank"])
            if span < 1e-5:
                fts_score = 1.0
            else:
                fts_score = (max_rank - raw_rank) / span
            if query_tokens:
                coverage = matched_terms / len(query_tokens)
                fts_score *= max(0.25, coverage)
            age_days = max(0.0, (now_ms - int(row["created_at"])) / 86_400_000.0)
            if half_life_days > 0:
                decay = 0.5 ** (age_days / half_life_days)
            else:
                decay = 1.0
            boost = workspace_boost if workspace and row["workspace"] == workspace else 1.0
            final = fts_score * decay * boost
            if final < score_threshold:
                continue
            mem = _memory_row(row)
            scored.append((mem, final))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def search_memories(
        self,
        query: str,
        *,
        workspace: str | None,
        limit: int = 8,
        score_threshold: float = 0.3,
        half_life_days: float = 180.0,
        workspace_boost: float = 1.2,
        hybrid: bool = False,
        query_embedding: list[float] | None = None,
    ) -> list[tuple[MemoryRow, float]]:
        cap = limit * 4
        query_tokens = collect_query_tokens(query, mode=self._fts_tokenizer)
        if hybrid:
            fts_scored = self._score_rows(
                self._fetch_fts_rows(query, workspace=workspace, limit=cap),
                query_tokens=query_tokens,
                workspace=workspace,
                score_threshold=0.0,
                half_life_days=half_life_days,
                workspace_boost=workspace_boost,
            )
            like_scored = self._score_rows(
                self._fetch_like_rows(query, workspace=workspace, limit=cap),
                query_tokens=query_tokens,
                workspace=workspace,
                score_threshold=0.0,
                half_life_days=half_life_days,
                workspace_boost=workspace_boost,
            )
            ranked_lists: list[list[tuple[MemoryRow, float]]] = [fts_scored, like_scored]
            vec_scored: list[tuple[MemoryRow, float]] = []
            if query_embedding:
                vec_scored = self._vector_search(
                    query_embedding, workspace=workspace, limit=cap
                )
                ranked_lists.append(vec_scored)
            merged = reciprocal_rank_fusion(ranked_lists)
            score_by_id: dict[str, float] = {}
            for row, score in fts_scored + like_scored + vec_scored:
                score_by_id[row.id] = max(score_by_id.get(row.id, 0.0), score)
            out: list[tuple[MemoryRow, float]] = []
            for row, _ in merged:
                final = score_by_id.get(row.id, 0.0)
                if final >= score_threshold:
                    out.append((row, final))
            return out[:limit]

        rows = self._fetch_fts_rows(query, workspace=workspace, limit=cap)
        if not rows:
            rows = self._fetch_like_rows(query, workspace=workspace, limit=cap)
        return self._score_rows(
            rows,
            query_tokens=query_tokens,
            workspace=workspace,
            score_threshold=score_threshold,
            half_life_days=half_life_days,
            workspace_boost=workspace_boost,
        )[:limit]

    def list_memories_by_type(
        self,
        mem_type: str,
        *,
        workspace: str | None = None,
        limit: int = 40,
    ) -> list[MemoryRow]:
        conn = self._conn_required()
        if workspace:
            rows = conn.execute(
                """
                SELECT * FROM memories
                WHERE type = ? AND (workspace = ? OR workspace IS NULL)
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (mem_type, workspace, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM memories
                WHERE type = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (mem_type, limit),
            ).fetchall()
        return [_memory_row(row) for row in rows]

    def touch_recalled(self, memory_ids: list[str]) -> None:
        if not memory_ids:
            return
        now = _now_ms()
        conn = self._conn_required()
        conn.executemany(
            "UPDATE memories SET last_recalled_at = ? WHERE id = ?",
            [(now, mid) for mid in memory_ids],
        )
        conn.commit()

    def count_memories_for_thread(self, thread_id: str) -> int:
        conn = self._conn_required()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM memories WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def delete_memories_older_than(self, cutoff_ms: int) -> int:
        conn = self._conn_required()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM memories WHERE created_at < ?",
            (cutoff_ms,),
        ).fetchone()
        count = int(row["c"]) if row else 0
        conn.execute("DELETE FROM memories WHERE created_at < ?", (cutoff_ms,))
        conn.commit()
        return count
