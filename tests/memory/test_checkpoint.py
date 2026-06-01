from __future__ import annotations

from deepseek_tui.memory.native.checkpoint import CheckpointManager


def test_checkpoint_keeps_runner_and_pipeline_state_separate(tmp_path) -> None:
    manager = CheckpointManager(tmp_path)

    manager.update_runner_state("thr", last_scene_name="Deployment")
    manager.update_thread("thr", l1_processed=3, l2_cursor="cursor-1")

    checkpoint = manager.read()
    assert checkpoint.runner_states["thr"].last_scene_name == "Deployment"
    assert checkpoint.pipeline_states["thr"].l2_cursor == "cursor-1"
    assert checkpoint.total_processed == 3

    raw = manager.path.read_text(encoding="utf-8")
    assert '"runner_states"' in raw
    assert '"pipeline_states"' in raw
