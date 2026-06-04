from deepseek_tui.post_turn.evidence import TurnEvidence


def test_turn_evidence_capture_input() -> None:
    ev = TurnEvidence(
        thread_id="t",
        user_text="hello",
        workspace="/w",
        messages=[{"role": "user", "content": "hi"}],
        had_tool_calls=True,
        success=True,
    )
    inp = ev.to_capture_input()
    assert inp.thread_id == "t"
    assert inp.had_tool_calls is True
