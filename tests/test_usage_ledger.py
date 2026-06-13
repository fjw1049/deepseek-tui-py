"""Unit tests for per-turn usage ledger and metered client."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from deepseek_tui.client.base import LLMClient, MeteredLLMClient, RetryConfig
from deepseek_tui.engine.usage_ledger import TurnUsageLedger, usage_source
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, StreamEvent, Usage
from deepseek_tui.server.threads import build_turn_usage_record, turn_usage_from_engine_or_event


class _UsageClient(LLMClient):
    def __init__(self, usage: Usage) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        self.usage = usage
        self.model_seen: str | None = None

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        self.model_seen = request.model
        yield StreamDone(usage=self.usage)


def test_ledger_combined_usage_sums_multiple_calls() -> None:
    ledger = TurnUsageLedger()
    with usage_source("agent_round"):
        ledger.record_metered(
            model="deepseek-chat",
            usage=Usage(input_tokens=100, output_tokens=20),
        )
    with usage_source("phase_bridge"):
        ledger.record_metered(
            model="deepseek-chat",
            usage=Usage(
                input_tokens=50,
                output_tokens=10,
                cache_read_input_tokens=30,
                reasoning_tokens=5,
            ),
        )

    combined = ledger.combined_usage()
    assert combined is not None
    assert combined.input_tokens == 150
    assert combined.output_tokens == 30
    assert combined.cache_read_input_tokens == 30
    assert combined.reasoning_tokens == 5

    totals = ledger.totals()
    assert totals["input_tokens"] == 150
    assert totals["output_tokens"] == 30
    assert totals["turns"] == 2
    assert totals["sources"] == {"agent_round": 1, "phase_bridge": 1}
    assert "deepseek-chat" in totals["models"]
    assert totals["models"]["deepseek-chat"]["input_tokens"] == 150


def test_ledger_ignores_empty_usage() -> None:
    ledger = TurnUsageLedger()
    ledger.add(model="deepseek-chat", source="agent_round", usage=None)
    ledger.add(
        model="deepseek-chat",
        source="agent_round",
        usage=Usage(input_tokens=0, output_tokens=0),
    )
    assert ledger.items == []
    assert ledger.combined_usage() is None


@pytest.mark.asyncio
async def test_metered_client_records_stream_done_usage() -> None:
    ledger = TurnUsageLedger()
    inner = _UsageClient(Usage(input_tokens=42, output_tokens=7))
    client = MeteredLLMClient(inner, ledger)

    with usage_source("compaction"):
        async for event in client.stream_chat_completion(
            MessageRequest(model="deepseek-chat", messages=[])
        ):
            assert isinstance(event, StreamDone)

    assert len(ledger.items) == 1
    assert ledger.items[0].source == "compaction"
    assert ledger.items[0].usage.input_tokens == 42


def test_turn_usage_from_engine_prefers_ledger() -> None:
    class _Engine:
        turn_usage_ledger = TurnUsageLedger()

    engine = _Engine()
    with usage_source("agent_round"):
        engine.turn_usage_ledger.record_metered(
            model="deepseek-chat",
            usage=Usage(input_tokens=10, output_tokens=5),
        )
    with usage_source("agent_round"):
        engine.turn_usage_ledger.record_metered(
            model="deepseek-chat",
            usage=Usage(input_tokens=20, output_tokens=8),
        )

    event_usage = build_turn_usage_record(
        usage=Usage(input_tokens=999, output_tokens=999),
        model="deepseek-chat",
    )
    from deepseek_tui.engine.events import TurnCompleteEvent

    event = TurnCompleteEvent(
        assistant_message=None,
        usage=Usage(input_tokens=999, output_tokens=999),
    )
    record = turn_usage_from_engine_or_event(
        engine=engine,
        event=event,
        model="deepseek-chat",
    )
    assert record is not None
    assert record["input_tokens"] == 30
    assert record["output_tokens"] == 13
    assert record["turns"] == 2
    assert event_usage["input_tokens"] == 999
