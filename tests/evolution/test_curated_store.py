from pathlib import Path

import pytest

from deepseek_tui.evolution.curated.store import SECTION, CuratedMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> CuratedMemoryStore:
    return CuratedMemoryStore(tmp_path, memory_char_limit=100, user_char_limit=50)


def test_curated_add_and_section_separator(store: CuratedMemoryStore) -> None:
    r1 = store.add("memory", "first note")
    r2 = store.add("memory", "second note")
    assert r1["ok"] and r2["ok"]
    body = SECTION.join(store.memory_entries)
    assert SECTION in body or len(store.memory_entries) == 2
    assert "first note" in body and "second note" in body


def test_curated_rejects_over_limit_on_add(store: CuratedMemoryStore) -> None:
    first = store.add("user", "x" * 30)
    assert first["ok"]
    second = store.add("user", "y" * 30)
    assert not second["ok"]
    assert "usage" in second
    assert "current_entries" in second
    assert len(store.user_entries) == 1


def test_curated_dedupes_on_add(store: CuratedMemoryStore) -> None:
    store.add("memory", "same fact")
    again = store.add("memory", "same fact")
    assert again["ok"]
    assert len(store.memory_entries) == 1


def test_curated_replace_multiple_match(store: CuratedMemoryStore) -> None:
    store.add("memory", "alpha one")
    store.add("memory", "alpha two")
    result = store.replace("memory", "alpha", "beta content here")
    assert not result["ok"]
    assert "matches" in result


def test_curated_blocks_unsafe_content(store: CuratedMemoryStore) -> None:
    result = store.add("memory", "<script>alert(1)</script>")
    assert not result["ok"]
