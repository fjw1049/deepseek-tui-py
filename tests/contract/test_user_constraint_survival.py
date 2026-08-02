"""A constraint stated mid-session must survive compaction and cycling.

This was the Phase 2 acceptance baseline for F1. It is now the regression
guard for the user-request ledger that closed it.

Why the constraint deliberately contains no file path: the working-set pin in
``context.py`` keeps a message only when its text happens to contain a path
that is currently in the working set (F7). A path-free constraint is the
honest case — a policy the user stated once, in prose, that the harness has
no string coincidence to save it by.

Why the fake summarizer omits the constraint: the contract under test is that
the harness preserves user constraints *regardless* of what the summarizer
chooses to keep. A summarizer that happens to retain it proves nothing — it
sees the history head/tail-truncated and drifts across iterated re-summaries.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

import pytest

from deepseek_tui.engine.capacity import CompactionConfig, compact_messages_safe
from deepseek_tui.engine.context_pressure import (
    collect_user_requests,
    find_last_real_user_query,
)
from deepseek_tui.engine.cycle import CycleBriefing, build_seed_messages
from deepseek_tui.protocol.messages import Message, MessageOrigin

BANNED_REGEX_RULE = (
    "Never use regular expressions anywhere in this project — "
    "the team banned them after the outage last quarter."
)
FIRST_GOAL = "Build a CLI that parses our application logs."
LATEST_GOAL = "Now add a summary command that counts errors by hour."

# A valid handoff (passes validate_compaction_summary) that mentions only the
# newest goal — exactly what a drifting summarizer produces.
_FORGETFUL_SUMMARY = (
    "### Goal\nAdd a summary command to the log CLI.\n\n"
    "### Constraints\nNone recorded.\n\n"
    "### Progress\n#### Done\nParser skeleton.\n"
    "#### In Progress\nSummary command.\n#### Blocked\nNone\n\n"
    "### Key Decisions\nUse the existing CLI entrypoint.\n\n"
    "### Next step\nWire the summary subcommand.\n"
)


class _ForgetfulSummarizer:
    def stream_chat_completion(self, request: Any) -> Any:
        async def _events() -> Any:
            yield type("Delta", (), {"text": _FORGETFUL_SUMMARY})()

        return _events()


def _session() -> list[Message]:
    """Twelve turns; the constraint is stated on turn 3 and never repeated."""
    messages: list[Message] = [
        Message.user(
            f"<user_query>\n{FIRST_GOAL}\n</user_query>",
            origin=MessageOrigin.REAL_USER,
        ),
        Message.assistant("Starting on the parser."),
        Message.user(
            f"<user_query>\n{BANNED_REGEX_RULE}\n</user_query>",
            origin=MessageOrigin.REAL_USER,
        ),
    ]
    for i in range(8):
        messages.append(Message.assistant(f"Working on step {i}. " + "detail " * 40))
        messages.append(Message.tool_result(f"t{i}", f"step {i} output " * 40))
    messages.append(
        Message.user(
            f"<user_query>\n{LATEST_GOAL}\n</user_query>",
            origin=MessageOrigin.REAL_USER,
        )
    )
    return messages


async def _compact(messages: list[Message]):
    return await compact_messages_safe(  # type: ignore[arg-type]
        _ForgetfulSummarizer(),
        messages,
        CompactionConfig(enabled=True, keep_recent_tokens=50),
        model_override="deepseek-chat",
    )


def _seeds_for(messages: list[Message], cycle: int) -> str:
    """Mirror ``_maybe_advance_cycle``'s call, which the guard below pins."""
    seeds = build_seed_messages(
        structured_state_block="mode: agent",
        briefing=CycleBriefing(
            cycle=cycle,
            timestamp=1_700_000_000,
            briefing_text="Continuing the log CLI work.",
            token_estimate=10,
        ),
        pending_user_message=find_last_real_user_query(messages),
        prior_requests=collect_user_requests(messages),
    )
    return "\n".join(s["content"] for s in seeds)


@pytest.mark.asyncio
async def test_constraint_survives_rewrite_compaction() -> None:
    result = await _compact(_session())

    assert result.success
    transcript = "\n".join(m.text_content() for m in result.messages)
    assert LATEST_GOAL in transcript, "the newest goal is replayed today"
    assert BANNED_REGEX_RULE in transcript, (
        "a constraint from turn 3 must outlive the first compaction"
    )


def test_constraint_survives_cycle_advance() -> None:
    seeded = _seeds_for(_session(), cycle=1)
    assert LATEST_GOAL in seeded
    assert BANNED_REGEX_RULE in seeded, (
        "cycle seeds must carry earlier constraints, not just the last goal"
    )


@pytest.mark.asyncio
async def test_constraint_survives_compaction_then_cycle() -> None:
    """The compound path: rewrite first, then a cycle boundary on the result.

    This is what makes the ledger self-sustaining. The cycle step does not
    receive the original turns — it only sees the compacted transcript, so
    the constraint reaches the seed solely because the carrier the first
    compaction left behind can be read back.
    """
    compacted = await _compact(_session())
    assert compacted.success

    assert BANNED_REGEX_RULE in "\n".join(collect_user_requests(compacted.messages))
    assert BANNED_REGEX_RULE in _seeds_for(compacted.messages, cycle=2)


@pytest.mark.asyncio
async def test_repeated_compaction_does_not_stack_carriers() -> None:
    """Re-compacting absorbs the old ledger instead of appending a second."""
    once = await _compact(_session())
    twice = await _compact(list(once.messages) + _session())
    assert twice.success

    carriers = [
        m for m in twice.messages if m.origin is MessageOrigin.REQUEST_LEDGER
    ]
    assert len(carriers) == 1
    body = carriers[0].text_content()
    assert body.count(BANNED_REGEX_RULE) == 1


def test_the_ledger_is_not_mistaken_for_a_fresh_request() -> None:
    """The carrier holds user words but must not read as the current turn."""
    seeded_first_goal_only = build_seed_messages(
        structured_state_block=None,
        briefing=CycleBriefing(
            cycle=1,
            timestamp=1_700_000_000,
            briefing_text="b",
            token_estimate=1,
        ),
        pending_user_message=LATEST_GOAL,
        prior_requests=[FIRST_GOAL, BANNED_REGEX_RULE, LATEST_GOAL],
    )
    ledger = next(
        s for s in seeded_first_goal_only if s.get("origin") == "request_ledger"
    )
    messages = [Message.user(ledger["content"], origin=MessageOrigin.REQUEST_LEDGER)]
    assert find_last_real_user_query(messages) is None


def test_cycle_advance_passes_the_ledger() -> None:
    """The rendering is only half of it — the call site must supply entries.

    Wiring, not signature: ``build_seed_messages`` accepting the argument is
    inert if ``_maybe_advance_cycle`` never fills it, and that omission would
    leave every test above passing while the running harness still forgets.
    """
    from deepseek_tui.engine.orchestrator.maintenance import SessionMaintenanceMixin

    source = inspect.getsource(SessionMaintenanceMixin._maybe_advance_cycle)
    call = re.search(r"build_seed_messages\((.*?)\n\s*\)", source, re.DOTALL)
    assert call is not None, "build_seed_messages call not found"
    assert "prior_requests=collect_user_requests(" in call.group(1)
