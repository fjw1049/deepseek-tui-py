import json

from deepseek_tui.memory.l0 import L0Recorder
from deepseek_tui.memory.store import MemoryStore


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


def test_l0_sanitizes_injected_context_and_records_session_fields(tmp_path) -> None:
    store = MemoryStore(tmp_path / "db.sqlite")
    store.open()
    l0 = L0Recorder(tmp_path / "l0", store)
    try:
        rows = l0.append_turn(
            "thr_x",
            user_text=(
                "<user-persona>private persona</user-persona>\n"
                "<relevant-memories>old memory</relevant-memories>\n"
                "真正应该录入的用户事实 data:image/png;base64,AAAA"
            ),
            messages=[],
            workspace="/ws",
        )
        assert len(rows) == 1
        assert rows[0]["content"] == "真正应该录入的用户事实"
        assert rows[0]["sessionKey"] == "thr_x"
        assert rows[0]["sessionId"] == ""
        assert rows[0]["recordedAt"]

        raw = (tmp_path / "l0" / "thr_x.jsonl").read_text(encoding="utf-8")
        persisted = json.loads(raw)
        assert "private persona" not in persisted["content"]
        assert "data:image" not in persisted["content"]
    finally:
        store.close()
