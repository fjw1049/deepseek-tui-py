from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.memory.native.provider import NativeMemoryProvider
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.knowledge_tools import RememberTool
from deepseek_tui.host.services import ServiceScope
from deepseek_tui.tools.memory_tools import MEMORY_PROVIDER_KEY


@pytest.mark.asyncio
async def test_remember_dual_writes_l1_when_provider_present(tmp_path: Path) -> None:
    cfg = Config(
        memory=MemoryConfig(
            enabled=True,
            smart=MemorySmartConfig(enabled=True, data_dir=str(tmp_path / "mem")),
        )
    )
    provider = NativeMemoryProvider(cfg, AsyncMock())
    await provider.start()
    mem_file = tmp_path / "memory.md"
    try:
        ctx = ToolContext(working_directory=tmp_path)
        ctx.services.add_named(
            MEMORY_PROVIDER_KEY,
            provider,
            owner="test",
            scope=ServiceScope.ENGINE,
        )
        ctx.metadata["runtime_thread_id"] = "thr_remember"

        import os

        os.environ["DEEPSEEK_MEMORY_PATH"] = str(mem_file)
        result = await RememberTool().execute(
            {"note": "Always run pytest before committing"},
            ctx,
        )
        assert result.success
        assert result.metadata.get("l1_memory_id")
        count = provider._store.count_memories_for_thread("thr_remember")
        assert count >= 1
    finally:
        await provider.stop()
        import os

        os.environ.pop("DEEPSEEK_MEMORY_PATH", None)
