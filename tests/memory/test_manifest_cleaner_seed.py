from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.memory.store import MemoryCleaner
from deepseek_tui.memory.seed import ManifestMismatchError, MemoryManifest
from deepseek_tui.memory.seed import NativeMemoryProvider
from deepseek_tui.memory.seed import seed_memory_from_file
from deepseek_tui.memory.store import MemoryStore


def test_manifest_records_and_rejects_different_store_binding(tmp_path: Path) -> None:
    manifest = MemoryManifest(tmp_path)
    smart = MemorySmartConfig(enabled=True, data_dir=str(tmp_path))

    manifest.ensure_store_binding(store_path=tmp_path / "store" / "memory.db", config=smart)
    data = manifest.read()
    assert data["store_binding"]["backend"] == "sqlite"

    with pytest.raises(ManifestMismatchError):
        manifest.ensure_store_binding(store_path=tmp_path / "other.db", config=smart)


def test_cleaner_removes_expired_l1_and_l0(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "store" / "memory.db")
    store.open()
    try:
        old_id = store.insert_memory(
            content="old deployment fact",
            mem_type="episodic",
            workspace="/ws",
            thread_id="thr",
            confidence=1.0,
        )
        new_id = store.insert_memory(
            content="new deployment fact",
            mem_type="episodic",
            workspace="/ws",
            thread_id="thr",
            confidence=1.0,
        )
        assert old_id and new_id
        old_ts = int(time.time() * 1000) - 10 * 86_400_000
        store._conn_required().execute(
            "UPDATE memories SET created_at = ? WHERE id = ?",
            (old_ts, old_id),
        )
        store._conn_required().commit()

        l0_dir = tmp_path / "l0"
        l0_dir.mkdir()
        (l0_dir / "thr.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"timestamp": old_ts, "content": "old"}, ensure_ascii=False),
                    json.dumps(
                        {
                            "timestamp": int(time.time() * 1000),
                            "content": "new",
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        result = MemoryCleaner(tmp_path, store).run(retention_days=3)
        assert result.l1_deleted == 1
        assert store.get_memory(old_id) is None
        assert store.get_memory(new_id) is not None
        assert "old" not in (l0_dir / "thr.jsonl").read_text(encoding="utf-8")
    finally:
        store.close()


@pytest.mark.asyncio
async def test_seed_imports_history_and_records_manifest(tmp_path: Path) -> None:
    cfg = Config(
        memory=MemoryConfig(
            enabled=True,
            smart=MemorySmartConfig(
                enabled=True,
                data_dir=str(tmp_path / "mem"),
                l1_every_n=999,
            ),
        )
    )
    provider = NativeMemoryProvider(cfg, AsyncMock())
    await provider.start()
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "thread_id": "seed-thread",
                        "messages": [
                            {"role": "user", "content": "Remember pytest preference"},
                            {"role": "assistant", "content": "Noted pytest preference"},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        result = await seed_memory_from_file(
            provider,
            seed_path,
            workspace="/ws",
            flush=False,
        )
        assert result.sessions == 1
        assert result.turns == 1
        l0_file = tmp_path / "mem" / "l0" / "seed-thread.jsonl"
        assert l0_file.is_file()
        manifest = MemoryManifest(tmp_path / "mem").read()
        assert manifest["seed_runs"][-1]["source"] == str(seed_path.resolve())
    finally:
        await provider.stop()


def test_manifest_config_change_does_not_break(tmp_path: Path) -> None:
    """Changing non-critical config (e.g. thresholds) should NOT raise."""
    manifest = MemoryManifest(tmp_path)
    manifest.ensure_store_binding(store_path=tmp_path / "store.db", config="v1")
    manifest.ensure_store_binding(store_path=tmp_path / "store.db", config="v2_changed")


def test_l0_recorder_excludes_tool_from_l1_eligible(tmp_path: Path) -> None:
    from deepseek_tui.memory.l0 import L0Recorder
    from deepseek_tui.memory.store import MemoryStore

    store = MemoryStore(tmp_path / "store.db")
    store.open()
    try:
        recorder = L0Recorder(tmp_path / "l0", store)
        eligible = recorder.append_turn(
            "thread-1",
            user_text="hello",
            messages=[
                {"role": "assistant", "content": "hi back"},
                {"role": "tool", "content": "tool output data is here"},
            ],
            workspace="/ws",
        )
        assert any(m["role"] == "user" for m in eligible)
        assert any(m["role"] == "assistant" for m in eligible)
        assert not any(m["role"] == "tool" for m in eligible)
        l0_content = (tmp_path / "l0" / "thread-1.jsonl").read_text(encoding="utf-8")
        assert "tool output data" in l0_content
    finally:
        store.close()


def test_l0_cursor_skips_already_recorded_messages(tmp_path: Path) -> None:
    from deepseek_tui.memory.l0 import L0Recorder
    from deepseek_tui.memory.store import MemoryStore

    now = int(time.time() * 1000)
    store = MemoryStore(tmp_path / "store.db")
    store.open()
    try:
        recorder = L0Recorder(tmp_path / "l0", store)
        recorder.append_turn(
            "thread-1",
            user_text="first",
            messages=[{"role": "assistant", "content": "first reply", "timestamp": now + 1}],
            workspace="/ws",
        )
        eligible = recorder.append_turn(
            "thread-1",
            user_text="second",
            messages=[
                {"role": "assistant", "content": "first reply", "timestamp": now + 1},
                {"role": "assistant", "content": "second reply", "timestamp": now + 5000},
            ],
            workspace="/ws",
        )
        assert any("second reply" in m["content"] for m in eligible)
        assert not any(
            "first reply" in m["content"] for m in eligible if m["role"] == "assistant"
        )
    finally:
        store.close()


def test_scene_index_workspace_isolation(tmp_path: Path) -> None:
    from deepseek_tui.memory.l2 import SceneStore

    scenes = SceneStore(tmp_path / "data")
    blocks = tmp_path / "data" / "scene_blocks"
    blocks.mkdir(parents=True, exist_ok=True)
    (blocks / "ws1_scene.md").write_text("# ws1 scene\n", encoding="utf-8")
    scenes._sync_index_from_files(workspace="/ws1")

    (blocks / "ws2_scene.md").write_text("# ws2 scene\n", encoding="utf-8")
    scenes._sync_index_from_files(workspace="/ws2")

    nav1 = scenes.navigation_markdown(workspace="/ws1")
    nav2 = scenes.navigation_markdown(workspace="/ws2")
    assert "ws1_scene" in nav1
    assert "ws2_scene" not in nav1
    assert "ws2_scene" in nav2
