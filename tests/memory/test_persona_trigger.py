from __future__ import annotations

from deepseek_tui.memory.native.checkpoint import CheckpointManager, MemoryCheckpoint
from deepseek_tui.memory.native.persona_trigger import PersonaTrigger


def _scene_file(tmp_path) -> None:  # noqa: ANN001
    blocks = tmp_path / "scene_blocks"
    blocks.mkdir(parents=True, exist_ok=True)
    (blocks / "work.md").write_text("# Work\n", encoding="utf-8")


def test_persona_trigger_explicit_request(tmp_path) -> None:
    CheckpointManager(tmp_path).write(
        MemoryCheckpoint(
            request_persona_update=True,
            persona_update_reason="重大偏好变化",
        )
    )

    result = PersonaTrigger(tmp_path, interval=50).should_generate()

    assert result.should
    assert "重大偏好变化" in result.reason


def test_persona_trigger_cold_start_after_scene_extraction(tmp_path) -> None:
    _scene_file(tmp_path)
    CheckpointManager(tmp_path).write(MemoryCheckpoint(scenes_processed=1))

    result = PersonaTrigger(tmp_path, interval=50).should_generate()

    assert result.should
    assert "首次冷启动" in result.reason


def test_persona_trigger_recovers_missing_persona_body(tmp_path) -> None:
    _scene_file(tmp_path)
    (tmp_path / "persona.md").write_text("## Scene navigation (L2)\n", encoding="utf-8")
    CheckpointManager(tmp_path).write(
        MemoryCheckpoint(scenes_processed=3, last_persona_at=123)
    )

    result = PersonaTrigger(tmp_path, interval=50).should_generate()

    assert result.should
    assert "恢复" in result.reason


def test_persona_trigger_memory_threshold(tmp_path) -> None:
    CheckpointManager(tmp_path).write(
        MemoryCheckpoint(last_persona_at=123, memories_since_last_persona=50)
    )

    result = PersonaTrigger(tmp_path, interval=50).should_generate()

    assert result.should
    assert "达到阈值" in result.reason
