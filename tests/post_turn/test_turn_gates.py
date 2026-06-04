from deepseek_tui.evolution.signals import EvolutionSignals
from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.post_turn.gates import GateConfig, passes_base_gate, should_capture, should_review


def _evidence(**kwargs: object) -> TurnEvidence:
    base = dict(
        thread_id="t1",
        user_text="hello world enough chars",
        workspace="/tmp/ws",
        messages=[],
        had_tool_calls=False,
        success=True,
    )
    base.update(kwargs)
    return TurnEvidence(**base)  # type: ignore[arg-type]


def test_passes_base_gate_skips_slash() -> None:
    ev = _evidence(user_text="/compact")
    assert not passes_base_gate(ev, GateConfig())


def test_should_capture_with_tools() -> None:
    ev = _evidence(user_text="ok", had_tool_calls=True)
    assert should_capture(ev, GateConfig(min_chars=20))


def test_should_review_flush_mode() -> None:
    ev = _evidence(flush_mode=True, success=False)
    assert should_review(
        ev,
        cfg=GateConfig(),
        scheduler_due=False,
        signals=EvolutionSignals(),
    )


def test_should_review_requires_signal_or_scheduler() -> None:
    ev = _evidence()
    assert not should_review(
        ev,
        cfg=GateConfig(),
        scheduler_due=False,
        signals=EvolutionSignals(),
    )
    assert should_review(
        ev,
        cfg=GateConfig(),
        scheduler_due=True,
        signals=EvolutionSignals(),
    )
