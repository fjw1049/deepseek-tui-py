"""What the summarizer is shown, and what it is told about it.

The handoff is the only account of the archived work, so two things about
the summarizer's *input* are load-bearing: it must be able to see the end
of a long message (that is where conclusions live), and it must be able to
tell a severed message from a complete one. A silent head cut fails both.
"""

from __future__ import annotations

from typing import Any

import pytest

from deepseek_tui.engine.capacity import (
    _create_summary,
)
from deepseek_tui.engine.prompts import COMPACT_CONSUMER_HINT, COMPACT_TEMPLATE
from deepseek_tui.protocol.messages import Message, MessageOrigin, ToolUseBlock

_SMALL_MODEL = "gpt-4o"  # not in the large-context list: 800-char text limit


class _CapturingClient:
    def __init__(self) -> None:
        self.request: Any = None

    def stream_chat_completion(self, request: Any) -> Any:
        self.request = request

        async def _events() -> Any:
            return
            yield  # pragma: no cover — empty async generator

        return _events()


async def _summarizer_input(messages: list[Message]) -> str:
    client = _CapturingClient()
    await _create_summary(client, messages, _SMALL_MODEL)  # type: ignore[arg-type]
    return "\n".join(m.model_dump_json() for m in client.request.messages)


# --- what reaches the summarizer ------------------------------------------


@pytest.mark.asyncio
async def test_the_end_of_a_long_assistant_message_survives() -> None:
    """The decision is at the end; head-only truncation used to drop it."""
    reasoning = "I considered several options. " * 200
    verdict = "DECISION: use the existing CLI entrypoint, not a new binary."
    prompt = await _summarizer_input([Message.assistant(reasoning + verdict)])
    assert verdict in prompt


@pytest.mark.asyncio
async def test_the_end_of_a_long_tool_result_survives() -> None:
    """For a traceback the assertion line is last and is the whole point."""
    dump = "  File \"x.py\", line 1, in f\n" * 200
    assertion = "AssertionError: expected 3 rows, got 0"
    prompt = await _summarizer_input([Message.tool_result("t1", dump + assertion)])
    assert assertion in prompt


@pytest.mark.asyncio
async def test_full_middle_survives() -> None:
    prompt = await _summarizer_input([Message.assistant("q" * 20_000)])
    assert "q" * 20_000 in prompt
    assert "characters omitted" not in prompt


@pytest.mark.asyncio
async def test_the_edited_path_reaches_the_summarizer() -> None:
    """``### Done`` asks for landed patches; a bare tool name cannot name one."""
    msg = Message.assistant("")
    msg.content = [
        ToolUseBlock(
            id="1",
            name="edit_file",
            input={
                "path": "src/deepseek_tui/engine/capacity.py",
                "old_string": "x" * 420,
                "new_string": "y" * 510,
            },
        )
    ]
    prompt = await _summarizer_input([msg])
    assert "edit_file" in prompt
    assert "src/deepseek_tui/engine/capacity.py" in prompt
    assert "x" * 420 in prompt


@pytest.mark.asyncio
async def test_a_tool_the_renderer_has_never_heard_of_still_works() -> None:
    """No per-tool table, so MCP tools registered at runtime are covered."""
    msg = Message.assistant("")
    msg.content = [
        ToolUseBlock(id="1", name="acme__deploy", input={"env": "staging"})
    ]
    assert "acme__deploy" in await _summarizer_input([msg])
    assert "staging" in await _summarizer_input([msg])


# --- what the summarizer is told ------------------------------------------


def test_contract_forbids_attributing_harness_or_assistant_text_to_the_user() -> None:
    contract = COMPACT_TEMPLATE()
    assert "Harness:" in contract
    assert "Only `User:` lines are the human" in contract


def test_contract_tells_the_summarizer_the_ledger_covers_user_wording() -> None:
    """Otherwise it burns its word budget re-paraphrasing what is already safe."""
    contract = COMPACT_TEMPLATE()
    assert "verbatim" in contract
    assert "prior_user_requests" in contract


def _unwrapped(text: str) -> str:
    """Collapse newlines so an assertion tests wording, not line breaks.

    The contract is hand-wrapped prose; asserting on a phrase that happens to
    straddle a wrap point makes the test fail on reflow rather than on meaning.
    """
    return " ".join(text.split())


def test_contract_asks_for_an_anchored_next_step() -> None:
    contract = _unwrapped(COMPACT_TEMPLATE())
    assert "anchored" in contract
    # An anchor is only usable if it names something copied from the transcript.
    assert "copied exactly" in contract


def test_contract_asks_for_the_remaining_plan_not_just_one_step() -> None:
    """One anchored line resumes the next action; it does not carry the task.

    The compacting turn holds more context than any later turn will, so the
    decisions it has already settled have to be written down here or the next
    turn re-opens them.
    """
    contract = _unwrapped(COMPACT_TEMPLATE())
    assert "remaining steps in order" in contract


def test_contract_asks_what_the_session_never_established() -> None:
    """Assumptions replayed as facts are the failure mode compaction adds."""
    contract = COMPACT_TEMPLATE()
    assert "### Unknowns" in contract
    assert "unverified" in contract


def test_contract_lets_the_shape_follow_the_task() -> None:
    """Only Goal and Next step are validated, so only those are mandatory.

    Requiring every heading is what produced sections whose entire content was
    "None" — tokens spent to satisfy a template rather than to carry state.
    """
    contract = _unwrapped(COMPACT_TEMPLATE())
    assert "### Goal" in contract and "### Next step" in contract
    assert "Do not keep a heading just to write `None` under it" in contract
    # The old rule demanded the opposite; it must not survive anywhere.
    assert "Keep every heading" not in contract


def test_contract_is_first_person_notes_to_self() -> None:
    """A third-party report invites table-filling; notes-to-self invite thought."""
    contract = _unwrapped(COMPACT_TEMPLATE())
    assert "handoff note to yourself" in contract
    assert "first person" in contract


@pytest.mark.asyncio
async def test_the_contract_actually_reaches_the_summarizer() -> None:
    """The template is inert unless _create_summary sends it."""
    real = Message.user("ship it", origin=MessageOrigin.REAL_USER)
    prompt = await _summarizer_input([real])
    assert "Only `User:` lines are the human" in prompt


# --- what the consuming model is told -------------------------------------


def test_consumer_hint_names_the_ledger_and_gives_a_tiebreaker() -> None:
    """A summary saying "Constraints: None" next to a ledger listing one is
    the expected state, so the precedence rule has to be stated outright."""
    assert "<prior_user_requests>" in COMPACT_CONSUMER_HINT
    assert "verbatim requests win" in COMPACT_CONSUMER_HINT
    assert "Incorporate the last entry into the active task" in COMPACT_CONSUMER_HINT
