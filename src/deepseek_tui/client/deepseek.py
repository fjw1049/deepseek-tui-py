

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
from deepseek_tui.client.chat_messages import build_chat_messages
from deepseek_tui.client.streaming import OpenAIStreamParser
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamEvent

logger = logging.getLogger(__name__)


def is_reasoning_model(model: str) -> bool:
    """Check if a model supports reasoning_content output."""
    lower = model.lower()
    return any(
        marker in lower
        for marker in (
            "deepseek-r",
            "reasoner",
            "-reasoning",
            "-thinking",
            "deepseek-v3.2",
            "deepseek-v4",
        )
    )


def _map_tool_choice_for_chat(
    choice: str | dict[str, Any] | None,
) -> str | dict[str, Any] | None:
    """Translate internal tool_choice shape into the chat-completions API shape.

    The engine emits ``{"type": "auto"}`` etc. internally, but DeepSeek's
    ``/v1/chat/completions`` only accepts the OpenAI shapes:
      - bare string ``"auto" | "none" | "required"``
      - object ``{"type": "function", "function": {"name": "..."}}``

    Without this mapping the API returns HTTP 400 "unknown variant `auto`".
    """
    if choice is None:
        return None
    if isinstance(choice, str):
        return choice
    if not isinstance(choice, dict):
        return choice
    choice_type = choice.get("type")
    if not isinstance(choice_type, str):
        return choice
    if choice_type in ("auto", "none", "required"):
        return choice_type
    if choice_type == "any":
        return "auto"
    if choice_type == "tool":
        name = choice.get("name")
        if isinstance(name, str):
            return {"type": "function", "function": {"name": name}}
    return choice


class DeepSeekClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
        thinking_supported: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.thinking_supported = thinking_supported
        self.extra_headers = dict(extra_headers or {})
        self._http_client: httpx.AsyncClient | None = None

    @classmethod
    def from_config(cls, config: object) -> DeepSeekClient:
        """Build a client from a Config instance (or use env fallback).

        Prefer ``build_llm_client()`` from ``client.factory`` for new code;
        this class method is kept for backwards compatibility.
        """
        import os

        from deepseek_tui.state.secrets import SecretsManager

        mgr = SecretsManager()
        api_key = mgr.resolve_api_key(config)
        if not api_key:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        pc = config.effective_provider_config()  # type: ignore[union-attr]
        base_url = pc.base_url or "https://api.deepseek.com"
        # Infer thinking_supported from base_url for legacy callers.
        thinking = "deepseek" in base_url.lower()
        return cls(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=float(pc.timeout),
            thinking_supported=thinking,
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return a persistent httpx client for connection reuse.

        ``read=None`` lets the per-chunk ``asyncio.wait_for`` in
        ``stream_chat_completion`` be the sole source of truth for SSE idle
        timeouts. With a finite httpx ``read`` the global timer can fire
        first and surface as ``httpx.ReadTimeout`` instead of
        ``asyncio.TimeoutError``, hitting different retry branches in
        ``TurnLoop._run_turn_loop`` and confusing transparent-retry
        accounting. Connect/write timeouts stay bounded so DNS or TLS
        stalls still surface promptly.
        """
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
        """Close the persistent HTTP client."""
        if self._http_client is not None and not self._http_client.is_closed:
            logger.debug("http_client_close base_url=%s", self.base_url)
            await self._http_client.aclose()
            self._http_client = None

    async def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[StreamEvent]:
        parser = OpenAIStreamParser()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        payload = self._build_payload(request)
        client = self._get_http_client()
        chunk_timeout = self.timeout_seconds
        # Pre-stream retry on 429 / 5xx / connect errors: only retries
        # before the first byte of the response body is consumed; once SSE
        # chunks start flowing the engine's transparent-retry layer takes
        # over.
        url = self._chat_completions_url()
        body_bytes = len(json.dumps(payload).encode())
        logger.info(
            "http_request method=POST url=%s model=%s msg_count=%d body_bytes=%d",
            url,
            request.model,
            len(payload.get("messages", [])),
            body_bytes,
        )
        request_started = time.monotonic()
        async for sse_event in self._stream_with_pre_retry(
            client, url, headers, payload, parser, chunk_timeout
        ):
            yield sse_event
        for event in parser.finalize():
            yield event
        logger.info(
            "http_response url=%s elapsed_ms=%d",
            url,
            int((time.monotonic() - request_started) * 1000),
        )

    def _chat_completions_url(self) -> str:
        """Build the chat-completions URL without doubling the version prefix.

        Several PROVIDER_DEFAULTS base URLs already end in a version path
        (``/v1``, ``/v3``, etc.); appending ``/v1/chat/completions``
        blindly yields a 404.  Detect any ``/vN`` suffix and append only
        ``/chat/completions`` when present.
        """
        import re
        if re.search(r"/v\d+$", self.base_url):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    async def _stream_with_pre_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        parser: OpenAIStreamParser,
        chunk_timeout: float,
    ) -> AsyncIterator[StreamEvent]:
        """Yield SSE events; retry connection-phase 429/5xx with backoff.

        The retry loop only fires before the first SSE chunk is yielded.
        Delays: 1s base, ×2 backoff, max 60s, but
        capped at MAX_PRE_STREAM_RETRIES attempts.
        """
        max_retries = 3
        attempt = 0
        backoff = 1.0
        streamed = False
        while True:
            try:
                async with aconnect_sse(
                    client, "POST", url, headers=headers, json=payload,
                ) as event_source:
                    # Real httpx_sse exposes ``response`` on the event source,
                    # but tests inject minimal fakes without that attribute.
                    # When absent, skip the status-code retry path and let the
                    # SSE iteration speak for itself.
                    response = getattr(event_source, "response", None)
                    status = getattr(response, "status_code", None) if response else None
                    if status is not None and status >= 400 and response is not None:
                        if attempt < max_retries and (status == 429 or status >= 500):
                            attempt += 1
                            logger.warning(
                                "pre_stream_retry attempt=%d status=%d backoff_s=%.1f",
                                attempt,
                                status,
                                backoff,
                            )
                            try:
                                await response.aread()
                            except Exception:  # noqa: BLE001 — body read best-effort
                                pass
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, 60.0)
                            continue
                        body = ""
                        try:
                            body = (await response.aread()).decode(
                                "utf-8", errors="replace"
                            )[:512]
                        except Exception:  # noqa: BLE001
                            pass
                        message = f"HTTP {status} from {url}: {body}"
                        if status in (401, 403):
                            message += (
                                " — API key invalid or unauthorized; run"
                                " `deepseek-tui login` or check config.toml"
                            )
                        raise httpx.HTTPStatusError(
                            message,
                            request=response.request,
                            response=response,
                        )

                    sse_iter = event_source.aiter_sse().__aiter__()
                    while True:
                        try:
                            sse = await asyncio.wait_for(
                                sse_iter.__anext__(), timeout=chunk_timeout
                            )
                        except StopAsyncIteration:
                            return
                        streamed = True
                        if sse.data == "[DONE]":
                            return
                        try:
                            chunk = json.loads(sse.data)
                        except json.JSONDecodeError as exc:
                            logger.warning(
                                "sse_chunk_invalid_json error=%s data=%r",
                                exc,
                                sse.data[:200],
                            )
                            continue
                        for event in parser.parse_chunk(chunk):
                            yield event
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                logger.warning(
                    "http_connect_error attempt=%d streamed=%s exception_type=%s message=%s",
                    attempt,
                    streamed,
                    type(exc).__name__,
                    str(exc)[:200],
                )
                if streamed:
                    # Chunks were already parsed and yielded: replaying the
                    # request here would feed duplicate deltas into the same
                    # parser (corrupting accumulated tool calls). Propagate
                    # and let the turn-level retry restart cleanly.
                    raise httpx.NetworkError(
                        f"connection lost mid-stream: {exc}"
                    ) from exc
                if attempt < max_retries:
                    attempt += 1
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
                raise httpx.NetworkError(
                    f"connection error after {attempt} retries: {exc}"
                ) from exc

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
            mapped = _map_tool_choice_for_chat(request.tool_choice)
            if mapped is not None:
                payload["tool_choice"] = mapped
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        # ``reasoning_effort`` / ``thinking`` are DeepSeek-specific fields;
        # standard OpenAI-compatible endpoints reject unknown keys with 400.
        # Gate on the ``thinking_supported`` capability flag set at
        # construction time by the client factory. This correctly handles
        # DeepSeek models served via third-party hosts (e.g. OpenRouter)
        # where base_url no longer contains "deepseek".
        if (
            request.reasoning_effort is not None
            and request.reasoning_effort != "off"
            and self.thinking_supported
        ):
            payload["reasoning_effort"] = request.reasoning_effort
            payload["thinking"] = {"type": "enabled"}
        payload.update(request.extra_body)
        return payload


class OpenAICompatClient(DeepSeekClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
        thinking_supported: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            transport=transport,
            thinking_supported=thinking_supported,
            extra_headers=extra_headers,
        )
