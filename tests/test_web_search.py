from __future__ import annotations

import pytest

from deepseek_tui.tools.web import WebSearchTool, _merge_hits, _normalize_url, _SearchHit


def test_normalize_url_strips_www_and_trailing_slash() -> None:
    assert _normalize_url("https://WWW.Example.com/path/") == "example.com/path"


def test_merge_hits_dedupes_by_url_and_caps() -> None:
    hits = [
        _SearchHit("A", "https://ex.com/a", "one", "anysearch", score=0.9),
        _SearchHit("B", "https://www.ex.com/a/", "two", "tavily", score=0.5),
        _SearchHit("C", "https://ex.com/b", "three", "anysearch", score=0.8),
    ]
    merged = _merge_hits(hits, 2)
    assert len(merged) == 2
    assert merged[0].title == "A"
    assert merged[1].title == "C"


@pytest.mark.asyncio
async def test_web_search_uses_first_provider_when_successful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    async def fake_anysearch(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str | None,
    ) -> list[_SearchHit]:
        called.append("anysearch")
        assert query == "test query"
        assert api_key == "as-key"
        return [
            _SearchHit("Any", "https://a.example/x", "snippet a", "anysearch", score=0.9),
        ]

    async def fake_tavily(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str,
    ) -> tuple[list[_SearchHit], str]:
        called.append("tavily")
        return (
            [
                _SearchHit(
                    "Tav",
                    "https://b.example/y",
                    "snippet b",
                    "tavily",
                    score=0.7,
                ),
            ],
            "summary answer",
        )

    monkeypatch.setattr("deepseek_tui.tools.web._search_anysearch", fake_anysearch)
    monkeypatch.setattr("deepseek_tui.tools.web._search_tavily", fake_tavily)

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "deepseek_tui.tools.web.httpx.AsyncClient",
        lambda **_kwargs: _FakeClient(),
    )

    tool = WebSearchTool(
        tavily_api_key="tv-key",
        anysearch_api_key="as-key",
        providers=["anysearch", "tavily"],
    )
    result = await tool.execute({"query": "test query"}, context=object())  # type: ignore[arg-type]

    assert result.success
    assert called == ["anysearch"]
    assert "https://a.example/x" in result.content
    assert "https://b.example/y" not in result.content
    assert result.metadata["provider"] == "anysearch"
    assert result.metadata["sources"] == ["anysearch"]


@pytest.mark.asyncio
async def test_web_search_falls_back_when_first_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    async def fake_anysearch(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str | None,
    ) -> list[_SearchHit]:
        called.append("anysearch")
        raise RuntimeError("anysearch down")

    async def fake_tavily(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str,
    ) -> tuple[list[_SearchHit], str]:
        called.append("tavily")
        return (
            [_SearchHit("Tav", "https://b.example/y", "snippet b", "tavily", score=0.7)],
            "summary answer",
        )

    monkeypatch.setattr("deepseek_tui.tools.web._search_anysearch", fake_anysearch)
    monkeypatch.setattr("deepseek_tui.tools.web._search_tavily", fake_tavily)

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "deepseek_tui.tools.web.httpx.AsyncClient",
        lambda **_kwargs: _FakeClient(),
    )

    tool = WebSearchTool(
        tavily_api_key="tv-key",
        anysearch_api_key="as-key",
        providers=["anysearch", "tavily"],
    )
    result = await tool.execute({"query": "fallback"}, context=object())  # type: ignore[arg-type]

    assert result.success
    assert called == ["anysearch", "tavily"]
    assert "Answer: summary answer" in result.content
    assert result.metadata["provider"] == "tavily"
    assert "anysearch:" in ";".join(result.metadata["errors"])


@pytest.mark.asyncio
async def test_web_search_falls_back_when_first_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    async def fake_anysearch(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str | None,
    ) -> list[_SearchHit]:
        called.append("anysearch")
        return []

    async def fake_tavily(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str,
    ) -> tuple[list[_SearchHit], str]:
        called.append("tavily")
        return (
            [_SearchHit("Tav", "https://b.example/y", "b", "tavily", score=0.7)],
            "",
        )

    monkeypatch.setattr("deepseek_tui.tools.web._search_anysearch", fake_anysearch)
    monkeypatch.setattr("deepseek_tui.tools.web._search_tavily", fake_tavily)

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "deepseek_tui.tools.web.httpx.AsyncClient",
        lambda **_kwargs: _FakeClient(),
    )

    tool = WebSearchTool(
        tavily_api_key="tv-key",
        providers=["anysearch", "tavily"],
    )
    result = await tool.execute({"query": "empty first"}, context=object())  # type: ignore[arg-type]

    assert result.success
    assert called == ["anysearch", "tavily"]
    assert result.metadata["provider"] == "tavily"


@pytest.mark.asyncio
async def test_web_search_respects_providers_list(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    async def fake_anysearch(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str | None,
    ) -> list[_SearchHit]:
        called.append("anysearch")
        return [_SearchHit("Any", "https://a.example/x", "a", "anysearch", score=0.9)]

    async def fake_tavily(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str,
    ) -> tuple[list[_SearchHit], str]:
        called.append("tavily")
        return (
            [_SearchHit("Tav", "https://b.example/y", "b", "tavily", score=0.7)],
            "",
        )

    monkeypatch.setattr("deepseek_tui.tools.web._search_anysearch", fake_anysearch)
    monkeypatch.setattr("deepseek_tui.tools.web._search_tavily", fake_tavily)

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "deepseek_tui.tools.web.httpx.AsyncClient",
        lambda **_kwargs: _FakeClient(),
    )

    tool = WebSearchTool(
        tavily_api_key="tv-key",
        anysearch_api_key="as-key",
        providers=["tavily"],
    )
    result = await tool.execute({"query": "only tavily"}, context=object())  # type: ignore[arg-type]

    assert result.success
    assert called == ["tavily"]
    assert result.metadata["sources"] == ["tavily"]


@pytest.mark.asyncio
async def test_web_search_empty_providers_fails() -> None:
    tool = WebSearchTool(providers=[])
    with pytest.raises(Exception, match="no providers enabled"):
        await tool.execute({"query": "x"}, context=object())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_web_search_caps_huge_provider_snippets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tavily/AnySearch often return full-page text as 'content' — must not
    persist 100KB–400KB blobs into the turn item / soft-resume transcript.
    """
    from deepseek_tui.tools.web import (
        _MAX_SEARCH_CONTENT_CHARS,
        _MAX_SEARCH_SNIPPET_CHARS,
    )

    huge = "甲" * 50_000

    async def fake_tavily(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str,
    ) -> tuple[list[_SearchHit], str]:
        return (
            [
                _SearchHit("T", f"https://t.example/{i}", huge, "tavily", score=1.0)
                for i in range(8)
            ],
            "答" * 5_000,
        )

    monkeypatch.setattr("deepseek_tui.tools.web._search_tavily", fake_tavily)

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "deepseek_tui.tools.web.httpx.AsyncClient",
        lambda **_kwargs: _FakeClient(),
    )

    tool = WebSearchTool(tavily_api_key="tv-key", providers=["tavily"])
    result = await tool.execute({"query": "众安"}, context=object())  # type: ignore[arg-type]

    assert result.success
    assert len(result.content) <= _MAX_SEARCH_CONTENT_CHARS + 80
    for entry in result.metadata["results"]:
        assert len(entry["content"]) <= _MAX_SEARCH_SNIPPET_CHARS + 80
