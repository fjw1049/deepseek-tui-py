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


def test_workspace_filter_applies_before_candidate_limit(tmp_path) -> None:
    """Other workspaces should not crowd out current-workspace candidates."""
    store = MemoryStore(tmp_path / "m.db")
    store.open()
    try:
        for i in range(20):
            store.insert_memory(
                content=f"shared deployment token noisy fact {i}",
                mem_type="instruction",
                workspace=f"/ws/noise-{i}",
                thread_id=f"noise-{i}",
                confidence=1.0,
            )
        store.insert_memory(
            content="shared deployment token current workspace fact",
            mem_type="instruction",
            workspace="/ws/current",
            thread_id="current",
            confidence=1.0,
        )

        hits = store.search_memories(
            "shared deployment token",
            workspace="/ws/current",
            limit=2,
            score_threshold=0.0,
        )
        assert any(row.workspace == "/ws/current" for row, _ in hits)
    finally:
        store.close()


def test_multi_term_query_requires_more_than_one_weak_match(tmp_path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    store.open()
    try:
        store.insert_memory(
            content="API base URL is stored in config",
            mem_type="instruction",
            workspace="/ws",
            thread_id="t1",
            confidence=1.0,
        )
        weak_hits = store.search_memories(
            "api deployment timeout",
            workspace="/ws",
            limit=5,
            score_threshold=0.3,
        )
        assert weak_hits == []

        store.insert_memory(
            content="API deployment timeout is fixed by raising gateway limits",
            mem_type="instruction",
            workspace="/ws",
            thread_id="t2",
            confidence=1.0,
        )
        strong_hits = store.search_memories(
            "api deployment timeout",
            workspace="/ws",
            limit=5,
            score_threshold=0.3,
        )
        assert strong_hits
        assert "gateway limits" in strong_hits[0][0].content
    finally:
        store.close()


def test_l1_tencentdb_compatible_fields_are_persisted(tmp_path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    store.open()
    try:
        mem_id = store.insert_memory(
            content="用户要求 AI 以后回答时先给结论",
            mem_type="instruction",
            workspace="/ws",
            thread_id="thr",
            confidence=0.95,
            priority=95,
            scene_name="我（AI）在和用户约定回答风格",
            source_message_ids=["msg_1"],
            metadata={"activity_start_time": "2026-06-01T00:00:00Z"},
            timestamps=["2026-06-01T00:00:00Z"],
            session_key="session-key",
            session_id="session-id",
        )
        assert mem_id

        row = store.get_memory(mem_id)
        assert row is not None
        assert row.priority == 95
        assert row.scene_name == "我（AI）在和用户约定回答风格"
        assert row.source_message_ids == ["msg_1"]
        assert row.metadata == {"activity_start_time": "2026-06-01T00:00:00Z"}
        assert row.timestamps == ["2026-06-01T00:00:00Z"]
        assert row.session_key == "session-key"
        assert row.session_id == "session-id"
    finally:
        store.close()
