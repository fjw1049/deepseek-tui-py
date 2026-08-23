"""Offline regression: the parent receives the child's report inline.

The completion payload is the only thing a parent turn is guaranteed to see
when a sub-agent finishes — it rides the ``SUBAGENT_DONE`` reminder into the
parent's context. It used to carry just the 240-character sidebar line, so a
parent that needed the actual findings had to spend a ``task_output`` round-trip
on every delegation, foreground ones included. The reminder's own budget was
already sized for a full report ("A child's report is the one tail item that can
be arbitrarily large"), so the report now rides along.

What has to keep holding:
  - the one-line summary stays first, so a skim still yields the outcome;
  - the sentinel stays machine-parseable and intact;
  - an oversized report is trimmed head-first (the contract puts ``### SUMMARY``
    first) and says how to recover the tail;
  - the payload never exceeds the reminder budget, so the reminder's own
    head+tail elision never fires and cannot cut the sentinel in half.
"""

from __future__ import annotations

import json
import re

import pytest

from deepseek_tui.engine import reminders
from deepseek_tui.tools.subagent.completion import (
    _MAX_PAYLOAD_CHARS,
    build_completion_payload,
)
from deepseek_tui.tools.subagent.types import (
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentType,
)

_SENTINEL_RE = re.compile(
    r"<deepseek:subagent\.done>(.*?)</deepseek:subagent\.done>", re.DOTALL
)

_REPORT = (
    "### SUMMARY\n"
    "已审计摘要链路，发现 bridge 全文被回喂给摘要器，外壳每轮叠加一次。\n\n"
    "### 证据\n"
    "- maintenance.py:228 — _record_compaction_summary 存的是整个 bridge\n"
    "- capacity.py:1055 — 作为 <previous-summary> 回放\n"
)


def _snap(
    result: str | None,
    *,
    agent_id: str = "a1",
    status: SubAgentStatus | None = None,
) -> SubAgentResult:
    return SubAgentResult(
        agent_id=agent_id,
        agent_type=SubAgentType.EXPLORE,
        assignment=SubAgentAssignment(objective="map the compaction path"),
        model="deepseek-chat",
        nickname="Blue",
        status=status or SubAgentStatus.completed(),
        result=result,
        steps_taken=7,
        duration_ms=4200,
    )


# --- the report reaches the parent ----------------------------------------


def test_full_report_is_inlined_for_the_parent() -> None:
    """No task_output round-trip needed to read what the child found."""
    payload = build_completion_payload(_snap(_REPORT))
    assert "maintenance.py:228" in payload
    assert "capacity.py:1055" in payload
    assert "### 证据" in payload


def test_summary_line_comes_before_the_report() -> None:
    """A parent that reads only the first line still learns the outcome."""
    payload = build_completion_payload(_snap(_REPORT))
    first_line = payload.splitlines()[0]
    assert "已审计摘要链路" in first_line
    assert payload.index(first_line) < payload.index("### 证据")


def test_sentinel_stays_parseable_with_a_report_appended() -> None:
    """The sentinel is machine-read; a trailing report must not disturb it."""
    payload = build_completion_payload(_snap(_REPORT))
    match = _SENTINEL_RE.search(payload)
    assert match is not None
    data = json.loads(match.group(1))
    assert data["agent_id"] == "a1"
    assert data["status"] == "completed"
    assert data["steps"] == 7
    assert 'agent(resume="a1")' in data["resume_hint"]


def test_report_is_not_duplicated_when_it_is_only_the_summary_line() -> None:
    """A one-line result already shows as the summary; repeating it is noise."""
    payload = build_completion_payload(_snap("Fixed it."))
    assert payload.count("Fixed it.") == 2  # summary line + sentinel JSON only


# --- bounds ---------------------------------------------------------------


def test_oversized_report_is_trimmed_head_first_with_a_recovery_pointer() -> None:
    big = "### SUMMARY\n" + ("详细结论。" * 3000)
    payload = build_completion_payload(_snap(big))

    assert len(payload) <= _MAX_PAYLOAD_CHARS
    # Head kept: the contract puts the conclusion first.
    assert "### SUMMARY" in payload
    # The elided tail is recoverable, and the payload says how.
    assert "task_output" in payload
    assert 'agent_id="a1"' in payload


def test_payload_stays_inside_the_reminder_budget() -> None:
    """Otherwise the reminder's head+tail elision fires and can split the
    sentinel across the omission marker, leaving it unparseable."""
    big = "### SUMMARY\n" + ("详细结论。" * 3000)
    payload = build_completion_payload(_snap(big))
    rendered = reminders.render(reminders.SUBAGENT_DONE, payload)

    assert "chars omitted from the middle" not in rendered
    assert _SENTINEL_RE.search(rendered) is not None


def test_empty_result_adds_no_report_block() -> None:
    payload = build_completion_payload(_snap(None))
    assert payload.startswith("Completed (explore)")
    assert "\n\n" not in payload


# --- terminal states other than success ------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        (SubAgentStatus.cancelled(), "Cancelled"),
        (SubAgentStatus.failed("boom"), "Failed: boom"),
    ],
    ids=["cancelled", "failed"],
)
def test_non_success_states_still_lead_with_their_status(
    status: SubAgentStatus, expected: str
) -> None:
    payload = build_completion_payload(_snap(_REPORT, status=status))
    assert payload.splitlines()[0] == expected
    assert _SENTINEL_RE.search(payload) is not None
