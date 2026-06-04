from pathlib import Path

from deepseek_tui.evolution.sinks.trajectory import TrajectorySink


def test_trajectory_sink_appends_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "traj.jsonl"
    sink = TrajectorySink(path)
    sink.observe(
        event="submit",
        record_id="abc",
        kind="memory_curate_add",
        source="main_tool",
        thread_id="t1",
        workspace="/w",
    )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "memory_curate_add" in lines[0]
