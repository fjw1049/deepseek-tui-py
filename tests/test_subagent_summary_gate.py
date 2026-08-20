"""Offline regression: the sub-agent output gate accepts real reports and
rejects content-free ones, in both Simplified Chinese and English.

The gate used to check only that ``### SUMMARY`` appeared somewhere, so a
sub-agent that answered ``### SUMMARY\\n Done.`` satisfied the contract; that
stub then reached the parent as the whole deliverable (the sidebar line and the
``subagent.done`` sentinel both derive from this body).

Length alone cannot separate the two classes. Measured against real reports a
complete Chinese summary runs 14-43 characters while the stubs worth rejecting
run 4-14, so the bands overlap: any single threshold that rejects ``已完成。``
also rejects ``审计完成，未发现阻塞性问题。``. The gate therefore keys on
substance — a count, a path, an identifier, a verdict — and falls back to a
script-scaled length bound only when no such token is present.
"""

from __future__ import annotations

import pytest

from deepseek_tui.tools.subagent.completion import summary_section_text
from deepseek_tui.tools.subagent.loop import _has_summary_section


def _report(body: str) -> str:
    return f"### SUMMARY\n{body}"


# --- reports that must be accepted ----------------------------------------

ACCEPTED = [
    pytest.param(
        "最终报告：115 个测试文件，649 个用例，覆盖率良好。",
        id="zh-with-counts",
    ),
    pytest.param(
        "已修复 bridge 递归叠加问题，改动在 maintenance.py:228。",
        id="zh-with-path",
    ),
    pytest.param(
        "PASS。执行 pytest -q，退出码 0，共 649 个用例通过。",
        id="zh-verifier-verdict",
    ),
    # No checkable token at all, but plainly a real finding: the length bound
    # for a CJK body has to sit below this.
    pytest.param("审计完成，未发现阻塞性问题。", id="zh-prose-no-token"),
    pytest.param(
        "Fixed the recursive stacking in maintenance.py:228; verified by test.",
        id="en-with-path",
    ),
    # A verifier's whole job is the verdict; four characters is a complete
    # answer here and must not be mistaken for a stub.
    pytest.param("FAIL", id="en-verdict-only"),
    pytest.param("Reviewed 3 modules, no blockers.", id="en-with-count"),
    pytest.param(
        "Reviewed the auth module and found no blocking issues.",
        id="en-prose-no-token",
    ),
]


@pytest.mark.parametrize("body", ACCEPTED)
def test_real_summaries_are_accepted(body: str) -> None:
    assert _has_summary_section(_report(body)) is True


# --- reports that must be rejected ----------------------------------------

REJECTED = [
    pytest.param("做完了。", id="zh-stub"),
    pytest.param("已完成。", id="zh-stub-2"),
    pytest.param("任务完成。", id="zh-stub-3"),
    pytest.param("Done.", id="en-stub"),
    pytest.param("Task complete.", id="en-stub-2"),
    pytest.param("All good.", id="en-stub-3"),
    pytest.param("Finished the task.", id="en-stub-4"),
    pytest.param("", id="empty-body"),
]


@pytest.mark.parametrize("body", REJECTED)
def test_content_free_summaries_are_rejected(body: str) -> None:
    """Rejection costs one tools-off retry, which is the cheap direction."""
    assert _has_summary_section(_report(body)) is False


# --- structural cases ------------------------------------------------------


def test_missing_heading_is_rejected() -> None:
    assert _has_summary_section("I did the thing and it worked.") is False


def test_none_and_empty_are_rejected() -> None:
    assert _has_summary_section(None) is False
    assert _has_summary_section("") is False


def test_heading_with_only_a_following_section_is_rejected() -> None:
    """An empty SUMMARY followed by another heading has no body to read."""
    assert _has_summary_section("### SUMMARY\n\n### RISKS\nNone.") is False


def test_body_stops_at_the_next_heading() -> None:
    """The gate must not borrow substance from a later section.

    Without the boundary, a stub SUMMARY would pass on a path that appears
    under a different heading further down.
    """
    text = "### SUMMARY\n做完了。\n\n### EVIDENCE\n- src/deepseek_tui/engine/turn.py:42"
    assert summary_section_text(text) == "做完了。"
    assert _has_summary_section(text) is False


def test_gate_and_sidebar_read_the_same_body() -> None:
    """``summarize_subagent_result`` shows what the gate approved.

    They share one extractor precisely so a body cannot pass the gate and then
    render as something else in the parent's sidebar.
    """
    body = "已修复 bridge 递归叠加问题，改动在 maintenance.py:228。"
    text = _report(body)
    assert _has_summary_section(text) is True
    assert summary_section_text(text) == body
