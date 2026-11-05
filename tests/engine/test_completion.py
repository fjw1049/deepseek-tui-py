"""The harness reports what it knows at turn end and leaves the verdict to the model."""

from types import SimpleNamespace

from deepseek_tui.engine.completion import (
    COMPLETION_NOTE_KEY,
    TurnFacts,
    without_completion_note,
)


def record(facts, tool, arguments, success=True, error=""):
    facts.record(tool, arguments, success=success, error=error)


def test_plain_reply_has_no_outcome_and_no_note():
    facts = TurnFacts()
    assert facts.outcome([], []) is None
    assert facts.note([], []) is None


def test_a_later_success_of_the_same_call_clears_the_failure():
    facts = TurnFacts()
    record(facts, "exec_shell", {"command": "pytest"}, success=False, error="1 failed")
    assert facts.outcome([], [])["status"] == "partial"
    record(facts, "exec_shell", {"command": "pytest"})
    assert facts.outcome([], [])["status"] == "completed_with_evidence"
    assert facts.note([], []) is None


def test_a_different_success_does_not_clear_a_failure():
    facts = TurnFacts()
    record(facts, "exec_shell", {"command": "pytest"}, success=False, error="1 failed")
    record(facts, "exec_shell", {"command": "ls"})
    assert "pytest: 1 failed" in facts.note([], [])


def test_failed_reads_are_exploration_not_unfinished_work():
    facts = TurnFacts()
    record(facts, "read_file", {"path": "maybe.txt"}, success=False, error="not found")
    assert facts.failures == {}


def test_edits_with_no_run_in_the_turn_say_nothing():
    # A writing task never ran anything, so nothing can have gone stale.
    facts = TurnFacts()
    record(facts, "write_file", {"path": "report.md"})
    assert facts.outcome([], [])["status"] == "completed_unverified"
    assert facts.note([], []) is None


def test_edit_after_the_last_run_is_reported_until_the_next_run():
    facts = TurnFacts()
    record(facts, "exec_shell", {"command": "pytest"})
    record(facts, "edit_file", {"path": "app.py"})
    assert "app.py" in facts.note([], [], "en")
    assert facts.outcome([], [])["status"] == "completed_unverified"
    record(facts, "exec_shell", {"command": "pytest"})
    assert facts.note([], []) is None


def test_files_a_command_writes_are_its_output_not_a_later_edit():
    facts = TurnFacts()
    record(facts, "write_file", {"path": "draft.txt"})
    record(facts, "exec_shell", {"command": "python build.py"})
    assert facts.edited_after_run == []


def test_a_document_edited_after_the_last_run_is_not_reported():
    facts = TurnFacts()
    record(facts, "exec_shell", {"command": "python check.py"})
    record(facts, "write_file", {"path": "邮件说明.txt"})
    record(facts, "edit_file", {"path": "建议.MD"})
    assert facts.note([], []) is None


def test_a_different_browser_ref_does_not_clear_a_failure():
    # Action names alone cannot establish that a failed target was retried.
    facts = TurnFacts()
    record(facts, "browser_use", {"action": "click", "ref": "e11"}, success=False, error="x")
    record(facts, "browser_use", {"action": "click", "ref": "e42"})
    assert len(facts.failures) == 1


def test_a_browser_failure_is_reported_in_words_not_json():
    facts = TurnFacts()
    record(facts, "browser_use", {"action": "drag", "ref": "e1"}, success=False,
           error='{"success": false, "content": "target_obscured", "artifact": null}')
    assert "browser_use drag" in facts.note([], [])
    assert ": target_obscured" in facts.note([], [])
    assert "{" not in facts.note([], [])


def test_browser_state_is_read_only_when_the_browser_was_used():
    browser = SimpleNamespace(
        state=lambda thread: {"unresolved": ["op"], "dialog": {"type": "alert"}},
        runs={"t": SimpleNamespace(unresolved={}, assistance="help", owner="agent")},
    )
    metadata = {"browser_service": browser, "runtime_thread_id": "t"}
    facts = TurnFacts()
    assert facts.pending(metadata) == []
    record(facts, "browser_use", {"action": "observe"})
    assert facts.pending(metadata) == [
        "browser_unresolved", "browser_dialog", "browser_assistance"]


def test_unknown_desktop_outcome_makes_the_turn_partial():
    session = SimpleNamespace(unresolved=True, outside_change=False, reset_reason="")
    facts = TurnFacts()
    record(facts, "cua_js", {"code": "click()"})
    pending = facts.pending({"cua_session": session})
    assert pending == ["cua_unresolved"]
    assert facts.outcome(pending, [])["status"] == "partial"
    assert "桌面操作结果未知" in facts.note(pending, [])


def test_stopping_after_desktop_input_without_a_closing_summary_is_open():
    session = SimpleNamespace(unresolved=False, outside_change=False, reset_reason="")
    metadata = {"cua_session": session}
    acted = {"cua_trace": {"ready": True, "actions": [{"action": "click", "ok": True}]}}
    looked = {"cua_trace": {"ready": True, "actions": [{"action": "getAXState", "observe": True}]}}
    facts = TurnFacts()
    facts.record("cua_js", {"code": "await app.getAXState()"}, success=True, metadata=looked)
    assert facts.pending(metadata) == []
    facts.record("cua_js", {"code": "await app.click(3)"}, success=True, metadata=acted)
    assert facts.pending(metadata) == ["cua_completion_summary_missing"]
    facts.record("cua_js", {"completion_summary": "Saved the file"}, success=True)
    # Looking again after the summary does not reopen it.
    facts.record("cua_js", {"code": "await app.getAXState()"}, success=True, metadata=looked)
    assert facts.pending(metadata) == []
    facts.record("cua_js", {"code": "await app.click(4)"}, success=True, metadata=acted)
    facts.assistance_requests.append({"reason": "Touch ID"})
    # A handoff to the person is its own open state; the summary comes after it.
    assert facts.pending(metadata) == []


def test_a_problem_alone_still_reaches_the_user():
    facts = TurnFacts()
    assert facts.outcome([], ["limit"])["status"] == "partial"
    assert "limit" in facts.note([], ["limit"])


def test_long_lists_stay_bounded():
    facts = TurnFacts(ran=True, edited_after_run=[f"f{i}" for i in range(9)])
    note = facts.note([], [], "en")
    assert "f4" in note and "f5" not in note and "+4" in note


def test_note_never_reads_as_the_models_words():
    note = TurnFacts(ran=True, edited_after_run=["a"]).note([], [])
    text = f"答案\n\n{note}"
    assert without_completion_note(text, {COMPLETION_NOTE_KEY: note}) == "答案"
    assert without_completion_note("答案", None) == "答案"
    assert without_completion_note(note, {COMPLETION_NOTE_KEY: note}) == ""
