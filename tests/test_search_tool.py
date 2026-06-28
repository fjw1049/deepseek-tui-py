"""Regression tests for grep_files context-explosion guardrails.

A single `grep_files pattern='vitest' root=packages/workbench` walked a 1 GB
``node_modules`` and returned 2128 (often minified) matches, all joined into one
tool result — blowing the turn context to ~5.5M tokens (budget ~995K). The fix
prunes heavy directories during traversal and hard-caps match count and line
length. These tests pin all three behaviors.
"""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.search import _MAX_LINE_LEN, _MAX_MATCHES, GrepFilesTool


async def test_grep_skips_ignored_dirs(tmp_path: Path):
    (tmp_path / "src.py").write_text("needle here\n", encoding="utf-8")
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "bundle.js").write_text("needle in vendored code\n", encoding="utf-8")

    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": "."}, ToolContext(working_directory=tmp_path)
    )

    assert result.metadata["count"] == 1, "node_modules match should be pruned"
    assert "node_modules" not in result.content


async def test_grep_caps_match_count(tmp_path: Path):
    lines = "\n".join("needle" for _ in range(_MAX_MATCHES + 50))
    (tmp_path / "big.txt").write_text(lines, encoding="utf-8")

    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": "."}, ToolContext(working_directory=tmp_path)
    )

    assert result.metadata["count"] == _MAX_MATCHES + 50
    assert result.metadata["shown"] == _MAX_MATCHES
    assert result.metadata["truncated"] is True
    assert result.content.count("big.txt") == _MAX_MATCHES
    assert "of 250 matches" in result.content


async def test_grep_caps_line_length(tmp_path: Path):
    long_line = "needle" + "x" * (_MAX_LINE_LEN * 2)
    (tmp_path / "min.js").write_text(long_line + "\n", encoding="utf-8")

    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": "."}, ToolContext(working_directory=tmp_path)
    )

    assert "(line truncated)" in result.content
    # The emitted match line must be bounded (path prefix + capped body).
    body = result.content.splitlines()[0]
    assert len(body) < len(long_line)


async def test_grep_normal_result_not_truncated(tmp_path: Path):
    (tmp_path / "a.py").write_text("hello\nworld\n", encoding="utf-8")

    result = await GrepFilesTool().execute(
        {"pattern": "hello", "path": "."}, ToolContext(working_directory=tmp_path)
    )

    assert result.metadata["count"] == 1
    assert result.metadata["truncated"] is False
    assert "truncated" not in result.content
