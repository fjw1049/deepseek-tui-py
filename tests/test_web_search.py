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
async def test_web_search_merges_anysearch_and_tavily(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_anysearch(
        _client: object,
        *,
        query: str,
        max_results: int,
        api_key: str | None,
    ) -> list[_SearchHit]:
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
        assert api_key == "tv-key"
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

    monkeypatch.setattr(
        "deepseek_tui.tools.web._search_anysearch",
        fake_anysearch,
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

    tool = WebSearchTool(tavily_api_key="tv-key", anysearch_api_key="as-key")
    result = await tool.execute({"query": "test query"}, context=object())  # type: ignore[arg-type]

    assert result.success
    assert "Answer: summary answer" in result.content
    assert "https://a.example/x" in result.content
    assert "https://b.example/y" in result.content
    assert result.metadata["sources"] == ["anysearch", "tavily"]
    assert result.metadata["result_count"] == 2
