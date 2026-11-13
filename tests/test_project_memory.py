"""Offline memory lifecycle and real tool-dispatch regression tests."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.protocol.messages import Message, ToolResultBlock
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.state.memory import MemoryStore, render_memories
from deepseek_tui.tools.memory import MemoryReadTool, MemoryWriteTool
from deepseek_tui.tools.registry import ToolContext, ToolError
from tests.test_audit_tool_pipeline import _engine


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    root = tmp_path / "project"
    root.mkdir()
    return root


def save(store, content="接口测试需要 Redis", **kwargs):
    return store.write(action="remember", content=content, source={"thread": "t1"}, **kwargs)


def test_persistence_search_update_forget(workspace):
    store = MemoryStore(workspace)
    entry = save(store)
    save(store, "frontend uses pnpm")
    reopened = MemoryStore(workspace)
    assert reopened.read(query="接口测试")[0].id == entry.id
    assert reopened.read(query="unrelated zebra") == []
    assert save(store).id == entry.id
    updated = store.write(
        action="update",
        entry_id=entry.id,
        revision=1,
        content="接口测试现在使用 fake Redis",
        source={"thread": "t2"},
    )
    assert updated.revision == 2 and updated.source == {"thread": "t1"}
    assert updated.updated_source == {"thread": "t2"}
    with pytest.raises(ValueError, match="changed"):
        store.write(action="forget", entry_id=entry.id, revision=1, source={})
    store.write(action="forget", entry_id=entry.id, revision=2, source={})
    assert store.read(entry_id=entry.id) == []
    assert "接口测试现在使用 fake Redis" not in store.path.read_text()
    with pytest.raises(ValueError, match="forgotten"):
        store.write(action="propose", content="接口测试现在使用 fake Redis", source={})
    assert save(store, "接口测试现在使用 fake Redis").status == "active"


def test_project_isolation_and_empty_read_has_no_side_effects(workspace, tmp_path):
    empty = MemoryStore(workspace)
    assert empty.read() == [] and not empty.root.exists()
    entry = save(empty)
    other = tmp_path / "other"
    other.mkdir()
    store = MemoryStore(other)
    assert store.read() == []
    with pytest.raises(ValueError, match="not found"):
        store.write(action="forget", entry_id=entry.id, revision=1, source={})


def test_worktrees_share_but_clones_do_not(workspace, tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(workspace), *args], check=True, capture_output=True)

    git("init")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "fixture",
    )
    worktree = tmp_path / "worktree"
    git("worktree", "add", "--detach", str(worktree))
    clone = tmp_path / "clone"
    git("clone", str(workspace), str(clone))
    entry = save(MemoryStore(workspace))
    subdir = worktree / "src"
    subdir.mkdir()
    assert MemoryStore(subdir).read()[0].id == entry.id
    assert MemoryStore(clone).read() == []


def test_parallel_writers_and_revision_conflicts(workspace):
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda n: save(MemoryStore(workspace), f"unique entry {n}"), range(12)))
    assert len(MemoryStore(workspace).read(limit=20)) == 12


def test_output_budget_and_corrupt_storage_fail_closed(workspace):
    store = MemoryStore(workspace)
    for n in range(5):
        save(store, f"{n}:" + "界" * 1800)
    rendered = render_memories(store.read())
    assert len(rendered) <= 6000
    for line in rendered.splitlines():
        assert json.loads(line)["source"]
    store.path.write_text("broken")
    with pytest.raises(ValueError):
        save(store, "must not overwrite corruption")
    assert store.path.read_text() == "broken"


def test_symlink_storage_is_rejected(workspace, tmp_path):
    store = MemoryStore(workspace)
    store.root.mkdir(parents=True)
    target = tmp_path / "outside.json"
    target.write_text('{"version":1,"entries":[]}')
    store.path.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        save(store)
    assert target.read_text() == '{"version":1,"entries":[]}'


async def test_tool_source_and_mode_guards(workspace):
    context = ToolContext(
        working_directory=workspace,
        metadata={
            "runtime_thread_id": "thread_actual",
            "turn_latency_turn_id": "turn_actual",
        },
    )
    result = await MemoryWriteTool().execute({"action": "remember", "content": "Use pnpm"}, context)
    entry = json.loads(result.content)
    assert entry["source"]["runtime_thread_id"] == "thread_actual"
    assert entry["source"]["turn_latency_turn_id"] == "turn_actual"
    for mode in ("ask", "plan"):
        context.metadata["engine_mode"] = mode
        assert "Use pnpm" in (await MemoryReadTool().execute({}, context)).content
        with pytest.raises(ToolError, match="read-only"):
            await MemoryWriteTool().execute({"action": "remember", "content": "bad"}, context)


async def test_shared_registry_readonly_and_scripted_agent_roundtrip(workspace):
    engine, client = await _engine(
        workspace,
        [
            ToolCall(
                id="save",
                name="memory_write",
                arguments={"action": "remember", "content": "Use pnpm"},
            ),
            ToolCall(id="recall", name="memory_read", arguments={"query": "pnpm"}),
            "Saved and recalled.",
        ],
    )
    engine._handle_approval_flow = AsyncMock(return_value=False)
    try:
        await engine._run_conversation([Message.user("Remember: Use pnpm")], "test", "sys", None)
        assert MemoryStore(workspace).read()[0].content == "Use pnpm"
        assert any(
            "Use pnpm" in block.content
            for message in client.requests[-1].messages
            for block in message.content
            if isinstance(block, ToolResultBlock) and block.tool_use_id == "recall"
        )
        for mode in ("ask", "plan"):
            engine.mode = mode
            catalog = await engine._get_tools_with_mcp()
            names = {tool["function"]["name"] for tool in catalog}
            assert "memory_read" in names and "memory_write" not in names
            with pytest.raises(ToolError):
                await engine._execute_single_tool(
                    ToolCall(
                        id="bad",
                        name="memory_write",
                        arguments={"action": "remember", "content": "bad"},
                    ),
                    catalog,
                    "test",
                )
    finally:
        await engine.shutdown_session()
