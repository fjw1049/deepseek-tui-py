"""Anthropic Messages API compatibility client."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from deepseek_tui.client.base import LLMClient
from deepseek_tui.client.streaming import AnthropicStreamParser
from deepseek_tui.protocol.messages import (
    Message,
    MessageRequest,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from deepseek_tui.protocol.responses import StreamEvent

logger = logging.getLogger(__name__)


class AnthropicCompatClient(LLMClient):
    """Client for Anthropic-compatible ``POST /v1/messages`` endpoints."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.extra_headers = dict(extra_headers or {})
        self._http_client: httpx.AsyncClient | None = None

    def _messages_url(self) -> str:
        if self.base_url.endswith("/v1/messages"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=self.timeout_seconds,
                    write=self.timeout_seconds,
                    read=None,
                    pool=self.timeout_seconds,
                ),
                transport=self.transport,
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        parser = AnthropicStreamParser()
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            **self.extra_headers,
        }
        payload = self._build_payload(request)
        url = self._messages_url()
        client = self._get_http_client()
        started = time.monotonic()

        async with aconnect_sse(
            client, "POST", url, headers=headers, json=payload
        ) as event_source:
            response = event_source.response
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")[:512]
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code} from {url}: {body}",
                    request=response.request,
                    response=response,
                )
            iterator = event_source.aiter_sse().__aiter__()
            while True:
                try:
                    sse = await asyncio.wait_for(
                        iterator.__anext__(), timeout=self.timeout_seconds
                    )
                except StopAsyncIteration:
                    break
                if not sse.data:
                    continue
                try:
                    chunk = json.loads(sse.data)
                except json.JSONDecodeError:
                    logger.warning("anthropic_sse_invalid_json data=%r", sse.data[:200])
                    continue
                for event in parser.parse_event(sse.event, chunk):
                    yield event

        for event in parser.finalize():
            yield event
        logger.info(
            "http_response url=%s elapsed_ms=%d",
            url,
            int((time.monotonic() - started) * 1000),
        )

    def _build_payload(self, request: MessageRequest) -> dict[str, Any]:
        system, messages = _build_anthropic_messages(
            request.messages, system_prompt=request.system_prompt
        )
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
            "stream": request.stream,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [_map_tool(tool) for tool in request.tools]
        if request.tool_choice is not None:
            payload["tool_choice"] = _map_tool_choice(request.tool_choice)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        payload.update(request.extra_body)
        return payload


def _build_anthropic_messages(
    messages: list[Message], *, system_prompt: str | None
) -> tuple[str, list[dict[str, Any]]]:
    system_parts = [system_prompt.strip()] if system_prompt and system_prompt.strip() else []
    output: list[dict[str, Any]] = []

    def append(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if output and output[-1]["role"] == role:
            output[-1]["content"].extend(blocks)
        else:
            output.append({"role": role, "content": blocks})

    for message in messages:
        blocks: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                if message.role is Role.SYSTEM:
                    system_parts.append(block.text)
                else:
                    blocks.append({"type": "text", "text": block.text})
            elif isinstance(block, ThinkingBlock) and block.signature:
                blocks.append(
                    {
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": block.signature,
                    }
                )
            elif isinstance(block, ToolUseBlock):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
            elif isinstance(block, ToolResultBlock):
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.tool_use_id,
                        "content": block.content,
                        "is_error": block.is_error,
                    }
                )
        if message.role is Role.SYSTEM:
            continue
        role = "assistant" if message.role is Role.ASSISTANT else "user"
        append(role, blocks)
    return "\n\n".join(system_parts), output


def _map_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function")
    if isinstance(function, dict):
        return {
            "name": function.get("name", ""),
            "description": function.get("description", ""),
            "input_schema": function.get("parameters", {"type": "object"}),
        }
    return tool


def _map_tool_choice(choice: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(choice, str):
        if choice in {"required", "any"}:
            return {"type": "any"}
        return {"type": choice}
    choice_type = choice.get("type")
    if choice_type in {"required", "any"}:
        return {"type": "any"}
    if choice_type == "tool":
        return {"type": "tool", "name": choice.get("name", "")}
    if choice_type == "function":
        function = choice.get("function")
        if isinstance(function, dict):
            return {"type": "tool", "name": function.get("name", "")}
    return {"type": str(choice_type or "auto")}
