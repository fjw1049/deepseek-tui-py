from datetime import date

from deepseek_tui.engine.compatibility_audit import report
from deepseek_tui.engine.dispatch import normalize_legacy_tool_call


def test_real_alias_log_report_preserves_compatibility(tmp_path, caplog):
    with caplog.at_level("INFO", logger="deepseek_tui.engine.dispatch"):
        assert normalize_legacy_tool_call("task_read", {"task_id": "a"}) == (
            "task_output",
            {"task_id": "a"},
        )
    path = tmp_path / "events.log"
    path.write_text(caplog.text)
    result = report([path])
    route = next(r for r in result["routes"] if r["name"] == "task_read")
    assert route["calls"] == 1 and route["status"] == "used"
    assert not result["automatic_removal"]
    assert all(r["status"] != "eligible_for_manual_review" for r in result["routes"])


def test_zero_calls_need_complete_observation_window(tmp_path):
    path = tmp_path / "events.log"
    path.write_text("")
    kwargs = {"start": date(2026, 11, 11), "end": date(2026, 12, 12), "today": date(2026, 12, 12)}
    assert report([path], **kwargs)["routes"][0]["status"] == "insufficient_evidence"
    assert (
        report([path], complete_coverage=True, **kwargs)["routes"][0]["status"]
        == "eligible_for_manual_review"
    )
    kwargs["end"] = date(2026, 11, 11)
    assert (
        report([path], complete_coverage=True, **kwargs)["routes"][0]["status"]
        == "insufficient_evidence"
    )
