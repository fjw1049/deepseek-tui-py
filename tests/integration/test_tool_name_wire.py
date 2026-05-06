"""Integration tests for the tool-name codec wiring.

Stage 1.1 (commit c15acc3) added a Rust-parity reversible codec at
`tools/encoding.py` but nothing called it. Stage "integration debt #1"
wired it into:

* ``tools/registry.py:_serialise_tool`` — encodes tool names before
  shipping them to the model.
* ``client/streaming.py:OpenAIStreamParser.parse_chunk`` — decodes
  the ``function.name`` echoed back by the model so the rest of the
  engine receives the original in-memory name.

These tests cover both the wire-up itself and a live-API round-trip
when a DeepSeek key is reachable.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deepseek_tui.client.streaming import OpenAIStreamParser
from deepseek_tui.protocol.responses import StreamToolCallComplete
from deepseek_tui.tools.base import ToolCapability, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.encoding import to_api_tool_name
from deepseek_tui.tools.registry import ToolRegistry
from tests._real_api import (
    get_deepseek_api_key,
    get_deepseek_base_url,
    has_deepseek_api_key,
)

# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


class _DotNameTool(ToolSpec):
    """A tool whose Python-side name contains a literal dot.

    Without the codec wire-up, OpenAI rejects this name with a 400
    ("Invalid 'tools[0].function.name'") because the API only allows
    `[A-Za-z0-9_-]`. With the wire-up, the name appears on the wire as
    ``-x00002E-`` and the Python side never sees the encoded form.
    """

    def name(self) -> str:
        return "namespace.dot_tool"

    def description(self) -> str:
        return "Echoes its 'phrase' argument back."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"phrase": {"type": "string"}},
            "required": ["phrase"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        phrase = input_data.get("phrase", "")
        return ToolResult(success=True, content=f"echo:{phrase}")


class _ColonNameTool(ToolSpec):
    def name(self) -> str:
        return "mcp__server:read"

    def description(self) -> str:
        return "MCP-style colon name."

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        return ToolResult(success=True, content="ok")


# ---------------------------------------------------------------------------
# 1. Wire encode: ToolRegistry.to_api_tools encodes names
# ---------------------------------------------------------------------------


def test_to_api_tools_encodes_dot_in_function_name() -> None:
    registry = ToolRegistry()
    registry.register(_DotNameTool())
    api = registry.to_api_tools()
    assert len(api) == 1
    assert api[0]["function"]["name"] == "namespace-x00002E-dot_tool"
    # The Rust serde shape is byte-stable: same as direct codec call.
    assert api[0]["function"]["name"] == to_api_tool_name("namespace.dot_tool")


def test_to_api_tools_encodes_colon_in_mcp_style_name() -> None:
    registry = ToolRegistry()
    registry.register(_ColonNameTool())
    encoded = registry.to_api_tools()[0]["function"]["name"]
    assert encoded == to_api_tool_name("mcp__server:read")
    # Sanity: encoded form is API-safe.
    import re

    assert re.fullmatch(r"[A-Za-z0-9_-]+", encoded), encoded


def test_to_api_tools_passes_through_simple_names() -> None:
    """Plain ASCII names are unchanged on the wire — no surprises."""
    registry = ToolRegistry()

    class _Plain(_DotNameTool):
        def name(self) -> str:
            return "read_file"

    registry.register(_Plain())
    assert registry.to_api_tools()[0]["function"]["name"] == "read_file"


def test_registry_lookup_still_uses_original_name() -> None:
    """The codec only affects the wire — registry.get() takes the
    Python in-memory name."""
    registry = ToolRegistry()
    tool = _DotNameTool()
    registry.register(tool)
    # The encoded name is NOT a valid lookup key.
    from deepseek_tui.tools.base import ToolError

    with pytest.raises(ToolError):
        registry.get("namespace-x00002E-dot_tool")
    # The original name still works.
    assert registry.get("namespace.dot_tool") is tool


# ---------------------------------------------------------------------------
# 2. Wire decode: OpenAIStreamParser decodes names
# ---------------------------------------------------------------------------


def _make_chunk(*, encoded_name: str, args_fragment: str) -> dict[str, Any]:
    """Mimic an OpenAI Chat Completion streaming delta containing a
    tool-call function.name + arguments fragment."""
    return {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_test",
                            "function": {
                                "name": encoded_name,
                                "arguments": args_fragment,
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    }


def _finish_chunk() -> dict[str, Any]:
    return {
        "choices": [{"delta": {}, "finish_reason": "tool_calls"}]
    }


def test_parser_decodes_encoded_function_name() -> None:
    """End-to-end: parser sees the encoded name on the wire and emits
    the decoded original."""
    parser = OpenAIStreamParser()
    parser.parse_chunk(
        _make_chunk(
            encoded_name="namespace-x00002E-dot_tool",
            args_fragment='{"phrase":"hi"}',
        )
    )
    events = parser.parse_chunk(_finish_chunk())
    completes = [e for e in events if isinstance(e, StreamToolCallComplete)]
    assert len(completes) == 1
    assert completes[0].tool_call.name == "namespace.dot_tool"
    assert completes[0].tool_call.arguments == {"phrase": "hi"}


def test_parser_decodes_bare_hex_when_model_drops_delimiter() -> None:
    """The Rust codec's bare-hex fallback covers the case where a model
    mangles ``-x00002E-`` into ``x00002E``.  Verify that wire path."""
    parser = OpenAIStreamParser()
    parser.parse_chunk(
        _make_chunk(
            # Note: leading `-` is missing. This is what real DeepSeek
            # outputs sometimes garble into.
            encoded_name="namespace_x00002Edot_tool",
            args_fragment="{}",
        )
    )
    events = parser.parse_chunk(_finish_chunk())
    completes = [e for e in events if isinstance(e, StreamToolCallComplete)]
    assert len(completes) == 1
    # Bare-hex pass decodes ``x00002E`` back to ``.``.
    assert completes[0].tool_call.name == "namespace_.dot_tool"


def test_parser_passes_through_simple_names_without_decoding() -> None:
    parser = OpenAIStreamParser()
    parser.parse_chunk(
        _make_chunk(encoded_name="read_file", args_fragment='{"path":"a"}')
    )
    events = parser.parse_chunk(_finish_chunk())
    completes = [e for e in events if isinstance(e, StreamToolCallComplete)]
    assert completes[0].tool_call.name == "read_file"


# ---------------------------------------------------------------------------
# 3. Live DeepSeek round-trip
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not has_deepseek_api_key(),
    reason="needs DEEPSEEK_API_KEY env var or project config.toml api_key",
)
@pytest.mark.asyncio
async def test_live_deepseek_accepts_encoded_dot_tool_name() -> None:
    """The end-to-end smoke test: send a tool whose Python-side name
    contains a dot, verify the live DeepSeek API accepts the request
    (the wire name is encoded, so DeepSeek sees a valid identifier).

    We assert two outcomes:

    * The HTTP request itself doesn't 400 — i.e. the encoding worked.
    * If the model decides to call the tool, the streamed
      ``function.name`` decodes back to the original Python name.
    """
    from deepseek_tui.client.deepseek import DeepSeekClient
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.requests import MessageRequest

    registry = ToolRegistry()
    registry.register(_DotNameTool())
    api_tools = registry.to_api_tools()
    # Sanity-check the wire form is what we expect before the call.
    assert api_tools[0]["function"]["name"] == "namespace-x00002E-dot_tool"

    client = DeepSeekClient(
        api_key=get_deepseek_api_key() or "",
        base_url=get_deepseek_base_url(),
    )
    request = MessageRequest(
        model="deepseek-v4-flash",
        messages=[
            Message.user(
                "Please call the namespace.dot_tool with phrase='hello'."
            ),
        ],
        tools=api_tools,
        max_tokens=200,
        stream=True,
    )

    decoded_names: list[str] = []
    text_chunks: list[str] = []
    error: Exception | None = None
    try:
        async for event in client.stream_chat_completion(request):
            if isinstance(event, StreamToolCallComplete):
                decoded_names.append(event.tool_call.name)
            elif event.type == "text_delta":
                text_chunks.append(getattr(event, "text", ""))
    except Exception as exc:  # pragma: no cover — only in regression
        error = exc

    # Primary invariant: the request reached DeepSeek without a
    # 400-class rejection. If we got any events at all, encoding worked.
    assert error is None, f"live request errored: {error!r}"

    # Best-effort secondary: if the model picked the tool, the decoded
    # name we surfaced to the engine matches the Python in-memory form.
    # We don't strictly require the model to call it (model behaviour
    # is not deterministic), but if it did we hold the codec to its
    # round-trip.
    if decoded_names:
        assert decoded_names == ["namespace.dot_tool"], decoded_names
        print(f"✓ live round-trip decoded names: {decoded_names}")
    else:
        # The model may have answered in text. That's still a successful
        # integration — the request was accepted with the encoded tool.
        print(
            f"✓ live request accepted; model answered in text "
            f"({len(text_chunks)} text chunks)"
        )


__all__ = [
    "test_live_deepseek_accepts_encoded_dot_tool_name",
    "test_parser_decodes_bare_hex_when_model_drops_delimiter",
    "test_parser_decodes_encoded_function_name",
    "test_parser_passes_through_simple_names_without_decoding",
    "test_registry_lookup_still_uses_original_name",
    "test_to_api_tools_encodes_colon_in_mcp_style_name",
    "test_to_api_tools_encodes_dot_in_function_name",
    "test_to_api_tools_passes_through_simple_names",
]


# Keep mypy happy about unused json import if module shrinks later.
_ = json
