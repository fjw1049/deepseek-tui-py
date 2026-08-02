"""Unit contracts for the request ledger's render/parse round trip.

The ledger is re-rendered from its own previous rendering on every
compaction, so the round trip is not a convenience — it is the mechanism.
Anything that survives one pass but decays over five is a bug that only
shows up in long sessions, which is exactly where the ledger is supposed
to help.
"""

from __future__ import annotations

from deepseek_tui.engine.context_pressure import (
    PRIOR_REQUESTS_MAX_ENTRY_CHARS,
    collect_user_requests,
    format_user_requests_block,
    parse_user_requests_block,
)
from deepseek_tui.protocol.messages import Message, MessageOrigin


def _roundtrip(requests: list[str]) -> list[str]:
    return parse_user_requests_block(format_user_requests_block(requests))


def test_empty_input_renders_nothing() -> None:
    assert format_user_requests_block([]) == ""
    assert format_user_requests_block(["", "   "]) == ""


def test_plain_requests_round_trip_verbatim() -> None:
    requests = ["Build the parser", "Never use regexes", "Add a summary command"]
    assert _roundtrip(requests) == requests


def test_multiline_requests_keep_their_line_breaks() -> None:
    requests = ["Refactor the loader.\n\nKeep the public API unchanged."]
    assert _roundtrip(requests) == requests


def test_a_numbered_list_inside_a_request_is_not_split() -> None:
    """The failure mode indentation exists to prevent."""
    requests = [
        "Do these in order:\n1. drop the cache\n2. rebuild the index",
        "Then deploy",
    ]
    assert _roundtrip(requests) == requests


def test_rendering_is_idempotent_across_repeated_passes() -> None:
    requests = ["a" * 5_000, "short one", "b" * 100]
    once = format_user_requests_block(requests)
    twice = format_user_requests_block(parse_user_requests_block(once))
    assert once == twice


def test_an_oversized_request_is_clipped_at_both_ends() -> None:
    entry = "HEAD-MARKER " + ("filler " * 5_000) + " TAIL-MARKER"
    (parsed,) = _roundtrip([entry])
    assert len(parsed) <= PRIOR_REQUESTS_MAX_ENTRY_CHARS
    assert parsed.startswith("HEAD-MARKER")
    assert parsed.endswith("TAIL-MARKER")


def test_overflow_drops_the_middle_and_says_so() -> None:
    requests = [f"request number {i} " + "x" * 900 for i in range(40)]
    block = format_user_requests_block(requests, max_chars=5_000)

    assert "request number 0 " in block
    assert "request number 39 " in block
    assert "omitted for length" in block
    assert "request number 20 " not in block
    # The notice must not come back as if it were one of the user's requests.
    assert not any("omitted for length" in e for e in parse_user_requests_block(block))


def test_collect_merges_a_carrier_with_later_turns() -> None:
    """After a compaction the history is carrier + whatever came since."""
    carrier = Message.user(
        format_user_requests_block(["first ask", "second ask"]),
        origin=MessageOrigin.REQUEST_LEDGER,
    )
    messages = [
        carrier,
        Message.user("<user_query>\nsecond ask\n</user_query>", origin=MessageOrigin.REAL_USER),
        Message.assistant("done"),
        Message.user("<user_query>\nthird ask\n</user_query>", origin=MessageOrigin.REAL_USER),
    ]
    assert collect_user_requests(messages) == ["first ask", "second ask", "third ask"]


def test_collect_ignores_injected_reminders() -> None:
    reminder = Message.user(
        "<system-reminder>Keep the checklist current.</system-reminder>",
        origin=MessageOrigin.SYSTEM_REMINDER,
    )
    real = Message.user("<user_query>\nship it\n</user_query>", origin=MessageOrigin.REAL_USER)
    assert collect_user_requests([reminder, real]) == ["ship it"]
