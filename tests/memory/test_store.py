import time

from deepseek_tui.memory.native.store import MemoryStore


def test_fts_search_and_time_decay_ordering(tmp_path) -> None:
    db = tmp_path / "memory.db"
    store = MemoryStore(db)
    store.open()
    try:
        old_ts = int(time.time() * 1000) - 200 * 86_400_000
        new_ts = int(time.time() * 1000) - 86_400_000
        id_old = store.insert_memory(
            content="Project uses React 17 for the frontend stack",
            mem_type="episodic",
            workspace="/ws/a",
            thread_id="thr_test",
            confidence=0.9,
        )
        id_new = store.insert_memory(
            content="Project uses React 19 for the frontend stack",
            mem_type="episodic",
            workspace="/ws/a",
            thread_id="thr_test",
            confidence=0.9,
        )
        assert id_old and id_new
        conn = store._conn_required()
        conn.execute(
            "UPDATE memories SET created_at = ? WHERE id = ?",
            (old_ts, id_old),
        )
        conn.execute(
            "UPDATE memories SET created_at = ? WHERE id = ?",
            (new_ts, id_new),
        )
        conn.commit()

        hits = store.search_memories(
            "React frontend",
            workspace="/ws/a",
            limit=5,
            score_threshold=0.0,
            half_life_days=180,
        )
        assert len(hits) >= 2
        assert "React 19" in hits[0][0].content
    finally:
        store.close()


def test_workspace_boost_prefers_same_workspace(tmp_path) -> None:
    db = tmp_path / "memory.db"
    store = MemoryStore(db)
    store.open()
    try:
        store.insert_memory(
            content="database connection pool size is 50 in workspace A",
            mem_type="instruction",
            workspace="/ws/a",
            thread_id="t1",
            confidence=1.0,
        )
        store.insert_memory(
            content="database connection pool size is 80 in workspace B",
            mem_type="instruction",
            workspace="/ws/b",
            thread_id="t2",
            confidence=1.0,
        )
        hits = store.search_memories(
            "database connection pool",
            workspace="/ws/a",
            limit=2,
            score_threshold=0.0,
        )
        assert hits
        assert hits[0][0].workspace == "/ws/a"
    finally:
        store.close()


def test_recall_excludes_other_workspace_facts(tmp_path) -> None:
    """MEMORY_INTEGRATION §6 #3 — project B recall must not surface A-only facts."""
    store = MemoryStore(tmp_path / "m.db")
    store.open()
    try:
        store.insert_memory(
            content="Workspace A only secret codename is ALPHA-7",
            mem_type="instruction",
            workspace="/ws/a",
            thread_id="t1",
            confidence=1.0,
        )
        store.insert_memory(
            content="Workspace B only secret codename is BRAVO-9",
            mem_type="instruction",
            workspace="/ws/b",
            thread_id="t2",
            confidence=1.0,
        )
        hits = store.search_memories(
            "secret codename BRAVO",
            workspace="/ws/b",
            limit=5,
            score_threshold=0.0,
        )
        contents = " ".join(h[0].content for h in hits)
        assert "BRAVO-9" in contents
        assert "ALPHA-7" not in contents
    finally:
        store.close()
