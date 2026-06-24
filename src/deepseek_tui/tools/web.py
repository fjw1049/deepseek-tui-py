

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.validation import optional_int as _optional_int
from deepseek_tui.tools.validation import require_string as _require_string

_TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
_ANYSEARCH_API_KEY = os.environ.get("ANYSEARCH_API_KEY", "")
_ANYSEARCH_SEARCH_URL = "https://api.anysearch.com/v1/search"
_ANYSEARCH_MCP_URL = "https://api.anysearch.com/mcp"
_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_DEFAULT_FETCH_MAX_CHARS = 30_000
_DEFAULT_FETCH_TIMEOUT_S = 25.0
_BROWSER_UA = (
    "Mozilla/5.0 (compatible; DeepSeekTUI/1.0; +https://github.com/deepseek-ai)"
)


@dataclass(frozen=True)
class _SearchHit:
    title: str
    url: str
    snippet: str
    source: str
    score: float = 0.0


class FetchUrlTool(ToolSpec):
    def __init__(self, *, anysearch_api_key: str | None = None) -> None:
        self._anysearch_api_key = (
            anysearch_api_key or _ANYSEARCH_API_KEY or ""
        ).strip()

    def name(self) -> str:
        return "fetch_url"

    def description(self) -> str:
        return (
            "Fetch a URL and return readable content. Prefer this over "
            "hand-rolling curl/wget in exec_shell for any HTTP(S) read. "
            "Uses AnySearch extract for general pages (clean Markdown, low "
            "noise); raw HTTP for direct files (raw GitHub, .md/.txt). "
            "Default max_chars=30000."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "required": ["url"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.NETWORK]

    def approval_requirement(self) -> ApprovalRequirement:
        # READ_ONLY+NETWORK default is AUTO; fetching arbitrary URLs needs review.
        return ApprovalRequirement.SUGGEST

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        url = _require_string(input_data, "url")
        _require_http_url(url)
        max_chars = _optional_int(input_data, "max_chars") or _DEFAULT_FETCH_MAX_CHARS
        timeout = context.timeout_ms / 1000 if context.timeout_ms is not None else _DEFAULT_FETCH_TIMEOUT_S
        started = time.monotonic()

        content = ""
        backend = ""
        final_url = url
        status_code: int | None = None
        content_type = ""
        extract_error = ""

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if _is_direct_resource_url(url):
                    _check_network_policy(url, "fetch_url", context)
                    response = await _http_get(client, url)
                    status_code = response.status_code
                    content_type = response.headers.get("content-type", "")
                    final_url = str(response.url)
                    if not response.is_success:
                        raise ToolError(
                            f"HTTP {status_code} fetching {url}: {response.text[:200]}"
                        )
                    content = response.text
                    backend = "direct"
                else:
                    try:
                        content = await _anysearch_extract(
                            client,
                            url=url,
                            api_key=self._anysearch_api_key or None,
                            context=context,
                        )
                        backend = "anysearch_extract"
                    except ToolError as exc:
                        extract_error = str(exc)

                    if not content.strip():
                        _check_network_policy(url, "fetch_url", context)
                        response = await _http_get(client, url)
                        status_code = response.status_code
                        content_type = response.headers.get("content-type", "")
                        final_url = str(response.url)
                        if not response.is_success:
                            detail = extract_error or f"HTTP {status_code}"
                            raise ToolError(f"fetch_url failed for {url}: {detail}")
                        content = response.text
                        backend = "httpx_fallback"
                        if "html" in content_type.lower():
                            content = (
                                "[Raw HTML fallback — navigation/noise may remain. "
                                "Prefer a direct file URL or retry later.]\n\n" + content
                            )
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            # Record the per-host timeout and surface an escalation hint so
            # the model doesn't retry in place (the reverse-skill trace
            # burned multiple rounds on raw.githubusercontent timeouts).
            # The hint is host-agnostic — domain-specific mirrors (jsDelivr
            # for raw GitHub, etc.) are taught in the skill/prompt layer.
            from deepseek_tui.tools.network_escalation import (
                record_host_timeout,
                should_escalate,
            )

            record_host_timeout(context, url)
            hint = ""
            if should_escalate(context, url):
                hint = (
                    " This host has timed out repeatedly — consider a "
                    "mirror/CDN, web_search, or an alternative source."
                )
            raise ToolError(
                f"fetch_url timed out after {timeout:.0f}s fetching {url}.{hint}"
            ) from exc

        truncated = len(content) > max_chars
        if truncated:
            content = _truncate_text(content, max_chars)

        latency_ms = int((time.monotonic() - started) * 1000)
        return ToolResult(
            success=True,
            content=content,
            metadata={
                "url": final_url,
                "status_code": status_code,
                "content_type": content_type,
                "backend": backend,
                "latency_ms": latency_ms,
                "truncated": truncated,
                "max_chars": max_chars,
                "extract_error": extract_error or None,
            },
        )


class WebSearchTool(ToolSpec):
    def __init__(
        self,
        *,
        tavily_api_key: str | None = None,
        anysearch_api_key: str | None = None,
        api_key: str | None = None,
    ) -> None:
        # ``api_key`` kept for backward compatibility (maps to Tavily).
        self._tavily_api_key = (tavily_api_key or api_key or _TAVILY_API_KEY or "").strip()
        self._anysearch_api_key = (
            anysearch_api_key or _ANYSEARCH_API_KEY or ""
        ).strip()

    def name(self) -> str:
        return "web_search"

    def description(self) -> str:
        return (
            "Search the web via AnySearch and Tavily (when configured), "
            "merge results, and return titles, URLs, and snippets."
        )

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
        max_results = _optional_int(input_data, "max_results") or 8
        # getattr: tests (and embedders) may pass duck-typed contexts.
        timeout_ms = getattr(context, "timeout_ms", None)
        timeout = timeout_ms / 1000 if timeout_ms is not None else 30.0

        _check_network_policy("https://api.anysearch.com", "web_search", context)
        use_tavily = bool(self._tavily_api_key)
        if use_tavily:
            _check_network_policy("https://api.tavily.com", "web_search", context)

        errors: list[str] = []
        answer = ""
        hits: list[_SearchHit] = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            tasks: list[tuple[str, asyncio.Task[object]]] = []
            tasks.append(
                (
                    "anysearch",
                    asyncio.create_task(
                        _search_anysearch(
                            client,
                            query=query,
                            max_results=max_results,
                            api_key=self._anysearch_api_key or None,
                        )
                    ),
                )
            )
            if use_tavily:
                tasks.append(
                    (
                        "tavily",
                        asyncio.create_task(
                            _search_tavily(
                                client,
                                query=query,
                                max_results=max_results,
                                api_key=self._tavily_api_key,
                            )
                        ),
                    ),
                )

            for name, task in tasks:
                try:
                    outcome = await task
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                    continue
                if name == "anysearch":
                    hits.extend(outcome)  # type: ignore[arg-type]
                else:
                    tavily_hits, tavily_answer = outcome  # type: ignore[misc]
                    hits.extend(tavily_hits)
                    if tavily_answer:
                        answer = tavily_answer

        merged = _merge_hits(hits, max_results)
        if not merged:
            detail = "; ".join(errors) if errors else "no results"
            raise ToolError(f"web_search failed: {detail}")

        sources = sorted({hit.source for hit in merged})
        lines: list[str] = []
        if answer:
            lines.append(f"Answer: {answer}\n")
        for i, hit in enumerate(merged, 1):
            tag = f"[{hit.source}] " if len(sources) > 1 else ""
            lines.append(f"{i}. {hit.title}\n   {hit.url}\n   {tag}{hit.snippet}")

        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "query": query,
                "result_count": len(merged),
                "results": [
                    {
                        "title": h.title,
                        "url": h.url,
                        "content": h.snippet,
                        "source": h.source,
                        "score": h.score,
                    }
                    for h in merged
                ],
                "sources": sources,
                "errors": errors,
            },
        )


