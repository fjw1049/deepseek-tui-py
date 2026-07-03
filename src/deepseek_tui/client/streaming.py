

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamEvent,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamToolCallComplete,
    StreamToolCallDelta,
    ToolCall,
    Usage,
)


def parse_json_object(raw: str) -> dict[str, Any]:
    """Parse raw JSON arguments with repair ladder fallback.

    Guarantees a dict is always returned.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    except json.JSONDecodeError:
        pass

    # Stage 2+: deterministic repair ladder (trailing commas, control chars,
    # unbalanced braces)
    from deepseek_tui.engine.dispatch import repair

    return repair(raw)


@dataclass(slots=True)
class _ToolCallBuilder:
    id: str
    name: str | None = None
    arguments_parts: list[str] = field(default_factory=list)

    def append(self, fragment: str) -> None:
        self.arguments_parts.append(fragment)

    def arguments_text(self) -> str:
        return "".join(self.arguments_parts)

    def build(self) -> ToolCall:
        return ToolCall(
            id=self.id,
            name=self.name or "",
            arguments=parse_json_object(self.arguments_text()),
        )


class OpenAIStreamParser:
    def __init__(self) -> None:
        self._tool_calls: dict[int, _ToolCallBuilder] = {}
        self._usage: Usage | None = None

    def parse_chunk(self, payload: dict[str, Any]) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        usage_payload = payload.get("usage")
        if isinstance(usage_payload, dict):
            self._usage = Usage.model_validate(usage_payload)

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return events

        choice = choices[0]
        if not isinstance(choice, dict):
            return events

        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str) and content:
                events.append(StreamTextDelta(text=content))

            thinking = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(thinking, str) and thinking:
                events.append(StreamThinkingDelta(thinking=thinking))

            tool_calls = delta.get("tool_calls")
            if isinstance(tool_calls, list):
                for item in tool_calls:
                    if not isinstance(item, dict):
                        continue
                    index = item.get("index", 0)
                    if not isinstance(index, int):
                        continue
                    builder = self._tool_calls.setdefault(
                        index,
                        _ToolCallBuilder(id=f"tool-call-{index}"),
                    )
                    tool_call_id = item.get("id")
                    if isinstance(tool_call_id, str) and tool_call_id:
                        builder.id = tool_call_id
                    function_data = item.get("function")
                    if isinstance(function_data, dict):
                        name = function_data.get("name")
                        if isinstance(name, str) and name:
                            # The wire form is the encoded name produced
                            # by ToolRegistry._serialise_tool. Decode here
                            # so the rest of the engine sees the original
                            # in-memory tool name (possibly with `.`, `:`,
                            # CJK, emoji, etc.). Bare hex fallback in
                            # from_api_tool_name also handles models that
                            # mangle the `-x...-` delimiters.
                            from deepseek_tui.tools.encoding import (
                                from_api_tool_name,
                            )

                            builder.name = from_api_tool_name(name)
                        arguments_fragment = function_data.get("arguments")
                        if isinstance(arguments_fragment, str):
                            builder.append(arguments_fragment)
                            events.append(
                                StreamToolCallDelta(
                                    tool_call_id=builder.id,
                                    name=builder.name,
                                    arguments_fragment=arguments_fragment,
                                )
                            )

        finish_reason = choice.get("finish_reason")
        if finish_reason == "tool_calls":
            for index in sorted(self._tool_calls):
                events.append(StreamToolCallComplete(tool_call=self._tool_calls[index].build()))
            self._tool_calls.clear()
        elif finish_reason == "stop":
            events.append(StreamDone(usage=self._usage))

        return events

    def finalize(self) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        if self._tool_calls:
            for index in sorted(self._tool_calls):
                events.append(StreamToolCallComplete(tool_call=self._tool_calls[index].build()))
            self._tool_calls.clear()
        if not events or not isinstance(events[-1], StreamDone):
            events.append(StreamDone(usage=self._usage))
        return events


class AnthropicStreamParser:
    """Translate Anthropic Messages SSE events into the shared stream model."""

    def __init__(self) -> None:
        self._tool_calls: dict[int, _ToolCallBuilder] = {}
        self._usage = Usage()
        self._done = False

    def parse_event(
        self, event_name: str, payload: dict[str, Any]
    ) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        event_type = str(payload.get("type") or event_name)

        if event_type == "message_start":
            usage = payload.get("message", {}).get("usage", {})
            if isinstance(usage, dict):
                self._usage = Usage.model_validate(usage)
            return events

        if event_type == "content_block_start":
            index = payload.get("index", 0)
            block = payload.get("content_block")
            if isinstance(index, int) and isinstance(block, dict):
                if block.get("type") == "tool_use":
                    tool_id = str(block.get("id") or f"tool-call-{index}")
                    name = str(block.get("name") or "")
                    from deepseek_tui.tools.encoding import from_api_tool_name

                    self._tool_calls[index] = _ToolCallBuilder(
                        id=tool_id,
                        name=from_api_tool_name(name),
                    )
                elif block.get("type") == "text" and block.get("text"):
                    events.append(StreamTextDelta(text=str(block["text"])))
            return events

        if event_type == "content_block_delta":
            index = payload.get("index", 0)
            delta = payload.get("delta")
            if not isinstance(delta, dict):
                return events
            delta_type = delta.get("type")
            if delta_type == "text_delta" and delta.get("text"):
                events.append(StreamTextDelta(text=str(delta["text"])))
            elif delta_type == "thinking_delta" and delta.get("thinking"):
                events.append(StreamThinkingDelta(thinking=str(delta["thinking"])))
            elif delta_type == "input_json_delta" and isinstance(index, int):
                fragment = str(delta.get("partial_json") or "")
                builder = self._tool_calls.get(index)
                if builder is not None:
                    builder.append(fragment)
                    events.append(
                        StreamToolCallDelta(
                            tool_call_id=builder.id,
                            name=builder.name,
                            arguments_fragment=fragment,
                        )
                    )
            return events

        if event_type == "content_block_stop":
            index = payload.get("index", 0)
            if isinstance(index, int):
                builder = self._tool_calls.pop(index, None)
                if builder is not None:
                    events.append(StreamToolCallComplete(tool_call=builder.build()))
            return events

        if event_type == "message_delta":
            usage = payload.get("usage")
            if isinstance(usage, dict):
                current = self._usage.model_dump()
                current.update(usage)
                self._usage = Usage.model_validate(current)
            return events

        if event_type == "error":
            error = payload.get("error")
            message = error.get("message") if isinstance(error, dict) else error
            events.append(StreamError(message=str(message or "Anthropic API error")))
            return events

        if event_type == "message_stop":
            events.extend(self.finalize())
        return events

    def finalize(self) -> list[StreamEvent]:
        if self._done:
            return []
        events: list[StreamEvent] = []
        for index in sorted(self._tool_calls):
            events.append(StreamToolCallComplete(tool_call=self._tool_calls[index].build()))
        self._tool_calls.clear()
        self._done = True
        events.append(StreamDone(usage=self._usage))
        return events
