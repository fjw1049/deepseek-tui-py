from deepseek_tui.memory.native.fts_tokenize import build_fts_query, collect_query_tokens
from deepseek_tui.memory.native.store import MemoryStore


def test_cjk_simple_tokenizer_finds_chinese_memory(tmp_path) -> None:
    store = MemoryStore(tmp_path / "m.db", fts_tokenizer="simple")
    store.open()
    try:
        store.insert_memory(
            content="项目使用 PostgreSQL 16 作为生产数据库",
            mem_type="episodic",
            workspace="/ws",
            thread_id="t1",
            confidence=0.9,
        )
        hits = store.search_memories(
            "PostgreSQL 数据库",
            workspace="/ws",
            limit=5,
            score_threshold=0.0,
            hybrid=False,
        )
        assert hits
        assert "PostgreSQL" in hits[0][0].content
    finally:
        store.close()


def test_build_fts_query_includes_cjk_tokens() -> None:
    tokens = collect_query_tokens("连接池配置", mode="simple")
    assert any("连接" in t or "连接池" in t for t in tokens)
    q = build_fts_query("连接池", mode="simple")
    assert "连接" in q or "连接池" in q
