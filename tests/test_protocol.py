from __future__ import annotations

from deepseek_tui.protocol.errors import ErrorEnvelope, ErrorKind
from deepseek_tui.protocol.messages import Message, Role, ToolUseBlock
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    StreamToolCallComplete,
    ToolCall,
    Usage,
)


def test_message_factory_methods() -> None:
    user_message = Message.user("hello")
    tool_message = Message.tool_result("tool-1", "done")

    assert user_message.role is Role.USER
    assert user_message.content[0].text == "hello"
    assert tool_message.role is Role.TOOL
    assert tool_message.content[0].tool_use_id == "tool-1"


def test_assistant_tool_message_serializes_blocks() -> None:
    message = Message.assistant_with_tools(
        [ToolUseBlock(id="call-1", name="read_file", input={"path": "a.txt"})]
    )

    assert message.role is Role.ASSISTANT
    assert message.content[0].name == "read_file"
    assert message.model_dump()["content"][0]["type"] == "tool_use"


def test_message_request_defaults() -> None:
    request = MessageRequest(model="deepseek-chat", messages=[Message.user("hello")])

    assert request.stream is True
    assert request.tools == []
    assert request.messages[0].role is Role.USER


def test_stream_event_models_hold_payloads() -> None:
    delta = StreamTextDelta(text="hi")
    tool_complete = StreamToolCallComplete(
        tool_call=ToolCall(id="call-1", name="write_file", arguments={"path": "a.txt"})
    )
    done = StreamDone(usage=Usage(input_tokens=10, output_tokens=5))

    assert delta.text == "hi"
    assert tool_complete.tool_call.name == "write_file"
    assert done.usage is not None
    assert done.usage.output_tokens == 5


def test_error_envelope_defaults() -> None:
    envelope = ErrorEnvelope(kind=ErrorKind.NETWORK, message="timeout")
    stream_error = StreamError(message="timeout", retryable=True)

    assert envelope.retryable is False
    assert stream_error.retryable is True
