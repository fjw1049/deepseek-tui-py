"""Automated acceptance for MEMORY_INTEGRATION §6 batches C/D/F (no live LLM)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.memory.coordinator import MemoryCoordinator
from deepseek_tui.memory.coordinator import wrap_relevant_memories
from deepseek_tui.memory.seed import NativeMemoryProvider
from deepseek_tui.memory.coordinator import CaptureInput


def _smart_cfg(tmp_path: Path) -> Config:
    return Config(
        memory=MemoryConfig(
            enabled=True,
            mode="hybrid",
            smart=MemorySmartConfig(
                enabled=True,
                data_dir=str(tmp_path / "mem"),
                l1_every_n=99,
                capture_min_user_chars=20,
            ),
        )
    )


@pytest.mark.asyncio
async def test_batch_c_l0_grows_over_five_captures(tmp_path: Path) -> None:
    """Batch C: substantive turns append L0 JSONL."""
    cfg = _smart_cfg(tmp_path)
    provider = NativeMemoryProvider(cfg, AsyncMock())
    await provider.start()
    try:
        coord = MemoryCoordinator(cfg, provider)
        thread_id = "thr_c"
        workspace = str(tmp_path.resolve())
        for i in range(5):
            await coord.capture_after_turn(
                thread_id=thread_id,
                user_text=f"Please explain database connection pooling topic {i} in detail",
                workspace=workspace,
                messages=[
                    {
                        "role": "assistant",
                        "content": f"Pooling topic {i} reuses connections efficiently.",
                    }
                ],
                had_tool_calls=False,
                success=True,
            )
        l0_dir = tmp_path / "mem" / "l0"
        files = list(l0_dir.glob("*.jsonl"))
        assert files, "expected L0 jsonl files"
        body = files[0].read_text(encoding="utf-8")
        assert body.count('"role"') >= 5
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_batch_d_recall_surfaces_stored_fact(tmp_path: Path) -> None:
    """Batch D: recall returns L1 text for a new query on same workspace."""
    cfg = _smart_cfg(tmp_path)
    provider = NativeMemoryProvider(cfg, AsyncMock())
    await provider.start()
    try:
        workspace = str(tmp_path.resolve())
        provider._store.insert_memory(
            content="Staging API base URL is https://staging.example.com",
            mem_type="instruction",
            workspace=workspace,
            thread_id="thr_d",
            confidence=1.0,
        )
        coord = MemoryCoordinator(cfg, provider)
        recall = await coord.recall_for_turn(
            "thr_d",
            "What is the staging API URL?",
            workspace=workspace,
        )
        assert recall is not None
        assert "staging.example.com" in recall.l1_context
        wrapped = wrap_relevant_memories(
            "What is the staging API URL?",
            recall.l1_context,
        )
        assert "<relevant-memories>" in wrapped
        assert "staging.example.com" in wrapped
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_batch_f_short_confirmations_skip_capture(tmp_path: Path) -> None:
    """Batch F: three short confirmations without tools do not grow L0."""
    cfg = _smart_cfg(tmp_path)
    provider = NativeMemoryProvider(cfg, AsyncMock())
    await provider.start()
    try:
        coord = MemoryCoordinator(cfg, provider)
        thread_id = "thr_f"
        workspace = str(tmp_path.resolve())
        for text in ("好的", "继续", "嗯嗯"):
            await coord.capture_after_turn(
                thread_id=thread_id,
                user_text=text,
                workspace=workspace,
                messages=[{"role": "assistant", "content": "OK"}],
                had_tool_calls=False,
                success=True,
            )
        l0_dir = tmp_path / "mem" / "l0"
        if l0_dir.exists():
            assert not any(l0_dir.glob("*.jsonl"))
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_batch_f_short_with_tools_captures(tmp_path: Path) -> None:
    """Batch F: short user text with tool calls should capture."""
    cfg = _smart_cfg(tmp_path)
    provider = NativeMemoryProvider(cfg, AsyncMock())
    await provider.start()
    try:
        coord = MemoryCoordinator(cfg, provider)
        thread_id = "thr_f2"
        workspace = str(tmp_path.resolve())
        await coord.capture_after_turn(
            thread_id=thread_id,
            user_text="改成 async",
            workspace=workspace,
            messages=[{"role": "assistant", "content": "done"}],
            had_tool_calls=True,
            success=True,
        )
        assert list((tmp_path / "mem" / "l0").glob("*.jsonl"))
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_batch_c_l1_row_after_flush_with_stub_extractor(tmp_path: Path) -> None:
    """Batch C (L1): flush runs extraction and persists a row in memory.db."""
    cfg = Config(
        memory=MemoryConfig(
            enabled=True,
            mode="hybrid",
            smart=MemorySmartConfig(
                enabled=True,
                data_dir=str(tmp_path / "mem"),
                l1_every_n=99,
                capture_min_user_chars=20,
            ),
        )
    )
    provider = NativeMemoryProvider(cfg, AsyncMock())
    await provider.start()
    try:
        thread_id = "thr_c_l1"
        workspace = str(tmp_path.resolve())

        async def _stub_extract(
            tid: str, batch: list, **kwargs: object
        ) -> None:
            assert tid == thread_id
            provider._store.insert_memory(
                content="Team standardizes on pytest for all Python tests",
                mem_type="instruction",
                workspace=workspace,
                thread_id=tid,
                confidence=0.95,
            )

        assert provider._scheduler is not None
        provider._scheduler._run_extraction = _stub_extract  # type: ignore[method-assign]

        coord = MemoryCoordinator(cfg, provider)
        await coord.capture_after_turn(
            thread_id=thread_id,
            user_text="We always use pytest for Python tests in this repository",
            workspace=workspace,
            messages=[
                {
                    "role": "assistant",
                    "content": "Noted — pytest is the testing standard here.",
                }
            ],
            had_tool_calls=False,
            success=True,
        )
        await provider.flush_session(thread_id)
        assert provider._store.count_memories_for_thread(thread_id) >= 1
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_batch_e_same_session_id_recall_after_provider_restart(tmp_path: Path) -> None:
    """Batch E: same memory_thread_id after restart still recalls (TUI resume semantics)."""
    cfg = _smart_cfg(tmp_path)
    session_id = "sess_resume_e"
    workspace = str(tmp_path.resolve())

    provider = NativeMemoryProvider(cfg, AsyncMock())
    await provider.start()
    try:
        await provider.remember_instruction(
            "Always run pytest before committing code",
            workspace=workspace,
            thread_id=session_id,
        )
    finally:
        await provider.stop()

    provider2 = NativeMemoryProvider(cfg, AsyncMock())
    await provider2.start()
    try:
        coord = MemoryCoordinator(cfg, provider2)
        recall = await coord.recall_for_turn(
            session_id,
            "What testing framework before commit?",
            workspace=workspace,
        )
        assert recall is not None
        assert "pytest" in recall.l1_context.lower()
    finally:
        await provider2.stop()


def test_batch_e_session_json_restores_memory_mode(tmp_path: Path) -> None:
    """Session metadata.memory_mode is read on resume (TUI path)."""
    import json

    from deepseek_tui.tui.session_restore import session_metadata

    payload = {
        "model": "deepseek-chat",
        "messages": [],
        "metadata": {
            "memory_thread_id": "sess_abc",
            "memory_mode": "manual",
        },
    }
    path = tmp_path / "current.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = session_metadata(data, path=path)
    assert meta["memory_thread_id"] == "sess_abc"
    assert meta["memory_mode"] == "manual"

    class _Engine:
        memory_mode: str | None = "hybrid"

    eng = _Engine()
    mm = meta.get("memory_mode")
    if isinstance(mm, str) and mm.strip():
        eng.memory_mode = mm.strip().lower()
    assert eng.memory_mode == "manual"
