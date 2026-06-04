from deepseek_tui.memory.native.l0_search import format_l0_hits


def test_format_l0_hits_summarize_groups_by_thread() -> None:
    hits = [
        {
            "thread_id": "a",
            "line": 1,
            "role": "user",
            "score": 1.2,
            "content": "hello world " * 20,
            "excerpt": "hello world " * 20,
        },
        {
            "thread_id": "a",
            "line": 5,
            "role": "assistant",
            "score": 0.8,
            "content": "reply text",
            "excerpt": "reply text",
        },
        {
            "thread_id": "b",
            "line": 0,
            "role": "user",
            "score": 0.5,
            "content": "other thread",
            "excerpt": "other thread",
        },
    ]
    raw = format_l0_hits(hits, summarize=False)
    summary = format_l0_hits(hits, summarize=True)
    assert "line=1" in raw
    assert "## Thread `a`" in summary
    assert "## Thread `b`" in summary
    assert len(summary) < len(raw)
