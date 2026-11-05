"""OpenAI Responses API client: routing, wire shapes, stream parsing, reasoning replay."""

from __future__ import annotations

import io
import json

import httpx
import pytest
from PIL import Image

from deepseek_tui.client.anthropic import _build_anthropic_messages
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.client.factory import build_llm_client
from deepseek_tui.client.openai_responses import (
    OpenAIResponsesClient,
    ResponsesStreamParser,
    build_responses_input,
    encode_signature,
)
from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.engine.events import AssistantResponseBuffer
from deepseek_tui.media import import_image
from deepseek_tui.protocol.messages import (
    Message,
    MessageRequest,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamToolCallComplete,
)

MODEL = "gpt-6.1-terra"
REASONING = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "enc"}

# Event order recorded from a live gpt-6.1-terra stream (payloads trimmed).
LIVE_EVENTS = [
    {"type": "response.created"},
    {"type": "response.output_item.added", "output_index": 0,
     "item": {"type": "reasoning", "id": "rs_1", "summary": []}},
    {"type": "response.reasoning_summary_part.added", "output_index": 0, "summary_index": 0},
    {"type": "response.reasoning_summary_text.delta", "output_index": 0, "delta": "Calculating"},
    {"type": "response.output_item.done", "output_index": 0, "item": REASONING},
    {"type": "response.output_item.added", "output_index": 1,
     "item": {"type": "message", "role": "assistant", "content": []}},
    {"type": "response.output_text.delta", "output_index": 1, "delta": "The last digit is 2."},
    {"type": "response.output_item.added", "output_index": 2,
     "item": {"type": "function_call", "call_id": "call_1", "name": "get_time", "arguments": ""}},
    {"type": "response.function_call_arguments.delta", "output_index": 2, "delta": '{"tz":'},
    {"type": "response.function_call_arguments.delta", "output_index": 2, "delta": '"UTC+2"}'},
    {"type": "response.output_item.done", "output_index": 2,
     "item": {"type": "function_call", "call_id": "call_1", "name": "get_time",
              "arguments": '{"tz":"UTC+2"}'}},
    {"type": "response.completed", "response": {"status": "completed", "usage": {
        "input_tokens": 74, "input_tokens_details": {"cached_tokens": 10},
        "output_tokens": 153, "output_tokens_details": {"reasoning_tokens": 69}}}},
]


@pytest.fixture(autouse=True)
def media_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))


def _image():
    output = io.BytesIO()
    Image.new("RGB", (48, 32), "red").save(output, format="PNG")
    return import_image(output.getvalue())


def _parse(events):
    parser = ResponsesStreamParser(MODEL)
    out = [e for chunk in events for e in parser.parse_chunk(chunk)]
    return out + parser.finalize()


def _config(base_url: str) -> Config:
    return Config(provider="openai", providers={"openai": ProviderConfig(
        protocol="openai", api_key="test-key", base_url=base_url, model=MODEL)})


def test_factory_routes_only_openai_host_to_responses() -> None:
    client = build_llm_client(_config("https://api.openai.com/v1"))
    assert isinstance(client, OpenAIResponsesClient)
    assert client._request_url() == "https://api.openai.com/v1/responses"
    other = build_llm_client(_config("https://gateway.example/v1"))
    assert type(other) is DeepSeekClient


def test_live_event_sequence_maps_to_stream_events() -> None:
    events = _parse(LIVE_EVENTS)
    thinking = [e.thinking for e in events if isinstance(e, StreamThinkingDelta)]
    assert "".join(thinking) == "Calculating"
    assert [e.text for e in events if isinstance(e, StreamTextDelta)] == ["The last digit is 2."]
    [call] = [e.tool_call for e in events if isinstance(e, StreamToolCallComplete)]
    assert (call.id, call.name, call.arguments) == ("call_1", "get_time", {"tz": "UTC+2"})
    [signed] = [e for e in events if isinstance(e, StreamThinkingDelta) and e.signature]
    assert signed.signature == encode_signature(MODEL, [REASONING])
    done = events[-1]
    assert isinstance(done, StreamDone) and not done.truncated
    assert (done.usage.total_input_tokens, done.usage.cache_read_input_tokens,
            done.usage.output_tokens, done.usage.reasoning_tokens) == (74, 10, 153, 69)


