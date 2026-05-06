from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamEvent,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamToolCallComplete,
    StreamToolCallDelta,
    ToolCall,
    Usage,
)


def parse_json_object(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


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

            thinking = delta.get("reasoning_content")
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
                            builder.name = name
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
