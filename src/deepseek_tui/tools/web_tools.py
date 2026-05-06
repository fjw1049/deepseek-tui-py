from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext


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
    def name(self) -> str:
        return "web_search"

    def description(self) -> str:
        return "Search the web and return a small set of results."

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
        response = await _fetch(
            "https://html.duckduckgo.com/html/",
            context,
            params={"q": query},
            headers={"user-agent": "deepseek-tui-py/0.1"},
        )
        parser = _DuckDuckGoResultParser()
        parser.feed(response.text)
        results = parser.results[:max_results]
        content = "\n".join(
            f"{index}. {item['title']} - {item['url']}"
            for index, item in enumerate(results, start=1)
        )
        return ToolResult(
            success=response.is_success,
            content=content,
            metadata={
                "query": query,
                "result_count": len(results),
                "results": results,
                "source": str(response.url),
            },
        )


class WebRunTool(ToolSpec):
    def name(self) -> str:
        return "web_run"

    def description(self) -> str:
        return "Execute a JavaScript snippet in a headless browser context."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "script": {"type": "string"},
            },
            "required": ["url", "script"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.NETWORK, ToolCapability.EXECUTES_CODE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        url = _require_string(input_data, "url")
        script = _require_string(input_data, "script")
        return ToolResult(
            success=True,
            content="(web_run not yet wired to a browser runtime)",
            metadata={"url": url, "script": script, "stub": True},
        )


class FinanceTool(ToolSpec):
    def name(self) -> str:
        return "finance"

    def description(self) -> str:
        return "Fetch financial market data for a ticker symbol."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "period": {"type": "string"},
            },
            "required": ["ticker"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.NETWORK]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        ticker = _require_string(input_data, "ticker")
        period = _optional_string(input_data, "period") or "1d"
        return ToolResult(
            success=True,
            content=f"(finance stub for {ticker} period={period})",
            metadata={
                "ticker": ticker,
                "period": period,
                "stub": True,
            },
        )


class _DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        class_name = attr_map.get("class", "") or ""
        href = attr_map.get("href")
        if href is None or "result__a" not in class_name:
            return
        self._current_href = href
        self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return
        title = " ".join(part.strip() for part in self._buffer if part.strip())
        url = _extract_result_url(self._current_href)
        if title and url:
            self.results.append({"title": unescape(title), "url": url})
        self._current_href = None
        self._buffer = []


async def _fetch(
    url: str,
    context: ToolContext,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    timeout = context.timeout_ms / 1000 if context.timeout_ms is not None else None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            return await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise ToolError(f"Failed to fetch URL {url}: {exc}") from exc


def _extract_result_url(href: str) -> str:
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    encoded_url = query.get("uddg")
    if encoded_url:
        return unquote(encoded_url[0])
    if href.startswith("//"):
        return f"https:{href}"
    return href


def _require_string(input_data: dict[str, object], key: str) -> str:
    value = input_data.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def _optional_int(input_data: dict[str, object], key: str) -> int | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
    return value


def _optional_string(input_data: dict[str, object], key: str) -> str | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value
