"""One StreamDone per request, regardless of where the provider puts usage.

Regression: DeepSeek official attaches usage to the ``finish_reason=stop``
chunk, and the parser used to emit StreamDone both there and in finalize().
MeteredLLMClient records every usage-bearing StreamDone, so every final
round was double-billed (turn_complete showed exactly 2x tokens).
"""

from __future__ import annotations

from deepseek_tui.client.streaming import OpenAIStreamParser
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamToolCallComplete,
)


def _stream(parser: OpenAIStreamParser, chunks: list[dict]) -> list:
    events: list = []
    for chunk in chunks:
        events.extend(parser.parse_chunk(chunk))
    events.extend(parser.finalize())
    return events


def test_single_done_when_finish_chunk_carries_usage() -> None:
    """DeepSeek-official shape: usage rides on the finish_reason chunk."""
    parser = OpenAIStreamParser()
    events = _stream(
        parser,
        [
            {"choices": [{"delta": {"content": "hi"}}]},
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        ],
    )
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert len(dones) == 1
    assert dones[0].usage is not None
    assert dones[0].usage.input_tokens == 100


def test_single_done_with_trailing_usage_chunk() -> None:
    """OpenAI include_usage shape: trailing usage-only chunk, empty choices."""
    parser = OpenAIStreamParser()
    events = _stream(
        parser,
        [
            {"choices": [{"delta": {"content": "hi"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {
                "choices": [],
                "usage": {"prompt_tokens": 55, "completion_tokens": 5},
            },
        ],
    )
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert len(dones) == 1
    assert dones[0].usage is not None
    assert dones[0].usage.input_tokens == 55


def test_tool_call_round_still_flushes_before_done() -> None:
    parser = OpenAIStreamParser()
    events = _stream(
        parser,
        [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "a.py"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 2},
            },
        ],
    )
    completes = [e for e in events if isinstance(e, StreamToolCallComplete)]
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert len(completes) == 1
    assert completes[0].tool_call.name == "read_file"
    assert len(dones) == 1
    assert events.index(completes[0]) < events.index(dones[0])
