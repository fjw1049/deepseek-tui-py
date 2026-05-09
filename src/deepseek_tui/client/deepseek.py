from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from deepseek_tui.client.base import LLMClient
from deepseek_tui.client.chat_messages import build_chat_messages
from deepseek_tui.client.streaming import OpenAIStreamParser
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import StreamEvent


class DeepSeekClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @classmethod
    def from_config(cls, config: object) -> DeepSeekClient:
        """Build a client from a Config instance (or use env fallback)."""
        import os

        from deepseek_tui.secrets.manager import SecretsManager

        mgr = SecretsManager()
        api_key = mgr.resolve_api_key(config)
        if not api_key:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        pc = config.effective_provider_config()  # type: ignore[union-attr]
        base_url = pc.base_url or "https://api.deepseek.com"
        return cls(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=float(pc.timeout),
        )

    async def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[StreamEvent]:
        parser = OpenAIStreamParser()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(request)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            transport=self.transport,
        ) as client:
            async with aconnect_sse(
                client,
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as event_source:
                async for sse in event_source.aiter_sse():
                    if sse.data == "[DONE]":
                        break
                    chunk = json.loads(sse.data)
                    for event in parser.parse_chunk(chunk):
                        yield event
        for event in parser.finalize():
            yield event

    def _build_payload(self, request: MessageRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": build_chat_messages(
                request.messages,
                system_prompt=request.system_prompt,
                model=request.model,
                reasoning_effort=request.reasoning_effort,
            ),
            "stream": request.stream,
        }
        if request.stream:
            payload["stream_options"] = {"include_usage": True}
        if request.tools:
            payload["tools"] = request.tools
        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.reasoning_effort is not None and request.reasoning_effort != "off":
            payload["reasoning_effort"] = request.reasoning_effort
            payload["thinking"] = {"type": "enabled"}
        payload.update(request.extra_body)
        return payload
