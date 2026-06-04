from deepseek_tui.evolution.signals import detect_signals
from deepseek_tui.post_turn.evidence import TurnEvidence


def test_detect_user_correction_signal() -> None:
    ev = TurnEvidence(
        thread_id="t",
        user_text="不对，应该改用 async",
        workspace="/w",
        messages=[],
        had_tool_calls=False,
        success=True,
        tool_rounds=0,
    )
    signals = detect_signals(ev, ev.messages)
    assert signals.user_correction
