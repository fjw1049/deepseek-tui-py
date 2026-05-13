"""Parity tests for P1 knowledge tools (remember, note, review, rlm_query, etc.).

Mirrors behavior from Rust tools/{remember,review,recall_archive}.rs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.knowledge_tools import (
    NoteTool,
    PlanUpdateTool,
    RecallArchiveTool,
    RememberTool,
    ReviewTool,
    RlmQueryTool,
    SkillLoadTool,
    _bm25_search,
    _tokenize,
)


def _make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(working_directory=tmp_path, trust_mode=False)


# ===========================================================================
# remember tool
# ===========================================================================


@pytest.mark.asyncio
async def test_remember_appends_bullet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    memory_file = tmp_path / "memory.md"
    monkeypatch.setenv("DEEPSEEK_MEMORY_PATH", str(memory_file))
    ctx = _make_context(tmp_path)
    tool = RememberTool()

    result = await tool.execute({"note": "Use 4 spaces for indentation"}, ctx)
    assert result.success
    assert "4 spaces" in result.content

    content = memory_file.read_text()
    assert "4 spaces" in content
    assert content.startswith("- (")


@pytest.mark.asyncio
async def test_remember_rejects_empty_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_MEMORY_PATH", str(tmp_path / "m.md"))
    ctx = _make_context(tmp_path)
    tool = RememberTool()

    from deepseek_tui.tools.base import ToolError

    with pytest.raises(ToolError):
        await tool.execute({"note": ""}, ctx)


@pytest.mark.asyncio
async def test_remember_multiple_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    memory_file = tmp_path / "memory.md"
    monkeypatch.setenv("DEEPSEEK_MEMORY_PATH", str(memory_file))
    ctx = _make_context(tmp_path)
    tool = RememberTool()

    await tool.execute({"note": "first"}, ctx)
    await tool.execute({"note": "second"}, ctx)

    lines = memory_file.read_text().strip().splitlines()
    assert len(lines) == 2
    assert "first" in lines[0]
    assert "second" in lines[1]


# ===========================================================================
# note tool
# ===========================================================================


@pytest.mark.asyncio
async def test_note_appends_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    notes_file = tmp_path / "notes.txt"
    monkeypatch.setenv("DEEPSEEK_NOTES_PATH", str(notes_file))
    ctx = _make_context(tmp_path)
    tool = NoteTool()

    result = await tool.execute({"content": "checkpoint reached"}, ctx)
    assert result.success
    assert "Note appended" in result.content

    assert notes_file.exists()
    body = notes_file.read_text()
    assert "checkpoint reached" in body
    assert "---" in body


@pytest.mark.asyncio
async def test_note_rejects_missing_content(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    tool = NoteTool()

    from deepseek_tui.tools.base import ToolError

    with pytest.raises(ToolError):
        await tool.execute({}, ctx)


# ===========================================================================
# plan_update tool
# ===========================================================================


@pytest.mark.asyncio
async def test_plan_update_writes_file(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    tool = PlanUpdateTool()
    plan_text = "## Plan\n1. Do X\n2. Do Y"

    result = await tool.execute({"plan": plan_text}, ctx)
    assert result.success

    plan_path = tmp_path / ".deepseek" / "plan.md"
    assert plan_path.read_text() == plan_text


@pytest.mark.asyncio
async def test_plan_update_overwrites(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    tool = PlanUpdateTool()

    await tool.execute({"plan": "v1"}, ctx)
    await tool.execute({"plan": "v2"}, ctx)

    plan_path = tmp_path / ".deepseek" / "plan.md"
    assert plan_path.read_text() == "v2"


# ===========================================================================
# skill_load tool
# ===========================================================================


@pytest.mark.asyncio
async def test_skill_load_by_path(tmp_path: Path) -> None:
    skill_file = tmp_path / "test_skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("# My Skill\nInstructions here.")
    ctx = _make_context(tmp_path)
    tool = SkillLoadTool()

    result = await tool.execute({"path": str(skill_file)}, ctx)
    assert result.success
    assert "My Skill" in result.content


@pytest.mark.asyncio
async def test_skill_load_missing_raises(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    tool = SkillLoadTool()

    from deepseek_tui.tools.base import ToolError

    with pytest.raises(ToolError, match="not found"):
        await tool.execute({"path": "/nonexistent/SKILL.md"}, ctx)


@pytest.mark.asyncio
async def test_skill_load_by_name(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".deepseek" / "skills" / "review" / "SKILL.md"
    skill_dir.parent.mkdir(parents=True)
    skill_dir.write_text("Review skill content")
    ctx = _make_context(tmp_path)
    tool = SkillLoadTool()

    result = await tool.execute({"skill_name": "review"}, ctx)
    assert result.success
    assert "Review skill content" in result.content


@pytest.mark.asyncio
async def test_skill_load_requires_name_or_path(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    tool = SkillLoadTool()

    from deepseek_tui.tools.base import ToolError

    with pytest.raises(ToolError, match="skill_name.*path"):
        await tool.execute({}, ctx)


# ===========================================================================
# recall_archive tool — BM25 search
# ===========================================================================


def test_tokenize_basic() -> None:
    tokens = _tokenize("Hello World! foo_bar 123")
    assert tokens == ["hello", "world", "foo_bar", "123"]


def test_bm25_search_basic(tmp_path: Path) -> None:
    archives_dir = tmp_path / "cycles"
    archives_dir.mkdir()

    messages = [
        {"role": "user", "content": "Please fix the authentication bug"},
        {"role": "assistant", "content": "I'll look at the login module"},
        {"role": "user", "content": "The database connection is slow"},
    ]
    archive_file = archives_dir / "cycle_1.jsonl"
    archive_file.write_text("\n".join(json.dumps(m) for m in messages))

    hits = _bm25_search(archives_dir, "authentication login", None, 3)
    assert len(hits) >= 1
    assert hits[0]["role"] in ("user", "assistant")
    assert hits[0]["score"] > 0


def test_bm25_search_cycle_filter(tmp_path: Path) -> None:
    archives_dir = tmp_path / "cycles"
    archives_dir.mkdir()

    (archives_dir / "cycle_1.jsonl").write_text(
        json.dumps({"role": "user", "content": "hello world"})
    )
    (archives_dir / "cycle_2.jsonl").write_text(
        json.dumps({"role": "user", "content": "hello earth"})
    )

    hits = _bm25_search(archives_dir, "hello", 1, 5)
    assert all(h["cycle"] == 1 for h in hits)


def test_bm25_search_no_archives(tmp_path: Path) -> None:
    archives_dir = tmp_path / "cycles"
    archives_dir.mkdir()
    hits = _bm25_search(archives_dir, "anything", None, 5)
    assert hits == []


@pytest.mark.asyncio
async def test_recall_archive_no_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_ARCHIVES_DIR", str(tmp_path / "nonexistent"))
    ctx = _make_context(tmp_path)
    tool = RecallArchiveTool()

    result = await tool.execute({"query": "test"}, ctx)
    assert result.success
    assert "No cycle archives" in result.content


# ===========================================================================
# rlm_query tool — structure/schema tests (no real LLM call)
# ===========================================================================


def test_rlm_query_schema() -> None:
    tool = RlmQueryTool()
    schema = tool.input_schema()
    assert "query" in schema["properties"]
    assert "query" in schema["required"]


def test_review_tool_schema() -> None:
    tool = ReviewTool()
    schema = tool.input_schema()
    assert "target" in schema["properties"]
    assert "target" in schema["required"]


# ===========================================================================
# review tool — gather_review_content tests (file mode)
# ===========================================================================


@pytest.mark.asyncio
async def test_review_file_not_found(tmp_path: Path) -> None:
    from deepseek_tui.tools.base import ToolError
    from deepseek_tui.tools.knowledge_tools import _gather_review_content

    ctx = _make_context(tmp_path)
    with pytest.raises(ToolError, match="not found"):
        _gather_review_content("nonexistent.py", ctx, 200_000)


@pytest.mark.asyncio
async def test_review_reads_file(tmp_path: Path) -> None:
    from deepseek_tui.tools.knowledge_tools import _gather_review_content

    test_file = tmp_path / "main.py"
    test_file.write_text("def hello():\n    return 'world'\n")
    ctx = _make_context(tmp_path)

    content = _gather_review_content("main.py", ctx, 200_000)
    assert "def hello" in content


@pytest.mark.asyncio
async def test_review_truncates(tmp_path: Path) -> None:
    from deepseek_tui.tools.knowledge_tools import _gather_review_content

    test_file = tmp_path / "big.py"
    test_file.write_text("x" * 10000)
    ctx = _make_context(tmp_path)

    content = _gather_review_content("big.py", ctx, 100)
    assert len(content) == 100


# ===========================================================================
# builder registration
# ===========================================================================


def test_builder_registers_knowledge_tools() -> None:
    from deepseek_tui.tools.builder import build_default_registry

    registry = build_default_registry()
    names = list(registry.names())

    expected_tools = [
        "remember", "note", "update_plan", "rlm_query", "skill_load", "recall_archive",
    ]
    for expected in expected_tools:
        assert expected in names, f"'{expected}' not registered"


def test_builder_review_requires_web_search() -> None:
    from deepseek_tui.config.models import Config
    from deepseek_tui.tools.builder import build_default_registry

    cfg = Config()
    cfg.features.web_search = False
    registry = build_default_registry(cfg)
    names = list(registry.names())
    assert "review" not in names

    cfg.features.web_search = True
    registry = build_default_registry(cfg)
    names = list(registry.names())
    assert "review" in names
