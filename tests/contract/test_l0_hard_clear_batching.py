"""L0's hard clear must not break the KV prefix once per turn.

Tool-result ages tick with every user turn, so in a long session a fresh batch
crosses ``hard_clear_age_turns`` each turn. Clearing it rewrites bodies that sit
deep inside the payload the provider has already cached, and prefix caching
matches from the start — so the whole tail gets re-billed at full price for a
few thousand chars of window relief.

Measured on a 25-turn tool-heavy session: clearing eagerly held the cacheable
prefix at ~27% of the payload; batching the clears lifted it to ~58% for ~7%
more average payload, about a third off effective input billing. These tests
lock that behaviour in — both the deferral itself and the escape hatch at high
pressure, where the window matters more than the cache.
"""

from __future__ import annotations

from deepseek_tui.client.chat_messages import build_chat_messages
from deepseek_tui.config.providers import context_window_for_model
from deepseek_tui.engine.capacity import (
    L0_HARD_CLEAR_MIN_RECLAIM,
    CompactionConfig,
    ToolPruneConfig,
    prune_old_tool_results,
)
from deepseek_tui.engine.orchestrator.maintenance import SessionMaintenanceMixin
from deepseek_tui.protocol.messages import Message, ToolResultBlock, ToolUseBlock

MODEL = "deepseek-v4-pro"  # 1M window, so real_input_tokens sets the ratio
SETTLED_BODY_CHARS = 3_000  # what a soft trim leaves behind


def _turn(n: int, body: str) -> list[Message]:
    return [
        Message.user(f"u{n}"),
        Message.assistant_with_tools(
            [ToolUseBlock(id=f"call-{n}", name="exec_shell", input={"command": "ls"})]
        ),
        Message.tool_result(f"call-{n}", body),
        Message.assistant(f"a{n}"),
    ]


def _session(turns: int, *, fat_turns: int) -> list[Message]:
    """A settled session: the oldest ``fat_turns`` carry soft-trimmed bodies."""
    messages: list[Message] = []
    for n in range(turns):
        body = ("Z" * SETTLED_BODY_CHARS) if n < fat_turns else "short"
        messages.extend(_turn(n, body))
    return messages


def _bodies(messages: list[Message]) -> list[str]:
    return [
        block.content or ""
        for message in messages
        for block in message.content
        if isinstance(block, ToolResultBlock)
    ]


def _wire(messages: list[Message]) -> list[dict[str, object]]:
    return build_chat_messages(messages, system_prompt="SYS", model=MODEL)


def test_hard_clear_waits_until_the_batch_is_worth_a_prefix_break() -> None:
    """One newly aged body is not worth re-billing the tail."""
    messages = _session(14, fat_turns=1)
    before = _bodies(messages)

    changed = prune_old_tool_results(
        messages,
        config=ToolPruneConfig(hard_clear_min_reclaim=L0_HARD_CLEAR_MIN_RECLAIM),
    )

    assert changed == 0
    assert _bodies(messages) == before, "deferring a clear must not touch any body"


def test_hard_clear_fires_once_enough_is_reclaimable() -> None:
    """Same threshold, but now the batch pays for the break."""
    messages = _session(20, fat_turns=10)

    changed = prune_old_tool_results(
        messages,
        config=ToolPruneConfig(hard_clear_min_reclaim=L0_HARD_CLEAR_MIN_RECLAIM),
    )

    assert changed > 0
    assert any("omitted" in body for body in _bodies(messages))


def test_threshold_is_opt_in() -> None:
    """The default stays eager, so callers that want batching must ask."""
    assert ToolPruneConfig().hard_clear_min_reclaim == 0

    messages = _session(14, fat_turns=1)
    assert prune_old_tool_results(messages, config=ToolPruneConfig()) > 0
    assert any("omitted" in body for body in _bodies(messages))


def test_batching_keeps_the_payload_prefix_reusable() -> None:
    """The point of the whole exercise, checked at the wire.

    Prefix caching needs the next request to *start with* the last one. Step one
    turn forward under each policy and ask exactly that question — a pure append
    is a full cache hit, anything else re-bills from the first changed message.
    """
    batched_config = ToolPruneConfig(hard_clear_min_reclaim=L0_HARD_CLEAR_MIN_RECLAIM)
    eager = _session(14, fat_turns=1)
    batched = _session(14, fat_turns=1)
    prune_old_tool_results(eager, config=ToolPruneConfig())
    prune_old_tool_results(batched, config=batched_config)
    eager_before, batched_before = _wire(eager), _wire(batched)

    eager.extend(_turn(14, "Z" * SETTLED_BODY_CHARS))
    batched.extend(_turn(14, "Z" * SETTLED_BODY_CHARS))
    prune_old_tool_results(eager, config=ToolPruneConfig())
    prune_old_tool_results(batched, config=batched_config)
    eager_after, batched_after = _wire(eager), _wire(batched)

    assert batched_after[: len(batched_before)] == batched_before, (
        "batching should leave the settled history untouched, so the new turn "
        "reaches the provider as a pure append"
    )
    assert eager_after[: len(eager_before)] != eager_before, (
        "guard the premise: clearing eagerly is what rewrites cached history"
    )


class _Stub(SessionMaintenanceMixin):
    """Just enough Engine for ``_maybe_l0_prune_tool_results``."""

    def __init__(self, real_input_tokens: int) -> None:
        self.last_real_input_tokens = real_input_tokens
        self.compaction_config = CompactionConfig()


def test_engine_defers_at_l0_pressure_but_not_in_the_rewrite_band() -> None:
    """High pressure is about to break the prefix anyway — stop protecting it.

    Only ``real_input_tokens`` differs between the two runs, so the flip is
    attributable to pressure and nothing else. Token counts are derived from the
    model's own window rather than hardcoded, because config can override it.
    """
    window = context_window_for_model(MODEL)

    moderate = _session(14, fat_turns=1)
    changed = _Stub(int(window * 0.60))._maybe_l0_prune_tool_results(moderate, MODEL)
    assert changed == 0, "0.60 ratio: keep the cache, the batch is too small"

    urgent = _session(14, fat_turns=1)
    changed = _Stub(int(window * 0.80))._maybe_l0_prune_tool_results(urgent, MODEL)
    assert changed > 0, "0.80 ratio: reclaim the window regardless of the cache"
    assert any("omitted" in body for body in _bodies(urgent))
