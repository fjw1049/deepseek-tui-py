"""The prefix probe must accuse the right unit — and only when it should.

A diagnostic that cries wolf is worse than none: it would send someone hunting
for cache damage the provider never saw. So the two halves matter equally here,
that a real rewrite is caught and that wire-invisible churn is not.
"""

from __future__ import annotations

from deepseek_tui.engine.capacity import (
    L0_HARD_CLEAR_MIN_RECLAIM,
    ToolPruneConfig,
    prune_old_tool_results,
)
from deepseek_tui.engine.prefix_probe import (
    describe_break,
    fingerprint_request,
    first_divergence,
)
from deepseek_tui.protocol.messages import (
    Message,
    MessageOrigin,
    Role,
    TextBlock,
    ToolUseBlock,
)

SYSTEM = "You are a coding agent."
TOOLS = [{"type": "function", "function": {"name": "exec_shell"}}]


def _history() -> list[Message]:
    return [
        Message.user("find the bug"),
        Message.assistant_with_tools(
            [ToolUseBlock(id="call-1", name="exec_shell", input={"command": "pytest"})]
        ),
        Message.tool_result("call-1", "F" * 5_000),
        Message.assistant("found it"),
    ]


def test_identical_requests_have_identical_fingerprints() -> None:
    assert fingerprint_request(SYSTEM, _history(), TOOLS) == fingerprint_request(
        SYSTEM, _history(), TOOLS
    )


def test_appending_a_turn_is_not_a_break() -> None:
    """The common case: the provider serves the whole previous payload."""
    messages = _history()
    before = fingerprint_request(SYSTEM, messages, TOOLS)
    messages.append(Message.user("now fix it"))

    assert first_divergence(before, fingerprint_request(SYSTEM, messages, TOOLS)) is None


def test_rewriting_an_old_body_breaks_at_that_message() -> None:
    messages = _history()
    before = fingerprint_request(SYSTEM, messages, TOOLS)
    messages[2] = Message.tool_result("call-1", "[Tool result omitted — too old]")

    break_at = first_divergence(before, fingerprint_request(SYSTEM, messages, TOOLS))

    assert break_at == 3, "slot 0 is the static prefix, so message[2] lands at 3"
    assert describe_break(break_at, messages) == "message[2] role=tool origin=-"


def test_static_prefix_churn_breaks_at_slot_zero() -> None:
    messages = _history()
    before = fingerprint_request(SYSTEM, messages, TOOLS)

    reordered = [{"function": {"name": "exec_shell"}, "type": "function"}]
    break_at = first_divergence(before, fingerprint_request(SYSTEM, messages, reordered))

    assert break_at == 0, "tool schemas share the system prompt's cache lifetime"
    assert describe_break(break_at, messages) == "static_prefix(system_prompt|tools)"


def test_origin_alone_is_not_a_break() -> None:
    """``origin`` never reaches the wire, so re-tagging must stay silent.

    Guards against the probe blaming context assembly for cache damage the
    provider cannot possibly have seen.
    """
    messages = _history()
    before = fingerprint_request(SYSTEM, messages, TOOLS)
    messages[0] = Message.user("find the bug", origin=MessageOrigin.REQUEST_LEDGER)

    assert first_divergence(before, fingerprint_request(SYSTEM, messages, TOOLS)) is None


def test_break_reports_the_earliest_rewrite() -> None:
    """Everything after the first mismatch is re-billed, so only it matters."""
    messages = _history()
    before = fingerprint_request(SYSTEM, messages, TOOLS)
    messages[0] = Message.user("different question")
    messages[3] = Message.assistant("different answer")

    assert first_divergence(before, fingerprint_request(SYSTEM, messages, TOOLS)) == 1


def test_reminder_injection_is_attributed_to_its_origin() -> None:
    """Inserting mid-history shifts every later unit — the probe should say so."""
    messages = _history()
    before = fingerprint_request(SYSTEM, messages, TOOLS)
    messages.insert(
        2,
        Message(
            role=Role.USER,
            content=[TextBlock(text="<system-reminder>drifting</system-reminder>")],
            origin=MessageOrigin.SYSTEM_REMINDER,
        ),
    )

    break_at = first_divergence(before, fingerprint_request(SYSTEM, messages, TOOLS))

    assert break_at == 3
    assert describe_break(break_at, messages) == (
        "message[2] role=user origin=system_reminder"
    )


def test_probe_catches_the_l0_regression_it_was_built_for() -> None:
    """End-to-end sanity: the eager clear it found should still be visible.

    Ties the diagnostic to the bug that motivated it — if batching ever
    regresses, this fails alongside the L0 contract test rather than leaving the
    probe silently unable to see the thing it exists to see.
    """
    settled: list[Message] = []
    for n in range(20):
        settled.extend(
            [
                Message.user(f"u{n}"),
                Message.assistant_with_tools(
                    [ToolUseBlock(id=f"call-{n}", name="exec_shell", input={})]
                ),
                Message.tool_result(f"call-{n}", "Z" * 3_000),
                Message.assistant(f"a{n}"),
            ]
        )
    batched = [m.model_copy(deep=True) for m in settled]
    before_eager = fingerprint_request(SYSTEM, settled, TOOLS)
    before_batched = fingerprint_request(SYSTEM, batched, TOOLS)

    prune_old_tool_results(settled, config=ToolPruneConfig())
    prune_old_tool_results(
        batched,
        config=ToolPruneConfig(hard_clear_min_reclaim=L0_HARD_CLEAR_MIN_RECLAIM * 100),
    )

    eager_break = first_divergence(
        before_eager, fingerprint_request(SYSTEM, settled, TOOLS)
    )
    batched_break = first_divergence(
        before_batched, fingerprint_request(SYSTEM, batched, TOOLS)
    )

    assert eager_break is not None
    assert "role=tool" in describe_break(eager_break, settled)
    assert batched_break is None, "a deferred clear must leave the prefix intact"


class _Probe:
    """Only what ``Engine._log_prefix_break`` touches, called unbound."""

    def __init__(self) -> None:
        self._prefix_digests: list[str] = []


def test_engine_logs_the_break_with_its_culprit(caplog) -> None:
    """The wiring, not just the arithmetic — the round must actually report."""
    import logging

    from deepseek_tui.engine.orchestrator.core import Engine

    probe = _Probe()
    messages = _history()
    with caplog.at_level(logging.INFO, logger="deepseek_tui.engine.orchestrator.core"):
        Engine._log_prefix_break(probe, 0, SYSTEM, messages, TOOLS)
        assert "prefix_break" not in caplog.text, "nothing to compare on round 0"

        messages[2] = Message.tool_result("call-1", "[Tool result omitted — too old]")
        Engine._log_prefix_break(probe, 1, SYSTEM, messages, TOOLS)

    assert "prefix_break round=1 at=3/5" in caplog.text
    assert "culprit=message[2] role=tool" in caplog.text
