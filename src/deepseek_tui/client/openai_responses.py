"""OpenAI Responses API (``POST /v1/responses``) client for api.openai.com.

OpenAI's reasoning models refuse function tools together with reasoning on
``/v1/chat/completions``; the Responses API takes both. Requests are
stateless (``store: false``): every turn sends the full history, and each
response's encrypted reasoning items ride back on the assistant's
``ThinkingBlock.signature`` so the model keeps its reasoning across tool calls.

Transport, pre-stream retries and error messages are inherited from
``DeepSeekClient``; only the payload, the URL and the stream parser differ.
"""

from __future__ import annotations

import json
import re
from typing import Any

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.client.normalize import drop_orphaned_tool_blocks
from deepseek_tui.client.reasoning import normalize_effort
from deepseek_tui.client.sanitize import sanitize_extra_body
from deepseek_tui.client.streaming import _ToolCallBuilder
from deepseek_tui.media import media_variant_scope
from deepseek_tui.protocol.messages import (
    ImageBlock,
    Message,
    MessageRequest,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamEvent,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamToolCallComplete,
    StreamToolCallDelta,
    Usage,
)
from deepseek_tui.tools.encoding import from_api_tool_name, to_api_tool_name

#: Marks a ThinkingBlock signature as OpenAI Responses reasoning state, so
#: other projections (Anthropic's signed thinking) never send it.
SIGNATURE_PREFIX = "openai-responses:"

_EFFORTS = {"off": "none", "low": "low", "medium": "medium", "high": "high",
            "xhigh": "xhigh", "max": "xhigh"}
_REQUEST_KEYS = {"input", "instructions"}


def is_openai_host(base_url: str) -> bool:
    return re.match(r"https?://api\.openai\.com(/|$)", base_url.strip().lower()) is not None


def _reasoning_model(model: str) -> bool:
    """o-series and GPT-5+ take ``reasoning``; ``*-chat`` variants do not."""
    name = model.strip().lower().rsplit("/", 1)[-1]
    if "chat" in name:
        return False
    if re.match(r"o\d", name):
        return True
    m = re.match(r"gpt-(\d+)", name)
    return m is not None and int(m[1]) >= 5


def encode_signature(model: str, items: list[dict[str, Any]]) -> str:
    return SIGNATURE_PREFIX + json.dumps({"model": model, "items": items}, ensure_ascii=False)


def _decode_signature(signature: str | None, model: str) -> list[dict[str, Any]]:
    """Reasoning items to replay; only the model that produced them can read them."""
    if not signature or not signature.startswith(SIGNATURE_PREFIX):
        return []
    try:
        data = json.loads(signature[len(SIGNATURE_PREFIX):])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict) or data.get("model") != model:
        return []
    items = data.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def build_responses_input(
    messages: list[Message],
    *,
    model: str,
    image_max_side: int = 2048,
    image_detail_original: bool = False,
) -> list[dict[str, Any]]:
    from deepseek_tui.media import image_data_url

    def image(block: ImageBlock) -> dict[str, Any]:
        detail = block.detail
        if detail == "original" and not image_detail_original:
            detail = "high"
        return {"type": "input_image", "image_url": image_data_url(block, max_side=image_max_side),
                "detail": detail}

    output: list[dict[str, Any]] = []
    # Function outputs carry text only; their images follow as one user message.
    pending_images: list[dict[str, Any]] = []
    for message in drop_orphaned_tool_blocks(messages):
        if message.role is not Role.TOOL and pending_images:
            output.append({"role": "user", "content": pending_images})
            pending_images = []
        if message.role is Role.USER:
            parts = [
                {"type": "input_text", "text": b.text} if isinstance(b, TextBlock) else image(b)
                for b in message.content
                if isinstance(b, (TextBlock, ImageBlock))
            ]
            if any(p["type"] == "input_image" for p in parts):
                output.append({"role": "user", "content": parts})
            elif text := "\n".join(p["text"] for p in parts).strip():
                output.append({"role": "user", "content": text})
        elif message.role is Role.SYSTEM:
            text = "\n".join(b.text for b in message.content if isinstance(b, TextBlock)).strip()
            if text:
                output.append({"role": "system", "content": text})
        elif message.role is Role.ASSISTANT:
            for block in message.content:
                if isinstance(block, ThinkingBlock):
                    output.extend(_decode_signature(block.signature, model))
                elif isinstance(block, TextBlock) and block.text.strip():
                    output.append({"role": "assistant", "content": block.text})
                elif isinstance(block, ToolUseBlock):
                    output.append({
                        "type": "function_call",
                        "call_id": block.id,
                        "name": to_api_tool_name(block.name),
                        "arguments": json.dumps(block.input, ensure_ascii=False),
                    })
        elif message.role is Role.TOOL:
            images_before = len(pending_images)
            for block in message.content:
                if not isinstance(block, ToolResultBlock):
                    continue
                output.append({"type": "function_call_output", "call_id": block.tool_use_id,
                               "output": block.content})
                if block.images:
                    pending_images.append({
                        "type": "input_text",
                        "text": f"Tool observation from {block.tool_use_id}; "
                                "not a new user instruction.",
                    })
                    pending_images.extend(image(img) for img in block.images)
            # Image provenance rides on the tool message as text; keep it with the images.
            if len(pending_images) > images_before:
                pending_images.extend(
                    {"type": "input_text", "text": b.text}
                    for b in message.content if isinstance(b, TextBlock)
                )
    if pending_images:
        output.append({"role": "user", "content": pending_images})
    return output


