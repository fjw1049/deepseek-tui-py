from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.memory.native.provider import NativeMemoryProvider
from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.memory_tools import (
    MEMORY_PROVIDER_KEY,
    MEMORY_SEARCH_CALLS_KEY,
    ConversationSearchTool,
    MemorySearchTool,
)


class _MinimalProvider(NativeMemoryProvider):
    """Provider with in-memory store only (no LLM)."""

    def __init__(self, data_dir: Path) -> None:
        from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig

        cfg = Config(
            memory=MemoryConfig(
                smart=MemorySmartConfig(enabled=True, data_dir=str(data_dir))
            )
        )
        super().__init__(cfg, AsyncMock())


@pytest.mark.asyncio
async def test_memory_search_tool_uses_provider(tmp_path: Path) -> None:
    data_dir = tmp_path / "mem"
    provider = _MinimalProvider(data_dir)
    await provider.start()
    try:
        provider._store.insert_memory(
            content="User prefers pytest over unittest",
            mem_type="instruction",
            workspace="/proj",
            thread_id="t1",
            confidence=1.0,
        )
        ctx = ToolContext(working_directory=Path("/proj"))
        ctx.metadata[MEMORY_PROVIDER_KEY] = provider
        ctx.metadata[MEMORY_SEARCH_CALLS_KEY] = 0

        result = await MemorySearchTool().execute({"query": "pytest"}, ctx)
        assert result.success
        assert "pytest" in result.content.lower()
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_combined_search_call_limit(tmp_path: Path) -> None:
    data_dir = tmp_path / "mem2"
    provider = _MinimalProvider(data_dir)
    await provider.start()
    try:
        ctx = ToolContext(working_directory=Path("/proj"))
        ctx.metadata[MEMORY_PROVIDER_KEY] = provider
        ctx.metadata[MEMORY_SEARCH_CALLS_KEY] = 0
        tool_m = MemorySearchTool()
        tool_c = ConversationSearchTool()
        await tool_m.execute({"query": "a"}, ctx)
        await tool_m.execute({"query": "b"}, ctx)
        await tool_c.execute({"query": "c"}, ctx)
        with pytest.raises(ToolError, match="limit"):
            await tool_m.execute({"query": "d"}, ctx)
    finally:
        await provider.stop()
