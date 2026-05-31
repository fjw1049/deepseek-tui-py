"""Hybrid RRF search and L2/L3 wiring (no LLM)."""

from __future__ import annotations

from deepseek_tui.memory.native.l2_scenes import SceneStore
from deepseek_tui.memory.native.l3_persona import (
    persona_path_for_workspace,
    refresh_persona_from_store,
)
from deepseek_tui.memory.native.store import MemoryStore


def test_hybrid_search_merges_fts_and_like(tmp_path) -> None:
    db = tmp_path / "memory.db"
    store = MemoryStore(db)
    store.open()
    try:
        store.insert_memory(
            content="Kubernetes deployment uses Helm charts in staging",
            mem_type="episodic",
            workspace="/ws",
            thread_id="t1",
            confidence=0.9,
        )
        store.insert_memory(
            content="Helm chart values override replicas to three",
            mem_type="instruction",
            workspace="/ws",
            thread_id="t1",
            confidence=1.0,
        )
        hits = store.search_memories(
            "Helm charts",
            workspace="/ws",
            limit=5,
            score_threshold=0.0,
            hybrid=True,
        )
        assert len(hits) >= 1
        contents = {h[0].content for h in hits}
        assert any("Helm" in c for c in contents)
    finally:
        store.close()


def test_l3_persona_refresh(tmp_path) -> None:
    db = tmp_path / "memory.db"
    persona = tmp_path / "persona.md"
    store = MemoryStore(db)
    store.open()
    try:
        store.insert_memory(
            content="Prefers concise answers and TypeScript",
            mem_type="persona",
            workspace="/ws",
            thread_id="t1",
            confidence=0.95,
        )
        assert refresh_persona_from_store(store, persona, workspace="/ws")
        text = persona_path_for_workspace(persona, workspace="/ws").read_text(
            encoding="utf-8"
        )
        assert "TypeScript" in text
        assert not persona.exists()
    finally:
        store.close()


def test_l2_scene_navigation(tmp_path) -> None:
    scenes = SceneStore(tmp_path / "data")
    scenes.record_scenes(
        [
            {
                "scene_name": "Onboarding",
                "memories": [{"content": "User joined the payments team"}],
            }
        ],
        workspace="/ws",
    )
    nav = scenes.navigation_markdown(workspace="/ws")
    assert "Onboarding" in nav
    assert "Scene navigation" in nav


def test_l2_scene_files_are_workspace_scoped(tmp_path) -> None:
    scenes = SceneStore(tmp_path / "data")
    scenes.record_scenes(
        [{"scene_name": "Deployment", "memories": [{"content": "A uses Helm"}]}],
        workspace="/ws/a",
    )
    scenes.record_scenes(
        [{"scene_name": "Deployment", "memories": [{"content": "B uses Kustomize"}]}],
        workspace="/ws/b",
    )

    nav_a = scenes.navigation_markdown(workspace="/ws/a")
    nav_b = scenes.navigation_markdown(workspace="/ws/b")
    assert "Deployment" in nav_a
    assert "Deployment" in nav_b
    assert nav_a != nav_b
