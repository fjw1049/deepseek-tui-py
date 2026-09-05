"""Pressure on the estimate path must count the system prompt and tools.

``measure_context_pressure`` has always accepted ``system_prompt`` / ``tools``,
but every production call site omitted them, so the estimate path — the first
turn of every session, and any turn before a provider ``input_tokens`` lands —
silently ignored several thousand tokens of static prefix. Every threshold in
the ladder (L0 prune, rewrite, cycle) read low as a result.

The real-token path is unaffected: the provider's ``input_tokens`` already
counts the prefix, so adding it again would double-count.
"""

from __future__ import annotations

import pytest

from deepseek_tui.config.providers import set_context_window_override
from deepseek_tui.engine.capacity import (
    CompactionConfig,
    should_compact,
    should_l0_prune,
)
from deepseek_tui.engine.context_pressure import (
    estimate_request_tokens,
    measure_context_pressure,
)
from deepseek_tui.engine.orchestrator.maintenance import SessionMaintenanceMixin
from deepseek_tui.protocol.messages import Message, MessageOrigin

# A deliberately small window so the static prefix — not the message bulk —
# is the term that decides every threshold.
MODEL = "pressure-contract-test-model"
WINDOW = 20_000


@pytest.fixture(autouse=True)
def _restore_context_window_override() -> None:
    """Other config tests rebuild the process-global override registry."""
    set_context_window_override(MODEL, WINDOW)

# ~18k tokens: over the 0.75 rewrite ratio on its own, so any assertion below
# that flips is attributable to the prefix and nothing else.
_BIG_SYSTEM_PROMPT = "You are a coding agent. " * 3000
_BIG_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": f"tool_{i}",
            "description": "d" * 400,
            "parameters": {"type": "object", "properties": {}},
        },
    }
    for i in range(30)
]


def _messages() -> list[Message]:
    return [Message.user("short turn") for _ in range(4)]


def test_estimate_path_counts_system_prompt_and_tools() -> None:
    bare = measure_context_pressure(MODEL, _messages())
    withprefix = measure_context_pressure(
        MODEL, _messages(), system_prompt=_BIG_SYSTEM_PROMPT, tools=_BIG_TOOLS
    )

    assert bare.source == "estimate"
    assert withprefix.source == "estimate"
    assert withprefix.tokens > bare.tokens


def test_real_token_path_ignores_them_to_avoid_double_counting() -> None:
    real = measure_context_pressure(
        MODEL,
        _messages(),
        real_input_tokens=50_000,
        system_prompt=_BIG_SYSTEM_PROMPT,
        tools=_BIG_TOOLS,
    )

    assert real.source == "real"
    assert real.tokens == 50_000


def test_real_token_path_accounts_for_content_added_since_measurement() -> None:
    baseline = _messages()
    baseline_estimate = estimate_request_tokens(
        baseline, system_prompt=_BIG_SYSTEM_PROMPT, tools=_BIG_TOOLS
    )
    current = [*baseline, Message.tool_result("call-1", "x" * 20_000)]

    pressure = measure_context_pressure(
        MODEL,
        current,
        real_input_tokens=50_000,
        real_input_estimate=baseline_estimate,
        system_prompt=_BIG_SYSTEM_PROMPT,
        tools=_BIG_TOOLS,
    )

    assert pressure.source == "real"
    assert pressure.tokens > 50_000


def test_should_compact_forwards_the_static_prefix() -> None:
    """The prefix alone can carry the ratio over the rewrite threshold."""
    msgs = [Message.user("EARLY " + ("x" * 40)) for _ in range(30)]
    msgs += [Message.user(f"recent-{i}") for i in range(4)]
    cfg = CompactionConfig(
        rewrite_ratio=0.75, auto_floor_ratio=0.20, keep_recent_tokens=50
    )

    without = should_compact(msgs, cfg, model=MODEL)
    with_prefix = should_compact(
        msgs,
        cfg,
        model=MODEL,
        system_prompt=_BIG_SYSTEM_PROMPT,
        tools=_BIG_TOOLS,
    )

    assert not without
    assert with_prefix, "system prompt + tools must count toward rewrite ratio"


def test_should_l0_prune_forwards_the_static_prefix() -> None:
    msgs = [Message.user("x" * 200) for _ in range(10)]
    cfg = CompactionConfig(l0_prune_enabled=True, l0_prune_ratio=0.50)

    assert not should_l0_prune(model=MODEL, messages=msgs, config=cfg)
    assert should_l0_prune(
        model=MODEL,
        messages=msgs,
        config=cfg,
        system_prompt=_BIG_SYSTEM_PROMPT,
        tools=_BIG_TOOLS,
    )


def test_every_pressure_consumer_in_the_turn_loop_is_wired() -> None:
    """Accepting the kwargs is half the fix — the call sites must pass them.

    F24 was not a missing parameter; it was five call sites that never
    supplied one that already existed. Guard the wiring, not just the
    signature: both values are in scope for all of ``_run_conversation``.
    """
    import inspect
    import re

    from deepseek_tui.engine.orchestrator.core import Engine

    source = inspect.getsource(Engine._run_conversation)
    consumers = (
        "_maybe_advance_cycle",
        "_maybe_l0_prune_tool_results",
        "should_compact",
        "_maybe_inject_long_session_reminder",
    )
    for name in consumers:
        call = re.search(rf"{name}\((.*?)\n\s*\)", source, re.DOTALL)
        assert call is not None, f"{name} call not found in _run_conversation"
        args = call.group(1)
        assert "system_prompt=system_prompt" in args, f"{name} drops system_prompt"
        assert "tools=tools" in args, f"{name} drops tools"
        if name == "should_compact":
            assert "real_input_estimate=" in args


class _Stub(SessionMaintenanceMixin):
    def __init__(self) -> None:
        self.last_real_input_tokens = 0


def test_long_session_reminder_sees_the_static_prefix() -> None:
    """Same messages, same real tokens (none) — only the prefix differs."""
    quiet: list[Message] = [Message.user("hi")]
    _Stub()._maybe_inject_long_session_reminder(quiet, MODEL)
    assert not [m for m in quiet if m.origin is MessageOrigin.SYSTEM_REMINDER]

    loaded: list[Message] = [Message.user("hi")]
    _Stub()._maybe_inject_long_session_reminder(
        loaded,
        MODEL,
        system_prompt=_BIG_SYSTEM_PROMPT,
        tools=_BIG_TOOLS,
    )
    assert [m for m in loaded if m.origin is MessageOrigin.SYSTEM_REMINDER]
