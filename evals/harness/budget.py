"""Meter every provider attempt, including engine retries and compaction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.client.pricing import calculate_turn_cost_estimate_from_usage
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, StreamEvent

if TYPE_CHECKING:
    from evals.harness import HarnessContext


class BudgetExceeded(RuntimeError):
    pass


class BudgetedClient(LLMClient):
    def __init__(self, inner: LLMClient, context: HarnessContext) -> None:
        # The engine may retry; every attempt passes this wrapper. Do not hide
        # extra provider requests inside a second retry loop.
        super().__init__(retry_config=RetryConfig(max_transparent_retries=0, max_error_retries=0))
        self.inner = inner
        self.context = context

    def cache_fingerprint_units(self, request: MessageRequest) -> list[tuple[str, object]]:
        return self.inner.cache_fingerprint_units(request)

    async def close(self) -> None:
        await self.inner.close()

    async def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[StreamEvent]:
        ctx = self.context
        if ctx.remaining_live_requests <= 0:
            raise BudgetExceeded("请求预算已用完")
        if ctx.max_cost_usd is not None and ctx.cost_usd >= ctx.max_cost_usd:
            raise BudgetExceeded("已记录费用达到预算")
        ctx.remaining_live_requests -= 1
        ctx.requests += 1
        request = request.model_copy(
            update={
                "max_tokens": min(
                    request.max_tokens or ctx.max_output_tokens, ctx.max_output_tokens
                ),
            }
        )
        tools_json = json.dumps(request.tools or [], sort_keys=True, ensure_ascii=False)
        ctx.trace.append(
            {
                "type": "model_request",
                "request": ctx.requests,
                "model": request.model,
                "system_hash": hashlib.sha256((request.system_prompt or "").encode()).hexdigest(),
                "tools_hash": hashlib.sha256(tools_json.encode()).hexdigest(),
                "message_count": len(request.messages),
                "max_tokens": request.max_tokens,
                "messages": [m.model_dump(mode="json") for m in request.messages],
            }
        )
        metered = False
        try:
            async for event in self.inner.stream_chat_completion(request):
                if isinstance(event, StreamDone) and event.usage is not None and not metered:
                    metered = True
                    usage = event.usage
                    ctx.metered_requests += 1
                    for key, value in {
                        "input_tokens": usage.total_input_tokens,
                        "output_tokens": usage.output_tokens,
                        "cache_read_input_tokens": usage.cache_read_input_tokens,
                        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                    }.items():
                        ctx.usage[key] = ctx.usage.get(key, 0) + value
                    cost = calculate_turn_cost_estimate_from_usage(request.model, usage)
                    if cost is not None:
                        ctx.priced_requests += 1
                        ctx.cost_usd += cost.usd
                yield event
        finally:
            ctx.trace.append({"type": "request_finished", "usage_reported": metered})