async def _search_anysearch(
    client: httpx.AsyncClient,
    *,
    query: str,
    max_results: int,
    api_key: str | None,
) -> list[_SearchHit]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"query": query, "max_results": max_results}
    try:
        resp = await client.post(_ANYSEARCH_SEARCH_URL, json=payload, headers=headers)
    except (httpx.HTTPError, OSError) as exc:
        raise ToolError(f"AnySearch request failed: {exc}") from exc

    if not resp.is_success:
        raise ToolError(
            f"AnySearch API returned {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    if not isinstance(data, dict):
        raise ToolError("AnySearch API returned non-object JSON")

    code = data.get("code")
    if code is not None and code != 0:
        raise ToolError(
            f"AnySearch error {code}: {str(data.get('message', ''))[:200]}"
        )

    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    raw_results = payload.get("results", []) if isinstance(payload, dict) else []

    hits: list[_SearchHit] = []
    for item in raw_results[:max_results]:
        if not isinstance(item, dict):
            continue
        snippet = (item.get("content") or item.get("description") or "").strip()
        hits.append(
            _SearchHit(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                snippet=snippet,
                source="anysearch",
                score=float(item.get("quality_score") or item.get("score") or 0.0),
            )
        )
    return hits


async def _search_tavily(
    client: httpx.AsyncClient,
    *,
    query: str,
    max_results: int,
    api_key: str,
) -> tuple[list[_SearchHit], str]:
    payload = {
        "query": query,
        "max_results": max_results,
        "include_answer": True,
    }
    try:
        resp = await client.post(
            _TAVILY_SEARCH_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
    except (httpx.HTTPError, OSError) as exc:
        raise ToolError(f"Tavily request failed: {exc}") from exc

    if not resp.is_success:
        raise ToolError(f"Tavily API returned {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    hits = [
        _SearchHit(
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
            snippet=str(item.get("content", "")).strip(),
            source="tavily",
            score=float(item.get("score") or 0.0),
        )
        for item in data.get("results", [])[:max_results]
    ]
    return hits, str(data.get("answer", "") or "")


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip().lower())
    host = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/") or ""
    return f"{host}{path}"


def _merge_hits(hits: list[_SearchHit], max_results: int) -> list[_SearchHit]:
    ranked = sorted(hits, key=lambda h: h.score, reverse=True)
    seen: set[str] = set()
    merged: list[_SearchHit] = []
    for hit in ranked:
        if not hit.url.strip():
            continue
        key = _normalize_url(hit.url)
        if key in seen:
            continue
        seen.add(key)
        merged.append(hit)
        if len(merged) >= max_results:
            break
    return merged


def _check_network_policy(url: str, tool_name: str, context: ToolContext) -> None:
    """Enforce network policy if configured. Raises ToolError on DENY."""
    # getattr: tests (and embedders) may pass duck-typed contexts.
    policy = getattr(context, "network_policy", None)
    if policy is None:
        return
    from deepseek_tui.policy.network import Decision

    decision = policy.evaluate(url, tool_name)
    if decision == Decision.DENY:
        raise ToolError(
            f"Network access denied for {url} by policy. "
            "Configure allow-list in config.toml [network_policy]."
        )
    # PROMPT → for now treat as allow (full interactive prompt requires TUI hook)
    # TODO: wire interactive approval when TUI approval handler is available


def _require_http_url(url: str) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ToolError("URL must use http or https scheme")
    if not parsed.netloc:
        raise ToolError("URL must include a host")


def _is_direct_resource_url(url: str) -> bool:
    """Fast path: plain files where raw GET is already the payload."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    if host in ("raw.githubusercontent.com", "gist.githubusercontent.com"):
        return True
    if path.endswith((".md", ".txt", ".json", ".xml", ".csv", ".yaml", ".yml")):
        return True
    return False


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[... truncated to max_chars ...]"


def _mcp_text_content(result: dict[str, object]) -> str:
    parts: list[str] = []
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
    return "\n".join(parts).strip()


async def _anysearch_extract(
    client: httpx.AsyncClient,
    *,
    url: str,
    api_key: str | None,
    context: ToolContext,
) -> str:
    _check_network_policy(_ANYSEARCH_MCP_URL, "fetch_url", context)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "extract", "arguments": {"url": url}},
    }
    try:
        resp = await client.post(_ANYSEARCH_MCP_URL, json=payload, headers=headers)
    except (httpx.HTTPError, OSError) as exc:
        raise ToolError(f"AnySearch extract request failed: {exc}") from exc

    if not resp.is_success:
        raise ToolError(
            f"AnySearch extract HTTP {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    if not isinstance(data, dict):
        raise ToolError("AnySearch extract returned non-object JSON")

    result = data.get("result")
    if not isinstance(result, dict):
        raise ToolError("AnySearch extract missing result")

    if result.get("isError"):
        message = _mcp_text_content(result) or "unknown extract error"
        raise ToolError(message[:300])

    text = _mcp_text_content(result)
    if not text:
        raise ToolError("AnySearch extract returned empty content")
    return text


async def _http_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    merged = {"User-Agent": _BROWSER_UA}
    if headers:
        merged.update(headers)
    try:
        return await client.get(
            url, params=params, headers=merged, follow_redirects=True
        )
    except (httpx.HTTPError, OSError) as exc:
        raise ToolError(f"Failed to fetch URL {url}: {exc}") from exc


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
            return await _http_get(client, url, params=params, headers=headers)
    except (httpx.HTTPError, OSError) as exc:
        raise ToolError(f"Failed to fetch URL {url}: {exc}") from exc
