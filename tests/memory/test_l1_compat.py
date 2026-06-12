from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.memory.seed import NativeMemoryProvider


def _config(tmp_path: Path) -> Config:
    return Config(
        memory=MemoryConfig(
            enabled=True,
            smart=MemorySmartConfig(enabled=True, data_dir=str(tmp_path / "mem")),
        )
    )


@pytest.mark.asyncio
async def test_l1_records_jsonl_written_for_insert(tmp_path: Path) -> None:
    provider = NativeMemoryProvider(_config(tmp_path), AsyncMock())
    await provider.start()
    try:
        mem_id = await provider.remember_instruction(
            "Always run pytest before committing",
            workspace="/ws",
            thread_id="thr",
        )
        assert mem_id

        records = sorted((tmp_path / "mem" / "records").glob("*.jsonl"))
        assert records
        row = json.loads(records[0].read_text(encoding="utf-8").splitlines()[0])
        assert row["id"] == mem_id
        assert row["type"] == "instruction"
        assert row["priority"] == 100
        assert row["scene_name"] == "manual remember"
        assert row["sessionKey"] == "thr"
        assert row["workspace"] == "/ws"
        assert row["action"] == "store"
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_l1_update_decision_replaces_target_row(tmp_path: Path) -> None:
    provider = NativeMemoryProvider(_config(tmp_path), AsyncMock())
    await provider.start()
    try:
        old_id = provider._store_l1_decision(
            action="store",
            content="User prefers unittest for tests",
            mem_type="instruction",
            workspace="/ws",
            thread_id="thr",
            confidence=0.8,
            priority=80,
        )
        assert old_id

        new_id = provider._store_l1_decision(
            action="update",
            content="User prefers pytest for tests",
            mem_type="instruction",
            workspace="/ws",
            thread_id="thr",
            confidence=0.95,
            priority=95,
            target_ids=[old_id],
        )
        assert new_id
        assert provider._store.get_memory(old_id) is None
        row = provider._store.get_memory(new_id)
        assert row is not None
        assert row.content == "User prefers pytest for tests"

        records = sorted((tmp_path / "mem" / "records").glob("*.jsonl"))
        lines = records[0].read_text(encoding="utf-8").splitlines()
        update_row = json.loads(lines[-1])
        assert update_row["action"] == "update"
        assert update_row["target_ids"] == [old_id]
    finally:
        await provider.stop()