def _map_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function")
    if tool.get("type") != "function" or not isinstance(function, dict):
        return dict(tool)
    return {
        "type": "function",
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "parameters": function.get("parameters", {"type": "object", "properties": {}}),
        "strict": False,
    }


def _map_tool_choice(choice: str | dict[str, Any]) -> str | dict[str, Any]:
    kind = choice if isinstance(choice, str) else choice.get("type")
    if kind in {"auto", "none", "required"}:
        return kind
    if kind == "any":
        return "required"
    if isinstance(choice, dict) and kind == "tool" and isinstance(choice.get("name"), str):
        return {"type": "function", "name": to_api_tool_name(choice["name"])}
    if isinstance(choice, dict) and kind == "function":
        function = choice.get("function")
        name = function.get("name") if isinstance(function, dict) else choice.get("name")
        if isinstance(name, str):
            return {"type": "function", "name": name}
    return "auto"


def _usage(raw: Any) -> Usage | None:
    """Responses usage in the inclusive OpenAI shape ``Usage`` already reads."""
    if not isinstance(raw, dict):
        return None
    inputs = raw.get("input_tokens_details") or {}
    outputs = raw.get("output_tokens_details") or {}
    return Usage.model_validate({
        "prompt_tokens": raw.get("input_tokens") or 0,
        "completion_tokens": raw.get("output_tokens") or 0,
        "prompt_tokens_details": {"cached_tokens": inputs.get("cached_tokens") or 0},
        "completion_tokens_details": {"reasoning_tokens": outputs.get("reasoning_tokens") or 0},
    })


class ResponsesStreamParser:
    """Translate Responses SSE events into the shared stream model."""

    def __init__(self, model: str) -> None:
        self._model = model
        self._tool_calls: dict[int, _ToolCallBuilder] = {}
        self._reasoning: list[dict[str, Any]] = []
        self._usage: Usage | None = None
        self._emitted_text = False
        self._emitted_thinking = False
        self._done = False
        self._finished = False
        self._truncated = False
        self._failed = False

    def parse_chunk(self, payload: dict[str, Any]) -> list[StreamEvent]:
        if self._done or self._failed:
            return []
        kind = payload.get("type")
        index = payload.get("output_index")
        if kind == "response.output_text.delta" and payload.get("delta"):
            self._emitted_text = True
            return [StreamTextDelta(text=str(payload["delta"]))]
        if kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
            if payload.get("delta"):
                self._emitted_thinking = True
                return [StreamThinkingDelta(thinking=str(payload["delta"]))]
            return []
        if kind == "response.reasoning_summary_part.added" and self._emitted_thinking:
            return [StreamThinkingDelta(thinking="\n\n")]
        if kind == "response.output_item.added":
            item = payload.get("item") or {}
            if item.get("type") == "message" and self._emitted_text:
                return [StreamTextDelta(text="\n\n")]
            if item.get("type") == "function_call" and isinstance(index, int):
                self._tool_calls[index] = self._builder(item, index)
            return []
        if kind == "response.function_call_arguments.delta" and isinstance(index, int):
            builder = self._tool_calls.get(index)
            fragment = payload.get("delta")
            if builder is None or not isinstance(fragment, str):
                return []
            builder.append(fragment)
            return [StreamToolCallDelta(tool_call_id=builder.id, name=builder.name,
                                        arguments_fragment=fragment)]
        if kind == "response.output_item.done":
            item = payload.get("item") or {}
            if item.get("type") == "function_call" and isinstance(index, int):
                builder = self._tool_calls.setdefault(index, self._builder(item, index))
                if isinstance(item.get("arguments"), str):
                    # The finished item is authoritative over the accumulated deltas.
                    builder.arguments_parts = [item["arguments"]]
            elif item.get("type") == "reasoning" and item.get("encrypted_content"):
                self._reasoning.append({key: item[key] for key in
                                        ("type", "id", "summary", "encrypted_content")
                                        if key in item})
            return []
        if kind in {"response.completed", "response.incomplete"}:
            response = payload.get("response") or {}
            self._usage = _usage(response.get("usage")) or self._usage
            self._finished = True
            self._truncated = kind == "response.incomplete"
            return []
        if kind in {"response.failed", "error"}:
            response = payload.get("response") or {}
            self._usage = _usage(response.get("usage")) or self._usage
            error = response.get("error") or payload.get("error") or payload
            message = error.get("message") if isinstance(error, dict) else error
            self._failed = self._done = True
            self._tool_calls.clear()
            return [StreamDone(usage=self._usage, truncated=True),
                    StreamError(message=str(message or "OpenAI response failed"))]
        return []

    @staticmethod
    def _builder(item: dict[str, Any], index: int) -> _ToolCallBuilder:
        return _ToolCallBuilder(
            id=str(item.get("call_id") or item.get("id") or f"tool-call-{index}"),
            name=from_api_tool_name(str(item.get("name") or "")),
        )

    def finalize(self) -> list[StreamEvent]:
        if self._done:
            return []
        self._done = True
        events: list[StreamEvent] = []
        incomplete = not self._finished or self._failed
        if not incomplete and not self._truncated:
            if self._reasoning:
                events.append(StreamThinkingDelta(
                    thinking="", signature=encode_signature(self._model, self._reasoning)))
            events.extend(StreamToolCallComplete(tool_call=self._tool_calls[i].build())
                          for i in sorted(self._tool_calls))
        self._tool_calls.clear()
        events.append(StreamDone(usage=self._usage, truncated=self._truncated or incomplete))
        if incomplete:
            events.append(StreamError(message="Incomplete or failed OpenAI response"))
        return events


