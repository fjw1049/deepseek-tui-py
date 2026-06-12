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
