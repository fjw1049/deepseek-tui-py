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


async def test_grep_output_mode_files_with_matches(tmp_path: Path):
    (tmp_path / "a.py").write_text("needle\nneedle\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("nothing\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("needle\n", encoding="utf-8")

    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": ".", "output_mode": "files_with_matches"},
        ToolContext(working_directory=tmp_path),
    )

    lines = result.content.splitlines()
    assert len(lines) == 2
    assert any(line.endswith("a.py") for line in lines)
    assert any(line.endswith("c.py") for line in lines)
    assert not any("b.py" in line for line in lines)
    assert result.metadata["count"] == 3  # true match total across files


async def test_grep_output_mode_count_matches(tmp_path: Path):
    (tmp_path / "a.py").write_text("needle\nneedle\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("needle\n", encoding="utf-8")

    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": ".", "output_mode": "count_matches"},
        ToolContext(working_directory=tmp_path),
    )

    lines = result.content.splitlines()
    assert any(line.endswith("a.py:2") for line in lines)
    assert any(line.endswith("c.py:1") for line in lines)
    assert lines[-1] == "total: 3"


async def test_grep_content_mode_has_line_numbers(tmp_path: Path):
    (tmp_path / "a.py").write_text("x\nneedle\n", encoding="utf-8")

    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": ".", "output_mode": "content"},
        ToolContext(working_directory=tmp_path),
    )

    assert result.content.splitlines()[0].endswith("a.py:2:needle")


async def test_grep_context_lines(tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "one\ntwo\nneedle\nfour\nfive\n", encoding="utf-8"
    )

    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": ".", "-C": 1},
        ToolContext(working_directory=tmp_path),
    )

    lines = result.content.splitlines()
    assert len(lines) == 3
    assert lines[0].endswith("a.py-2-two")       # before context
    assert lines[1].endswith("a.py:3:needle")    # the match
    assert lines[2].endswith("a.py-4-four")      # after context


async def test_grep_context_a_b_sides(tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "one\ntwo\nneedle\nfour\nfive\n", encoding="utf-8"
    )

    before_only = await GrepFilesTool().execute(
        {"pattern": "needle", "path": ".", "-B": 2},
        ToolContext(working_directory=tmp_path),
    )
    before_lines = before_only.content.splitlines()
    assert before_lines[0].endswith("a.py-1-one")
    assert before_lines[1].endswith("a.py-2-two")
    assert before_lines[2].endswith("a.py:3:needle")
    assert len(before_lines) == 3

    after_only = await GrepFilesTool().execute(
        {"pattern": "needle", "path": ".", "-A": 1},
        ToolContext(working_directory=tmp_path),
    )
    assert after_only.content.splitlines()[-1].endswith("a.py-4-four")


async def test_grep_head_limit_caps_matches(tmp_path: Path):
    (tmp_path / "big.txt").write_text(
        "\n".join("needle" for _ in range(10)) + "\n", encoding="utf-8"
    )

    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": ".", "head_limit": 3},
        ToolContext(working_directory=tmp_path),
    )

    assert result.metadata["count"] == 10
    assert result.metadata["shown"] == 3
    assert result.metadata["truncated"] is True
    assert "showing 3 of 10 matches" in result.content


async def test_grep_adjacent_match_not_marked_as_context(tmp_path: Path):
    """A match line inside a previous match's context window is still a match:
    it must render as `path:N:` (not `path-N-`) and count as shown."""
    (tmp_path / "a.txt").write_text(
        "one\ntwo\nneedle\nneedle\nfive\n", encoding="utf-8"
    )

    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": ".", "-C": 1},
        ToolContext(working_directory=tmp_path),
    )

    assert "a.txt:3:needle" in result.content
    assert "a.txt:4:needle" in result.content
    assert "a.txt-4-needle" not in result.content
    # Genuine context lines still render as context.
    assert "a.txt-2-two" in result.content
    assert "a.txt-5-five" in result.content
    assert result.metadata["shown"] == 2
