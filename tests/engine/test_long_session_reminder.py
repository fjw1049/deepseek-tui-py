"""Long-session drift reminder injection (SessionMaintenanceMixin)."""

from __future__ import annotations

from deepseek_tui.config.providers import context_window_for_model
from deepseek_tui.engine.orchestrator.maintenance import SessionMaintenanceMixin
from deepseek_tui.engine.prompts import LONG_SESSION_REMINDER
from deepseek_tui.protocol.messages import Message, MessageOrigin

MODEL = "test-model"
WINDOW = context_window_for_model(MODEL)


class _Stub(SessionMaintenanceMixin):
    def __init__(self, real_tokens: int) -> None:
        self.last_real_input_tokens = real_tokens


def _reminders(messages: list[Message]) -> list[Message]:
    return [m for m in messages if m.origin is MessageOrigin.SYSTEM_REMINDER]


def test_below_first_threshold_no_injection():
    stub = _Stub(int(WINDOW * 0.30))
    messages = [Message.user("hi")]
    stub._maybe_inject_long_session_reminder(messages, MODEL)
    assert _reminders(messages) == []


def test_injects_once_past_first_threshold():
    stub = _Stub(int(WINDOW * 0.45))
    messages = [Message.user("hi")]
    stub._maybe_inject_long_session_reminder(messages, MODEL)
    injected = _reminders(messages)
    assert len(injected) == 1
    assert LONG_SESSION_REMINDER in injected[0].text_content()
    assert injected[0].text_content().startswith("<system-reminder>")
    # Same pressure again — no duplicate.
    stub._maybe_inject_long_session_reminder(messages, MODEL)
    assert len(_reminders(messages)) == 1


def test_reinjects_after_step_growth():
    stub = _Stub(int(WINDOW * 0.45))
    messages = [Message.user("hi")]
    stub._maybe_inject_long_session_reminder(messages, MODEL)
    assert len(_reminders(messages)) == 1
    # Growth below the step — still one copy.
    stub.last_real_input_tokens = int(WINDOW * 0.55)
    stub._maybe_inject_long_session_reminder(messages, MODEL)
    assert len(_reminders(messages)) == 1
    # Growth past the step — second copy.
    stub.last_real_input_tokens = int(WINDOW * 0.70)
    stub._maybe_inject_long_session_reminder(messages, MODEL)
    assert len(_reminders(messages)) == 2


def test_tracker_resets_when_context_shrinks():
    stub = _Stub(int(WINDOW * 0.80))
    messages = [Message.user("hi")]
    stub._maybe_inject_long_session_reminder(messages, MODEL)
    assert len(_reminders(messages)) == 1
    # Compaction shrank the context below the last injection point but
    # still above the first threshold — the archived copy is replaced.
    stub.last_real_input_tokens = int(WINDOW * 0.45)
    fresh: list[Message] = [Message.user("hi again")]
    stub._maybe_inject_long_session_reminder(fresh, MODEL)
    assert len(_reminders(fresh)) == 1