def test_incomplete_and_failed_responses_carry_no_tool_calls() -> None:
    incomplete = _parse([*LIVE_EVENTS[:-1], {"type": "response.incomplete", "response": {
        "incomplete_details": {"reason": "max_output_tokens"}}}])
    assert not any(isinstance(e, StreamToolCallComplete) for e in incomplete)
    assert isinstance(incomplete[-1], StreamDone) and incomplete[-1].truncated

    failed = _parse([LIVE_EVENTS[1], {"type": "response.failed", "response": {
        "error": {"message": "server overloaded"}}}])
    assert isinstance(failed[-1], StreamError) and failed[-1].message == "server overloaded"

    cut = _parse(LIVE_EVENTS[:-1])  # stream ended without response.completed
    assert isinstance(cut[-1], StreamError)


def test_history_maps_to_input_items_and_replays_own_reasoning_only() -> None:
    signature = encode_signature(MODEL, [REASONING])
    image = _image()
    messages = [
        Message.system("mid-conversation note"),
        Message.user("look"),
        Message(role=Role.ASSISTANT, content=[
            ThinkingBlock(thinking="summary", signature=signature), TextBlock(text="checking")]),
        Message.assistant_with_tools([ToolUseBlock(id="call_1", name="read", input={"p": "a"})]),
        Message(role=Role.TOOL, content=[
            *Message.tool_result("call_1", "screen", images=[image]).content,
            TextBlock(text="1024x768 screenshot")]),
        Message.user("next"),
    ]
    items = build_responses_input(messages, model=MODEL)
    assert items[:6] == [
        {"role": "system", "content": "mid-conversation note"},
        {"role": "user", "content": "look"},
        REASONING,
        {"role": "assistant", "content": "checking"},
        {"type": "function_call", "call_id": "call_1", "name": "read", "arguments": '{"p": "a"}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "screen"},
    ]
    follow_up = items[6]
    assert follow_up["role"] == "user"
    assert [p["type"] for p in follow_up["content"]] == ["input_text", "input_image", "input_text"]
    assert follow_up["content"][1]["image_url"].startswith("data:image/")
    assert follow_up["content"][2]["text"] == "1024x768 screenshot"
    assert items[7] == {"role": "user", "content": "next"}

    # Another model cannot decrypt these items; it gets the history without them.
    assert REASONING not in build_responses_input(messages, model="gpt-6-luna")


def test_payload_for_reasoning_and_plain_models() -> None:
    client = OpenAIResponsesClient(api_key="k", base_url="https://api.openai.com/v1")
    tool = {"type": "function", "function": {
        "name": "cua_js", "description": "run", "parameters": {"type": "object", "properties": {}}}}
    request = MessageRequest(model=MODEL, system_prompt="be brief", tools=[tool],
                             tool_choice={"type": "tool", "name": "cua_js"}, max_tokens=512,
                             temperature=0.2, reasoning_effort="max",
                             messages=[Message.user("hi")])
    payload = client._build_payload(request)
    assert payload["instructions"] == "be brief"
    assert payload["tools"] == [{"type": "function", "name": "cua_js", "description": "run",
                                 "parameters": {"type": "object", "properties": {}},
                                 "strict": False}]
    assert payload["tool_choice"] == {"type": "function", "name": "cua_js"}
    assert payload["max_output_tokens"] == 512
    assert payload["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert payload["store"] is False
    assert "temperature" not in payload

    plain = client._build_payload(request.model_copy(update={"model": "gpt-4.1"}))
    assert plain["temperature"] == 0.2
    assert "reasoning" not in plain and "include" not in plain


async def test_client_streams_from_responses_endpoint() -> None:
    sent: list[httpx.Request] = []
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in LIVE_EVENTS)

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    client = OpenAIResponsesClient(api_key="k", base_url="https://api.openai.com/v1",
                                   transport=httpx.MockTransport(handle))
    try:
        events = [e async for e in client.stream_chat_completion(
            MessageRequest(model=MODEL, messages=[Message.user("hi")]))]
    finally:
        await client.close()
    assert str(sent[0].url) == "https://api.openai.com/v1/responses"
    assert json.loads(sent[0].content)["input"] == [{"role": "user", "content": "hi"}]
    assert any(isinstance(e, StreamToolCallComplete) for e in events)


def test_signature_reaches_the_assistant_message_but_not_anthropic() -> None:
    buffer = AssistantResponseBuffer()
    buffer.signature = encode_signature(MODEL, [REASONING])
    message = buffer.build_message()
    assert message is not None
    [block] = message.content
    assert isinstance(block, ThinkingBlock) and block.signature == buffer.signature

    _, wire = _build_anthropic_messages([Message.user("hi"), message], system_prompt=None)
    assert all(b.get("type") != "thinking" for m in wire for b in m["content"])
