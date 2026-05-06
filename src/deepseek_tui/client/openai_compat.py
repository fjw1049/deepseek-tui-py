from __future__ import annotations

import httpx

from deepseek_tui.client.deepseek import DeepSeekClient


class OpenAICompatClient(DeepSeekClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
