from __future__ import annotations

import json
from typing import Any

import pytest

from deepseek_tui.memory.native.l1_extractor import L1Extractor, should_extract_l1
from deepseek_tui.memory.native.store import MemoryStore
from deepseek_tui.protocol.responses import StreamTextDelta


class _FakeClient:
    def __init__(self, payload: list[dict[str, Any]] | None = None) -> None:
        self.payloads = [payload or []]
        self.requests: list[Any] = []

    @classmethod
    def with_payloads(cls, payloads: list[list[dict[str, Any]]]) -> _FakeClient:
        client = cls([])
        client.payloads = payloads.copy()
        return client

    async def stream_with_retry(self, request):  # noqa: ANN001
        self.requests.append(request)
        payload = self.payloads.pop(0) if self.payloads else []
        yield StreamTextDelta(text=json.dumps(payload, ensure_ascii=False))


def test_should_extract_l1_filters_structural_noise() -> None:
    assert not should_extract_l1("")
    assert not should_extract_l1("???")
    assert not should_extract_l1("!!!")
    assert not should_extract_l1("/compact")
    assert not should_extract_l1("<relevant-memories>x</relevant-memories>")
    assert should_extract_l1("用户要求以后回答先给结论")


@pytest.mark.asyncio
async def test_extract_skips_llm_when_all_messages_fail_l1_gate(tmp_path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    store.open()
    client = _FakeClient([])
    extractor = L1Extractor(
        client,  # type: ignore[arg-type]
        store,
        model="fake-model",
        confidence_min=0.6,
        max_per_session=20,
    )
    try:
        result = await extractor.extract_and_store(
            "thr",
            [{"id": "m1", "role": "user", "content": "???", "timestamp": 1}],
            workspace="/ws",
        )
        assert result.inserted == 0
        assert client.requests == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_extract_uses_batch_dedup_update_decision(tmp_path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    store.open()
    old_id = store.insert_memory(
        content="User prefers unittest for tests",
        mem_type="instruction",
        workspace="/ws",
        thread_id="thr",
        confidence=0.8,
        priority=80,
    )
    assert old_id

    extraction_payload = [
        {
            "scene_name": "我（AI）在和用户维护测试规范",
            "message_ids": ["m1"],
            "memories": [
                {
                    "content": "User prefers pytest for tests",
                    "type": "instruction",
                    "priority": 95,
                    "source_message_ids": ["m1"],
                    "metadata": {},
                }
            ],
        }
    ]
    decision_payload = [
        {
            "record_id": "new_0",
            "action": "update",
            "target_ids": [old_id],
            "merged_content": "User prefers pytest for tests",
            "merged_type": "instruction",
            "merged_priority": 95,
            "merged_timestamps": ["2026-06-01T00:00:00Z"],
        }
    ]
    client = _FakeClient.with_payloads([extraction_payload, decision_payload])
    extractor = L1Extractor(
        client,  # type: ignore[arg-type]
        store,
        model="fake-model",
        confidence_min=0.6,
        max_per_session=20,
    )
    try:
        result = await extractor.extract_and_store(
            "thr",
            [
                {
                    "id": "m1",
                    "role": "user",
                    "content": "Remember that pytest is the required test runner",
                    "timestamp": 1,
                }
            ],
            workspace="/ws",
        )
        assert result.inserted == 1
        assert len(client.requests) == 2
        assert store.get_memory(old_id) is None
        hits = store.search_memories("pytest tests", workspace="/ws", score_threshold=0.0)
        assert hits
        assert hits[0][0].content == "User prefers pytest for tests"
        assert hits[0][0].priority == 95
    finally:
        store.close()


@pytest.mark.asyncio
async def test_extract_prompt_includes_previous_scene_name(tmp_path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    store.open()
    payload = [
        {
            "scene_name": "我（AI）在和用户维护部署规范",
            "message_ids": ["m1"],
            "memories": [
                {
                    "content": "用户要求 AI 以后部署前先运行 pytest",
                    "type": "instruction",
                    "priority": 90,
                    "source_message_ids": ["m1"],
                    "metadata": {},
                }
            ],
        }
    ]
    client = _FakeClient(payload)
    extractor = L1Extractor(
        client,  # type: ignore[arg-type]
        store,
        model="fake-model",
        confidence_min=0.6,
        max_per_session=20,
    )
    try:
        result = await extractor.extract_and_store(
            "thr",
            [
                {
                    "id": "m1",
                    "role": "user",
                    "content": "以后部署前请先运行 pytest",
                    "timestamp": 1,
                }
            ],
            workspace="/ws",
            previous_scene_name="我（AI）在和用户讨论测试流程",
        )
        assert result.inserted == 1
        assert result.last_scene_name == "我（AI）在和用户维护部署规范"
        prompt_text = client.requests[0].messages[0].content[0].text
        assert "我（AI）在和用户讨论测试流程" in prompt_text
    finally:
        store.close()
