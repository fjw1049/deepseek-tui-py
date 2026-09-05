"""Provider-neutral prompt-size accounting.

DeepSeek reports ``prompt_tokens`` as the whole prompt with hit/miss as its
internal split; Anthropic reports ``input_tokens`` as the uncached remainder
only. Reading ``input_tokens`` directly collapsed a 147K prompt behind a warm
Anthropic-style prefix cache down to ~200 tokens, which froze the /context
meter and kept the compaction ladder permanently idle.
"""

from __future__ import annotations

import pytest

from deepseek_tui.client.pricing import calculate_turn_cost_estimate_from_usage
from deepseek_tui.engine.context import estimate_context_breakdown
from deepseek_tui.engine.usage_ledger import TurnUsageLedger, usage_source
from deepseek_tui.protocol.responses import Usage
from deepseek_tui.server.threads import build_turn_usage_record

# Shape taken from a real devpilot/claudecode round: 147008 cached, 204 new.
ANTHROPIC_CACHED = {
    "input_tokens": 204,
    "output_tokens": 624,
    "cache_read_input_tokens": 147008,
    "cache_creation_input_tokens": 0,
}
ANTHROPIC_TOTAL_INPUT = 147212

# Same prompt as DeepSeek would report it: prompt_tokens already covers both.
DEEPSEEK_CACHED = {
    "prompt_tokens": 147008,
    "completion_tokens": 624,
    "prompt_cache_hit_tokens": 147008,
    "prompt_cache_miss_tokens": 0,
}


def test_total_input_tokens_adds_cache_counters_for_anthropic_payloads() -> None:
    usage = Usage.model_validate(ANTHROPIC_CACHED)
    assert usage.input_tokens == 204
    assert usage.total_input_tokens == ANTHROPIC_TOTAL_INPUT


def test_anthropic_semantics_do_not_depend_on_counter_magnitude() -> None:
    """A large uncached suffix must not masquerade as an inclusive total."""
    usage = Usage.model_validate({"input_tokens": 10_000, "cache_read_input_tokens": 5_000})
    assert usage.total_input_tokens == 15_000


def test_total_input_tokens_does_not_double_count_deepseek_payloads() -> None:
    usage = Usage.model_validate(DEEPSEEK_CACHED)
    assert usage.input_tokens == 147008
    assert usage.total_input_tokens == 147008


def test_openai_nested_cached_tokens_are_normalised() -> None:
    usage = Usage.model_validate(
        {
            "prompt_tokens": 10_000,
            "completion_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 6_000},
        }
    )
    assert usage.total_input_tokens == 10_000
    assert usage.cache_read_input_tokens == 6_000
    assert usage.cache_creation_input_tokens == 4_000


@pytest.mark.parametrize(
    "payload",
    [
        DEEPSEEK_CACHED,
        {
            "prompt_tokens": 10_000,
            "completion_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 6_000},
        },
    ],
)
def test_inclusive_usage_semantics_survive_serialisation(payload) -> None:
    usage = Usage.model_validate(payload)
    restored = Usage.model_validate(usage.model_dump())

    assert restored.input_tokens_include_cache is True
    assert restored.total_input_tokens == usage.total_input_tokens


def test_total_input_tokens_handles_partial_and_absent_caching() -> None:
    # DeepSeek, partially cached: hit + miss == prompt_tokens.
    partial = Usage.model_validate(
        {
            "prompt_tokens": 1000,
            "prompt_cache_hit_tokens": 640,
            "prompt_cache_miss_tokens": 360,
        }
    )
    assert partial.total_input_tokens == 1000

    # Anthropic, first call: the prompt is written to cache, not read from it.
    creating = Usage(input_tokens=204, cache_creation_input_tokens=147008)
    assert creating.total_input_tokens == ANTHROPIC_TOTAL_INPUT

    # No caching reported at all — nothing to add.
    plain = Usage(input_tokens=5000, output_tokens=100)
    assert plain.total_input_tokens == 5000

    assert Usage().total_input_tokens == 0


def test_context_breakdown_uses_full_prompt_instead_of_uncached_remainder(
    tmp_path,
) -> None:
    """The bug as the user saw it: every static bucket scaled to ~200 tokens
    and Conversation pinned at 0, unchanged across rounds."""
    api_tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "read a file",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    usage = Usage.model_validate(ANTHROPIC_CACHED)

    naive = estimate_context_breakdown(
        model="deepseek-chat",
        workspace=tmp_path,
        api_tools=api_tools,
        real_input_tokens=usage.input_tokens,
    )
    assert naive["total"] == 204
    assert naive["conversation"] == 0

    fixed = estimate_context_breakdown(
        model="deepseek-chat",
        workspace=tmp_path,
        api_tools=api_tools,
        real_input_tokens=usage.total_input_tokens,
    )
    assert fixed["total"] == ANTHROPIC_TOTAL_INPUT
    assert fixed["conversation"] > 0
    assert fixed["system_prompt"] > naive["system_prompt"]
    assert fixed["total"] == (
        fixed["system_prompt"]
        + fixed["rules"]
        + fixed["skills"]
        + fixed["tools"]
        + fixed["conversation"]
    )


def test_ledger_totals_count_the_full_prompt() -> None:
    ledger = TurnUsageLedger()
    with usage_source("agent_round"):
        ledger.record_metered(
            model="deepseek-chat",
            usage=Usage.model_validate(ANTHROPIC_CACHED),
        )

    totals = ledger.totals()
    assert totals["input_tokens"] == ANTHROPIC_TOTAL_INPUT
    assert totals["cache_hit_tokens"] == 147008
    assert totals["models"]["deepseek-chat"]["input_tokens"] == ANTHROPIC_TOTAL_INPUT


def test_ledger_totals_unchanged_for_deepseek_payloads() -> None:
    ledger = TurnUsageLedger()
    with usage_source("agent_round"):
        ledger.record_metered(
            model="deepseek-chat",
            usage=Usage.model_validate(DEEPSEEK_CACHED),
        )

    assert ledger.totals()["input_tokens"] == 147008


def test_turn_usage_record_counts_the_full_prompt() -> None:
    record = build_turn_usage_record(
        usage=Usage.model_validate(ANTHROPIC_CACHED), model="deepseek-chat"
    )
    assert record["input_tokens"] == ANTHROPIC_TOTAL_INPUT
    assert record["total_tokens"] == ANTHROPIC_TOTAL_INPUT + 624


def test_pricing_bills_the_uncached_remainder_without_double_counting() -> None:
    """Input-side only: hold output at zero so the deltas are unambiguous."""

    def cost(usage: Usage) -> float:
        estimate = calculate_turn_cost_estimate_from_usage("deepseek-chat", usage)
        assert estimate is not None
        return estimate.usd

    pure_hit = cost(Usage(input_tokens=0, cache_read_input_tokens=147008))
    anthropic = cost(Usage(input_tokens=204, cache_read_input_tokens=147008))
    deepseek = cost(
        Usage.model_validate(
            {
                "prompt_tokens": 147008,
                "prompt_cache_hit_tokens": 147008,
                "prompt_cache_miss_tokens": 0,
            }
        )
    )

    # The 204 uncached tokens must be billed at miss rates, not dropped.
    assert anthropic > pure_hit
    # DeepSeek's prompt_tokens already covers the hit, so nothing is billed on
    # top of it.
    assert deepseek == pure_hit
