from __future__ import annotations

import pytest

from deepseek_tui.tools.registry import ToolError
from deepseek_tui.tools.web import (
    FetchUrlTool,
    _is_direct_resource_url,
    _reject_private_fetch_url,
    _truncate_text,
)


def test_is_direct_resource_url() -> None:
    assert _is_direct_resource_url("https://raw.githubusercontent.com/o/r/main/README.md")
    assert _is_direct_resource_url("https://example.com/doc.txt")
    assert not _is_direct_resource_url("https://go.dev/doc/go1.22")
    assert not _is_direct_resource_url("https://zhuanlan.zhihu.com/p/123")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8787/v1/tools",
        "http://localhost/secret",
        "http://10.0.0.1/admin",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
    ],
)
def test_fetch_url_blocks_loopback_and_private(url: str) -> None:
    with pytest.raises(ToolError, match="loopback/private"):
        _reject_private_fetch_url(url)


def test_fetch_url_allows_public_literal() -> None:
    _reject_private_fetch_url("https://8.8.8.8/doc")


def test_fetch_url_rejects_url_credentials() -> None:
    with pytest.raises(ToolError, match="credentials"):
        _reject_private_fetch_url("https://user:pass@8.8.8.8/doc")


@pytest.mark.asyncio
async def test_http_get_rechecks_redirect_targets() -> None:
    """A public URL must not 302 the fetch into a loopback/private host."""
    import httpx

    from deepseek_tui.tools.web import _http_get

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        return httpx.Response(200, text="metadata")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ToolError, match="loopback/private"):
            await _http_get(client, "https://example.com/doc")


@pytest.mark.asyncio
async def test_http_get_follows_safe_redirect() -> None:
    import httpx

    from deepseek_tui.tools.web import _http_get

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="final")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await _http_get(client, "https://8.8.8.8/old")
    assert response.status_code == 200
    assert response.text == "final"


@pytest.mark.asyncio
async def test_http_get_checks_hosts_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    import httpx

    from deepseek_tui.tools import web

    main_thread = threading.get_ident()
    checked_on: list[int] = []
    monkeypatch.setattr(
        web, "_reject_private_fetch_url",
        lambda url: checked_on.append(threading.get_ident()),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
    ) as client:
        await web._http_get(client, "https://8.8.8.8/doc")
    assert checked_on and all(thread != main_thread for thread in checked_on)


@pytest.mark.asyncio
async def test_http_get_stops_reading_at_byte_limit() -> None:
    import httpx

    from deepseek_tui.tools.web import _http_get

    chunks_read = 0

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal chunks_read
            for _ in range(100):
                chunks_read += 1
                yield b"x" * 100

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Body()))
    ) as client:
        response = await _http_get(client, "https://8.8.8.8/doc", max_bytes=150)
    assert len(response.content) == 150
    assert response.extensions["body_truncated"] is True
    assert chunks_read == 2


def test_html_fallback_removes_hidden_content() -> None:
    from deepseek_tui.tools.web import _html_to_text

    result = _html_to_text(
        "<title>Page</title><script>secret()</script>"
        "<p>Hello <b>world</b></p><style>.x{}</style>"
    )
    assert "Hello world" in result
    assert "secret" not in result
    assert ".x" not in result


def test_truncate_text() -> None:
    assert _truncate_text("abc", 10) == "abc"
    assert _truncate_text("abcdefghij", 5).endswith("max_chars ...]")


@pytest.mark.asyncio
async def test_fetch_url_extract_go_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live extract when network available; skip if AnySearch unreachable."""
    from pathlib import Path

    from deepseek_tui.config.loader import ConfigLoader
    from deepseek_tui.tools.registry import ToolContext

    cfg = ConfigLoader().load(workspace=Path.cwd())
    if not cfg.anysearch_api_key:
        pytest.skip("anysearch_api_key not configured")

    tool = FetchUrlTool(anysearch_api_key=cfg.anysearch_api_key)
    ctx = ToolContext(working_directory=Path.cwd())
    try:
        result = await tool.execute(
            {
                "url": "https://go.dev/doc/go1.22",
                "max_chars": 5000,
            },
            ctx,
        )
    except Exception as exc:
        pytest.skip(f"network/AnySearch unavailable: {exc}")

    assert result.success
    assert result.metadata.get("backend") == "anysearch_extract"
    assert "Go 1.22" in result.content
    assert len(result.content) <= 5100