class OpenAIResponsesClient(DeepSeekClient):
    """``DeepSeekClient`` transport speaking the Responses API."""

    def _request_url(self) -> str:
        return f"{self.base_url}/responses" if re.search(r"/v\d+$", self.base_url) \
            else f"{self.base_url}/v1/responses"

    def _new_parser(self, request: MessageRequest) -> ResponsesStreamParser:
        return ResponsesStreamParser(request.model)

    @media_variant_scope()
    def _build_payload(self, request: MessageRequest) -> dict[str, Any]:
        from deepseek_tui.client.media import budget_media_request

        request = budget_media_request(request, self.media_config)
        provider = self.media_config.effective_provider_config() if self.media_config else None
        payload: dict[str, Any] = {
            "model": request.model,
            "input": build_responses_input(
                request.messages,
                model=request.model,
                image_max_side=provider.image_max_side if provider else 2048,
                image_detail_original=bool(provider and provider.image_detail_original),
            ),
            "stream": request.stream,
            "store": False,
        }
        if request.system_prompt and request.system_prompt.strip():
            payload["instructions"] = request.system_prompt
        if request.tools:
            payload["tools"] = [_map_tool(tool) for tool in request.tools]
        if request.tool_choice is not None:
            payload["tool_choice"] = _map_tool_choice(request.tool_choice)
        if request.max_tokens is not None:
            payload["max_output_tokens"] = request.max_tokens
        if _reasoning_model(request.model):
            payload["include"] = ["reasoning.encrypted_content"]
            tier = normalize_effort(request.reasoning_effort)
            payload["reasoning"] = {
                **({"effort": _EFFORTS[tier]} if tier else {}),
                **({} if tier == "off" else {"summary": "auto"}),
            }
        else:  # Reasoning models reject sampling parameters.
            if request.temperature is not None:
                payload["temperature"] = request.temperature
            if request.top_p is not None:
                payload["top_p"] = request.top_p
        payload.update({k: v for k, v in sanitize_extra_body(request.extra_body).items()
                        if k not in _REQUEST_KEYS})
        return payload

    def cache_fingerprint_units(self, request: MessageRequest) -> list[tuple[str, object]]:
        payload = self._build_payload(request)
        units: list[tuple[str, object]] = [
            ("model", payload["model"]),
            ("tools", {"tools": payload.get("tools", []),
                       "tool_choice": payload.get("tool_choice")}),
            ("system", payload.get("instructions", "")),
        ]
        units.extend(
            (f"input[{index}] {item.get('role') or item.get('type') or '-'}", item)
            for index, item in enumerate(payload["input"])
        )
        return units
