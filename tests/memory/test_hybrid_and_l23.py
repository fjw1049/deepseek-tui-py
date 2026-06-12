"""Hybrid RRF search and L2/L3 wiring (no LLM)."""

from __future__ import annotations

import pytest

from deepseek_tui.memory.l2 import SceneStore
from deepseek_tui.memory.l3 import (
    persona_path_for_workspace,
    refresh_persona_from_store,
    refresh_persona_with_llm,
)
from deepseek_tui.memory.store import MemoryStore
from deepseek_tui.protocol.responses import StreamTextDelta, StreamToolCallComplete, ToolCall


class _PersonaClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests = []

    async def stream_with_retry(self, request):  # noqa: ANN001
        self.requests.append(request)
        yield StreamTextDelta(text=self.text)


class _CoroutineClient:
    async def stream_with_retry(self, request):  # noqa: ANN001, ARG002
        return []


class _PersonaToolClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    async def stream_with_retry(self, request):  # noqa: ANN001
        self.requests.append(request)
        if len(self.requests) == 1:
            yield StreamToolCallComplete(
                tool_call=ToolCall(
                    id="call_1",
                    name="write",
                    arguments={"path": "persona.md", "content": self.content},
                )
            )
            return
        yield StreamTextDelta(text="done")


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


@pytest.mark.asyncio
async def test_l3_persona_refresh_with_llm(tmp_path) -> None:
    db = tmp_path / "memory.db"
    persona = tmp_path / "persona.md"
    store = MemoryStore(db)
    store.open()
    try:
        store.insert_memory(
            content="Prefers concise answers and Python tests with pytest",
            mem_type="persona",
            workspace="/ws",
            thread_id="t1",
            confidence=0.95,
            priority=95,
        )
        client = _PersonaClient("# Persona\n\n- Prefers concise pytest-focused help.")
        assert await refresh_persona_with_llm(
            client,
            store,
            persona,
            model="fake-model",
            workspace="/ws",
        )
        text = persona_path_for_workspace(persona, workspace="/ws").read_text(
            encoding="utf-8"
        )
        assert "pytest-focused" in text
        assert client.requests
    finally:
        store.close()


@pytest.mark.asyncio
async def test_l3_persona_refresh_prefers_tool_agent_and_backs_up(tmp_path) -> None:
    db = tmp_path / "memory.db"
    persona = tmp_path / "persona.md"
    persona.write_text("# Persona\n\nold\n", encoding="utf-8")
    store = MemoryStore(db)
    store.open()
    try:
        store.insert_memory(
            content="Prefers direct answers",
            mem_type="persona",
            workspace=None,
            thread_id="t1",
            confidence=0.95,
        )
        client = _PersonaToolClient("# Persona\n\nPrefers direct answers.")
        assert await refresh_persona_with_llm(
            client,
            store,
            persona,
            model="fake-model",
            workspace=None,
        )
        assert "direct answers" in persona.read_text(encoding="utf-8")
        backups = list((tmp_path / ".backup" / "persona").glob("*persona.md"))
        assert backups
        assert "old" in backups[0].read_text(encoding="utf-8")
    finally:
        store.close()


@pytest.mark.asyncio
async def test_l3_persona_refresh_with_llm_falls_back_for_non_stream_client(tmp_path) -> None:
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
        assert await refresh_persona_with_llm(
            _CoroutineClient(),
            store,
            persona,
            model="fake-model",
            workspace="/ws",
        )
        text = persona_path_for_workspace(persona, workspace="/ws").read_text(
            encoding="utf-8"
        )
        assert "TypeScript" in text
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
