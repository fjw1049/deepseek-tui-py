from deepseek_tui.evolution.backends.curated_memory import CuratedMemoryBackend
from deepseek_tui.evolution.curated.store import CuratedMemoryStore
from deepseek_tui.evolution.review.runner import collect_mutations_from_tool_results


def test_collect_mutations_from_tool_results(tmp_path) -> None:
    store = CuratedMemoryStore(tmp_path)
    backend = CuratedMemoryBackend(store)
    tool_results = [
        (
            "memory_curate",
            {"action": "add", "target": "memory", "content": "x"},
            '{"ok": true, "review_only": true, "kind": "memory_curate_add"}',
        )
    ]
    mutations = collect_mutations_from_tool_results(tool_results, [backend])
    assert len(mutations) == 1
    assert mutations[0].kind == "memory_curate_add"


def test_collect_mutations_skips_error_outputs(tmp_path) -> None:
    store = CuratedMemoryStore(tmp_path)
    backend = CuratedMemoryBackend(store)
    tool_results = [
        (
            "memory_curate",
            {"action": "add", "target": "memory", "content": "x"},
            "Error: curated memory store not configured",
        ),
        (
            "memory_curate",
            {"action": "add", "target": "memory", "content": "y"},
            '{"ok": true, "review_only": true, "kind": "memory_curate_add"}',
        ),
    ]
    mutations = collect_mutations_from_tool_results(tool_results, [backend])
    assert len(mutations) == 1
    assert mutations[0].payload["content"] == "y"
