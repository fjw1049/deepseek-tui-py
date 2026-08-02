"""Every injection declares its envelope, position and provenance.

Two invariants live here.

An alert and a history substitute must not share an envelope. `<system-reminder>`
means "this is about now, act on it"; `<archived_context>` and `<cycle_carryover>`
mean "this is what already happened". While both wore the reminder tag there was
nothing to base a position rule on, so position was whatever the append order
happened to be.

And the envelope must never travel without the provenance tag. Wrapping and
tagging used to be two separate calls at each site, which is how four sites
ended up wrapped but untagged — invisible to everything that asks whether a
message came from the human.
"""

from __future__ import annotations

import inspect
import re

import pytest

from deepseek_tui.engine import reminders
from deepseek_tui.engine.context_pressure import is_synthetic_user_message
from deepseek_tui.engine.reminders import (
    REGISTRY,
    Envelope,
    Placement,
    ReminderSpec,
    reminder_message,
    render,
)
from deepseek_tui.protocol.messages import MessageOrigin

# --- the split ------------------------------------------------------------


def test_alerts_and_history_substitutes_use_different_envelopes() -> None:
    alerts = {s.envelope for s in REGISTRY if s.placement is not Placement.IN_HISTORY}
    history = {s.envelope for s in REGISTRY if s.placement is Placement.IN_HISTORY}
    assert alerts == {Envelope.ALERT}
    assert Envelope.ALERT not in history
    assert history, "the split is pointless if nothing is on the history side"


def test_a_seam_is_not_wrapped_as_a_reminder() -> None:
    seam = '<archived_context level="2" range="msg 1-9">gist</archived_context>'
    out = render(reminders.SOFT_SEAM, seam)
    assert "<system-reminder>" not in out
    # Self-enveloping: re-wrapping would bury the attributes the model reads
    # to know which stretch of history this stands for.
    assert out == seam


def test_a_cycle_seed_carries_its_own_tag() -> None:
    out = render(reminders.CYCLE_SEED, "[CYCLE STATE] mode: agent")
    assert out.startswith("<cycle_carryover>")
    assert out.endswith("</cycle_carryover>")
    assert "<system-reminder>" not in out


def test_alerts_still_get_the_reminder_envelope() -> None:
    out = render(reminders.STOP_HOOK_BLOCK, "a Stop hook blocked the turn")
    assert out.startswith("<system-reminder>")
    assert out.endswith("</system-reminder>")


def test_the_model_is_told_what_the_new_tags_mean() -> None:
    """A tag the system prompt never explains is a tag the model guesses at."""
    from pathlib import Path

    base = (
        Path(__file__).resolve().parents[2]
        / "src/deepseek_tui/prompts/base.md"
    ).read_text(encoding="utf-8")
    assert "<archived_context>" in base
    assert "<cycle_carryover>" in base


# --- envelope and provenance travel together -------------------------------


@pytest.mark.parametrize("spec", REGISTRY, ids=lambda s: s.name)
def test_every_injection_is_synthetic(spec: ReminderSpec) -> None:
    msg = reminder_message(spec, "body text")
    assert msg.origin is spec.origin
    assert is_synthetic_user_message(msg)


@pytest.mark.parametrize("spec", REGISTRY, ids=lambda s: s.name)
def test_no_injection_masquerades_as_the_human(spec: ReminderSpec) -> None:
    assert spec.origin is not MessageOrigin.REAL_USER


def test_double_wrapping_is_a_no_op() -> None:
    once = render(reminders.LSP_DIAGNOSTICS, "2 errors")
    assert render(reminders.LSP_DIAGNOSTICS, once) == once


def test_an_empty_body_produces_nothing() -> None:
    assert render(reminders.LSP_DIAGNOSTICS, "   ") == ""


# --- ceilings --------------------------------------------------------------


def test_an_oversized_body_keeps_both_ends_and_says_so() -> None:
    spec = reminders.SUBAGENT_DONE
    assert spec.max_chars is not None
    body = "HEAD" + ("x" * spec.max_chars * 3) + "TAIL"
    out = render(spec, body)
    assert "HEAD" in out and "TAIL" in out
    assert "chars omitted from the middle" in out
    assert len(out) < len(body)


def test_a_body_under_the_ceiling_is_untouched() -> None:
    out = render(reminders.SUBAGENT_DONE, "### SUMMARY\nfound it")
    assert "omitted" not in out
    assert "### SUMMARY\nfound it" in out


# --- names and priorities are meaningful -----------------------------------


def test_names_are_unique() -> None:
    names = [s.name for s in REGISTRY]
    assert len(names) == len(set(names))


def test_the_stop_hook_gets_the_last_word() -> None:
    """It fires because the model just tried to end the turn; anything
    appended after it would be arguing with a decision already made."""
    tail = [s for s in REGISTRY if s.placement is Placement.TAIL]
    assert reminders.STOP_HOOK_BLOCK.priority == max(s.priority for s in tail)


def test_the_general_re_anchor_yields_to_specific_alerts() -> None:
    """Drift is a standing reminder, not a reaction — it must not sit
    between a fresh diagnostic and the model's attention."""
    assert (
        reminders.LONG_SESSION_DRIFT.priority < reminders.LSP_DIAGNOSTICS.priority
    )


def test_the_turn_loop_appends_tail_reminders_in_declared_order() -> None:
    """The declared priority is only worth something if the code follows it.

    These two are appended back to back in `_run_conversation`, which is the
    one place the relative order of two tail reminders is a live choice
    rather than a consequence of when they fire.
    """
    from deepseek_tui.engine.orchestrator.core import Engine

    source = inspect.getsource(Engine._run_conversation)
    drift = source.index("_maybe_inject_long_session_reminder")
    lsp = source.index("_flush_pending_lsp_diagnostics")
    declared = (
        reminders.LONG_SESSION_DRIFT.priority < reminders.LSP_DIAGNOSTICS.priority
    )
    assert (drift < lsp) is declared


# --- no site bypasses the registry -----------------------------------------


def test_injection_sites_go_through_the_registry() -> None:
    """`wrap_system_reminder` survives for neutralization tests and legacy
    inference; a production injection using it directly is a site that can
    forget the origin tag, or wrap something that is not an alert."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "deepseek_tui"
    allowed = {"engine/context_pressure.py"}
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        rel = path.relative_to(src).as_posix()
        if rel in allowed:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if re.search(r"\bwrap_system_reminder\s*\(", line):
                offenders.append(f"{rel}:{lineno}")
    assert not offenders, (
        "use reminders.reminder_message with a registered spec: "
        + ", ".join(offenders)
    )
