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
    _elide_middle,
    _render_tool_args,
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
    return client.request.messages[0].text_content()


# --- the elision primitive -------------------------------------------------


def test_short_text_is_untouched() -> None:
    assert _elide_middle("hello", 100) == "hello"


def test_elision_keeps_both_ends_and_respects_the_cap() -> None:
    text = "HEAD" + "x" * 5_000 + "TAIL"
    out = _elide_middle(text, 400)
    assert len(out) <= 400
    assert out.startswith("HEAD")
    assert out.endswith("TAIL")


def test_elision_reports_how_much_it_dropped() -> None:
    out = _elide_middle("y" * 1_000, 300)
    assert "characters omitted" in out


def test_a_cap_too_small_for_the_marker_degrades_instead_of_failing() -> None:
    out = _elide_middle("z" * 100, 8)
    assert len(out) <= 8


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
async def test_truncation_is_visible_not_silent() -> None:
    prompt = await _summarizer_input([Message.assistant("q" * 20_000)])
    assert "characters omitted" in prompt


# --- which action a tool call was -----------------------------------------


def test_identifying_arguments_render_in_full() -> None:
    out = _render_tool_args({"path": "src/engine/capacity.py", "replace_all": False})
    assert "path=src/engine/capacity.py" in out
    assert "replace_all=False" in out


def test_payload_arguments_collapse_to_their_size() -> None:
    """The body is recoverable from disk; its size is not worth the tokens."""
    out = _render_tool_args({"path": "a.py", "content": "z" * 9_000})
    assert "path=a.py" in out
    assert "content=<9000 chars>" in out
    assert "zzzz" not in out


def test_no_arguments_renders_empty() -> None:
    assert _render_tool_args({}) == ""


def test_many_arguments_stay_within_budget() -> None:
    out = _render_tool_args({f"k{i}": f"v{i}" * 10 for i in range(40)})
    assert len(out) < 700
    assert out.endswith("...")


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
    assert "edit_file(" in prompt
    assert "path=src/deepseek_tui/engine/capacity.py" in prompt
    assert "old_string=<420 chars>" in prompt


@pytest.mark.asyncio
async def test_a_tool_the_renderer_has_never_heard_of_still_works() -> None:
    """No per-tool table, so MCP tools registered at runtime are covered."""
    msg = Message.assistant("")
    msg.content = [
        ToolUseBlock(id="1", name="acme__deploy", input={"env": "staging"})
    ]
    assert "acme__deploy(env=staging)" in await _summarizer_input([msg])


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


def test_contract_asks_for_an_anchored_next_step() -> None:
    assert "Anchor it" in COMPACT_TEMPLATE()


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
    assert "last entry is the current request" in COMPACT_CONSUMER_HINT
