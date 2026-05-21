from __future__ import annotations

import os

import httpx

from deepseek_tui.tools._validators import optional_int as _optional_int
from deepseek_tui.tools._validators import require_string as _require_string
from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

_TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")


class FetchUrlTool(ToolSpec):
    def name(self) -> str:
        return "fetch_url"

    def description(self) -> str:
        return "Fetch a URL over HTTP and return the response body."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.NETWORK]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        url = _require_string(input_data, "url")
        response = await _fetch(url, context)
        content_type = response.headers.get("content-type", "")
        return ToolResult(
            success=response.is_success,
            content=response.text,
            metadata={
                "url": str(response.url),
                "status_code": response.status_code,
                "content_type": content_type,
            },
        )


class WebSearchTool(ToolSpec):
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or _TAVILY_API_KEY

    def name(self) -> str:
        return "web_search"

    def description(self) -> str:
        return "Search the web using Tavily and return results with snippets."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.NETWORK]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        query = _require_string(input_data, "query")
        max_results = _optional_int(input_data, "max_results") or 5

        _check_network_policy("https://api.tavily.com", "web_search", context)

        if not self._api_key:
            raise ToolError("TAVILY_API_KEY not configured (set in config.toml or env)")

        payload = {
            "query": query,
            "max_results": max_results,
            "include_answer": True,
        }
        timeout = context.timeout_ms / 1000 if context.timeout_ms is not None else 30
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._api_key}",
                    },
                )
        except (httpx.HTTPError, OSError) as exc:
            raise ToolError(f"Tavily search failed: {exc}") from exc

        if not resp.is_success:
            raise ToolError(
                f"Tavily API returned {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        results = data.get("results", [])[:max_results]
        answer = data.get("answer", "")

        lines: list[str] = []
        if answer:
            lines.append(f"Answer: {answer}\n")
        for i, item in enumerate(results, 1):
            title = item.get("title", "")
            url = item.get("url", "")
            snippet = item.get("content", "")
            lines.append(f"{i}. {title}\n   {url}\n   {snippet}")

        content = "\n".join(lines)
        return ToolResult(
            success=True,
            content=content,
            metadata={
                "query": query,
                "result_count": len(results),
                "results": results,
                "source": "tavily",
            },
        )


def _check_network_policy(url: str, tool_name: str, context: ToolContext) -> None:
    """Enforce network policy if configured. Raises ToolError on DENY."""
    if context.network_policy is None:
        return
    from deepseek_tui.network.policy import Decision

    decision = context.network_policy.evaluate(url, tool_name)
    if decision == Decision.DENY:
        raise ToolError(
            f"Network access denied for {url} by policy. "
            "Configure allow-list in config.toml [network_policy]."
        )
    # PROMPT → for now treat as allow (full interactive prompt requires TUI hook)
    # TODO: wire interactive approval when TUI approval handler is available


async def _fetch(
    url: str,
    context: ToolContext,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    _check_network_policy(url, "fetch_url", context)
    timeout = context.timeout_ms / 1000 if context.timeout_ms is not None else None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            return await client.get(url, params=params, headers=headers)
    except (httpx.HTTPError, OSError) as exc:
        raise ToolError(f"Failed to fetch URL {url}: {exc}") from exc


