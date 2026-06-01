"""Live embedding API — run with ``-m live``."""

from __future__ import annotations

import pytest

from deepseek_tui.config.models import Config, MemorySmartConfig
from deepseek_tui.memory.native.embedding import EmbeddingClient

pytestmark = pytest.mark.live


@pytest.fixture
def embedding_smart_config(live_project_config: Config) -> MemorySmartConfig:
    smart = live_project_config.memory.smart
    if not smart.embedding_enabled():
        pytest.skip("set memory.smart.embedding_provider=openai in config")
    if not smart.embedding_api_key.strip() or not smart.embedding_base_url.strip():
        pytest.skip("embedding_api_key/base_url not configured")
    return smart


@pytest.mark.asyncio
async def test_embedding_api_reachable(embedding_smart_config: MemorySmartConfig) -> None:
    client = EmbeddingClient(embedding_smart_config)
    try:
        vec = await client.embed("memory integration probe")
        assert len(vec) >= 128
    finally:
        await client.close()
