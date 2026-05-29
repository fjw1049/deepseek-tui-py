import json

from deepseek_tui.memory.native.l0_search import format_l0_hits, search_l0_jsonl


def test_l0_search_finds_matching_line(tmp_path) -> None:
    l0 = tmp_path / "l0"
    l0.mkdir()
    rows = [
        {
            "id": "1",
            "role": "user",
            "content": "We use pytest for all Python tests",
            "workspace": "/ws/a",
        },
        {
            "id": "2",
            "role": "assistant",
            "content": "Acknowledged.",
            "workspace": "/ws/a",
        },
        {
            "id": "3",
            "role": "user",
            "content": "Unrelated weather chat",
            "workspace": "/ws/a",
        },
    ]
    path = l0 / "thr_demo.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    hits = search_l0_jsonl(l0, "pytest Python", thread_id="thr_demo", workspace="/ws/a", limit=3)
    assert hits
    assert "pytest" in hits[0]["content"].lower()
    text = format_l0_hits(hits)
    assert "thr_demo" in text
