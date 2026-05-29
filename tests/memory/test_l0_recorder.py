from deepseek_tui.memory.native.l0_recorder import L0Recorder
from deepseek_tui.memory.native.store import MemoryStore


def test_l0_appends_jsonl_and_updates_cursor(tmp_path) -> None:
    store = MemoryStore(tmp_path / "db.sqlite")
    store.open()
    l0 = L0Recorder(tmp_path / "l0", store)
    try:
        first = l0.append_turn(
            "thr_x",
            user_text="这是一段足够长的用户消息用于测试录制",
            messages=[],
            workspace="/ws",
        )
        assert len(first) == 1
        path = tmp_path / "l0" / "thr_x.jsonl"
        lines_after_first = path.read_text(encoding="utf-8").count("\n")

        second = l0.append_turn(
            "thr_x",
            user_text="这是一段足够长的用户消息用于测试录制",
            messages=[],
            workspace="/ws",
        )
        assert len(second) == 1
        lines_after_second = path.read_text(encoding="utf-8").count("\n")
        assert lines_after_second == lines_after_first + 1
    finally:
        store.close()
