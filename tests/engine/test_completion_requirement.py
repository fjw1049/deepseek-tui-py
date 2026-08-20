"""CompletionRequirement is a policy, not a role-specific gate.

Callers decide what ``satisfied`` means. This module only answers whether
to inject a reminder and run again, and it accepts the last result when
the budget is gone.
"""

from __future__ import annotations

from deepseek_tui.engine.completion_requirement import CompletionRequirement

REQ = CompletionRequirement(name="test", reminder="try again", max_retries=2)


def test_recovers_only_while_unsatisfied_and_under_budget() -> None:
    assert REQ.should_recover(satisfied=False, fired=0) is True
    assert REQ.should_recover(satisfied=False, fired=1) is True
    assert REQ.should_recover(satisfied=False, fired=2) is False


def test_satisfied_or_abort_never_recovers() -> None:
    assert REQ.should_recover(satisfied=True, fired=0) is False
    assert REQ.should_recover(satisfied=False, fired=0, abort=True) is False


def test_zero_retries_means_no_requirement() -> None:
    none = CompletionRequirement(name="off", reminder="", max_retries=0)
    assert none.should_recover(satisfied=False, fired=0) is False
