"""Embedding pack/unpack, dedup, and mocked API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from deepseek_tui.config.models import MemoryConfig, MemorySmartConfig
from deepseek_tui.memory.search import (
    EmbeddingClient,
    cosine_similarity,
    pack_embedding,
    unpack_embedding,
)
from deepseek_tui.memory.store import MemoryStore


def test_cosine_identical_vectors() -> None:
    v = pack_embedding([1.0, 0.0, 0.0])
    a = unpack_embedding(v)
    b = unpack_embedding(v)
    assert cosine_similarity(a, b) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.asyncio
async def test_semantic_dedup_blocks_near_duplicate(tmp_path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    store.open()
    try:
        vec = [1.0, 0.0, 0.0]
        mid = store.insert_memory(
            content="User prefers pytest for all Python tests",
            mem_type="instruction",
            workspace="/ws",
            thread_id="t1",
            confidence=1.0,
        )
        assert mid
        store.save_embedding(mid, model="test", vector=vec)
        assert store.is_semantic_duplicate(
            [0.99, 0.01, 0.0],
            workspace="/ws",
            threshold=0.92,
        )
    finally:
        store.close()


@pytest.mark.asyncio
async def test_provider_indexes_embedding_on_insert(tmp_path) -> None:
    from deepseek_tui.config.models import Config
    from deepseek_tui.memory.seed import NativeMemoryProvider

    cfg = Config(
        memory=MemoryConfig(
            enabled=True,
            smart=MemorySmartConfig(
                enabled=True,
                data_dir=str(tmp_path / "mem"),
                embedding_provider="openai",
                embedding_api_key="test-key",
                embedding_base_url="https://example.com",
            ),
        )
    )
    provider = NativeMemoryProvider(cfg, AsyncMock())
    fake_vec = [0.1, 0.2, 0.3]
    with patch.object(
        EmbeddingClient,
        "health_check",
        new=AsyncMock(return_value=3),
    ), patch.object(
        EmbeddingClient,
        "embed",
        new=AsyncMock(return_value=fake_vec),
    ):
        await provider.start()
        try:
            mem_id = await provider.remember_instruction(
                "Use ruff for linting",
                workspace="/ws",
                thread_id="t1",
            )
            assert mem_id
            row = provider._store._conn_required().execute(
                "SELECT dims FROM memory_embeddings WHERE memory_id = ?",
                (mem_id,),
            ).fetchone()
            assert row is not None
            assert int(row[0]) == 3
        finally:
            await provider.stop()


@pytest.mark.asyncio
async def test_backfill_indexes_missing_rows(tmp_path) -> None:
    from deepseek_tui.config.models import Config
    from deepseek_tui.memory.seed import NativeMemoryProvider

    cfg = Config(
        memory=MemoryConfig(
            enabled=True,
            smart=MemorySmartConfig(
                enabled=True,
                data_dir=str(tmp_path / "mem"),
                embedding_provider="openai",
                embedding_api_key="k",
                embedding_base_url="https://example.com",
                embedding_backfill_on_start=False,
            ),
        )
    )
    provider = NativeMemoryProvider(cfg, AsyncMock())
    fake = [0.5, 0.5, 0.5]
    with patch.object(
        EmbeddingClient, "health_check", new=AsyncMock(return_value=3)
    ), patch.object(EmbeddingClient, "embed", new=AsyncMock(return_value=fake)):
        await provider.start()
        try:
            mid = provider._store.insert_memory(
                content="backfill me",
                mem_type="instruction",
                workspace="/w",
                thread_id="t",
                confidence=1.0,
            )
            assert mid
            n = await provider._backfill_embeddings()
            assert n >= 1
            row = provider._store._conn_required().execute(
                "SELECT 1 FROM memory_embeddings WHERE memory_id = ?",
                (mid,),
            ).fetchone()
            assert row is not None
        finally:
            await provider.stop()
