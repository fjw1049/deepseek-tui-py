"""No relevance rules: complete traversal, current conditions, explicit saves."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from deepseek_tui.config.models import MemoryConfig
from deepseek_tui.engine.memory import MemorySession
from deepseek_tui.integrations.skills import Skill, SkillRegistry
from deepseek_tui.protocol.messages import Message, MessageOrigin
from deepseek_tui.state.memory import MemoryStore
from deepseek_tui.tools.knowledge import SkillSearchTool
from deepseek_tui.tools.memory import MemoryReadTool
from deepseek_tui.tools.registry import ToolContext
from tests.test_project_memory import save


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.mark.parametrize(
    "condition",
    [
        {"branch": "release-b"},
        {"topic": "second"},
        {"kind": "decision"},
        {"expires_at": "2099-01-01T00:00:00Z"},
        {"files": ["version.txt"]},
    ],
)
def test_identical_text_preserves_distinct_conditions(workspace, condition):
    (workspace / "version.txt").write_text("v1")
    store = MemoryStore(workspace)
    first = save(store, "Use staging", branch="release-a")
    args = {"branch": "release-a", **condition}
    second = save(store, "Use staging", **args)
    assert first.id != second.id
    assert save(store, "Use staging", **args).id == second.id


async def test_expiry_and_external_file_change_rechecked_without_write_tool(workspace):
    store = MemoryStore(workspace)
    (workspace / "version.txt").write_text("v1")
    now = datetime.now(timezone.utc)
    expiring = save(
        store, "Temporary endpoint", expires_at=(now + timedelta(seconds=10)).isoformat()
    )
    conditional = save(store, "Legacy build command", files=["version.txt"])
    session = MemorySession(workspace, MemoryConfig())
    messages = [Message.user("continue")]
    await session.recall(messages, "continue")
    assert expiring.id in messages[0].text_content()
    assert conditional.id in messages[0].text_content()
    (workspace / "version.txt").write_text("v2")
    with patch("deepseek_tui.state.memory.datetime") as clock:
        clock.now.return_value = now + timedelta(seconds=11)
        await session.recall(messages, "continue")
    assert all(m.origin is not MessageOrigin.MEMORY_RECALL for m in messages)


async def test_oversized_memory_can_be_fully_read_without_query_or_truncation_gaps(workspace):
    store = MemoryStore(workspace)
    expected = {save(store, f"{n}: " + "保留这个完整证据。" * 160).id for n in range(25)}
    session = MemorySession(workspace, MemoryConfig(max_recall_chars=512))
    messages = [Message.user("Quelle est notre procédure ?")]
    await session.recall(messages, "Quelle est notre procédure ?")
    assert "memory_read" in messages[-1].text_content()
    assert len(messages[-1].text_content()) <= 512
    tool = MemoryReadTool()
    context = ToolContext(working_directory=workspace)
    seen, offset = set(), 0
    while offset is not None:
        page = json.loads((await tool.execute({"offset": offset, "limit": 20}, context)).content)
        assert not seen.intersection(e["id"] for e in page["entries"])
        seen.update(e["id"] for e in page["entries"])
        offset = page["next_offset"]
    assert seen == expected
    assert (
        json.loads((await tool.execute({"query": "nonexistent"}, context)).content)["total_matches"]
        == 0
    )


async def test_skills_can_be_discovered_without_matching_language_or_scoring(workspace):
    skills = [
        Skill(f"skill-{i:03}", f"能力{i}", "body", workspace / str(i) / "SKILL.md")
        for i in range(45)
    ]
    skills.append(
        Skill(
            "private",
            "hidden",
            "body",
            workspace / "private" / "SKILL.md",
            disable_model_invocation=True,
        )
    )
    context = ToolContext(
        working_directory=workspace, metadata={"skill_registry": SkillRegistry(skills=skills)}
    )
    tool = SkillSearchTool()
    assert (
        json.loads((await tool.execute({"query": "Find a financial workflow"}, context)).content)[
            "matches"
        ]
        == []
    )
    names, offset = [], 0
    while offset is not None:
        page = json.loads((await tool.execute({"offset": offset}, context)).content)
        names.extend(s["name"] for s in page["matches"])
        offset = page["next_offset"]
    assert names == [s.name for s in skills[:-1]]


def test_legacy_capture_settings_cannot_enable_extraction():
    cfg = MemoryConfig(capture_candidates=True, idle_seconds=0, max_candidates_per_pass=20)
    assert cfg.model_dump() == {"enabled": True, "auto_recall": True, "max_recall_chars": 4000}
    assert not hasattr(MemorySession, "schedule_capture")


def test_legacy_candidate_requires_live_source_before_acceptance(workspace):
    import hashlib

    from deepseek_tui.engine.transcript import Transcript
    from deepseek_tui.state.memory_capture import committed_users

    log = Transcript(workspace / "legacy.jsonl")
    log.record(
        "commit",
        [Message.user("Use local validation before release.", origin=MessageOrigin.REAL_USER)],
        turn_id="old-turn",
    )
    text, turn_id, seq = committed_users(log.path)[0]
    store = MemoryStore(workspace)
    entry = store.write(
        action="propose",
        content=text,
        source={
            "type": "local_candidate",
            "transcript": str(log.path),
            "turn_id": turn_id,
            "seq": str(seq),
            "quote_hash": hashlib.sha256(text.encode()).hexdigest(),
        },
    )
    assert store.stale_reason(entry) is None
    log.path.unlink()
    with pytest.raises(ValueError, match="no longer eligible"):
        store.write(action="accept", entry_id=entry.id, revision=entry.revision, source={})
