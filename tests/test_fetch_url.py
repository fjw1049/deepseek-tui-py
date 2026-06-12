from __future__ import annotations

import pytest

from deepseek_tui.tools.web import (
    FetchUrlTool,
    _is_direct_resource_url,
    _truncate_text,
)


def test_is_direct_resource_url() -> None:
    assert _is_direct_resource_url("https://raw.githubusercontent.com/o/r/main/README.md")
    assert _is_direct_resource_url("https://example.com/doc.txt")
    assert not _is_direct_resource_url("https://go.dev/doc/go1.22")
    assert not _is_direct_resource_url("https://zhuanlan.zhihu.com/p/123")


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
