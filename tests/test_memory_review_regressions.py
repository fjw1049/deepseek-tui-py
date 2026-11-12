"""Permanent reproductions of the memory review, plus turn/cache boundary checks."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from deepseek_tui.config.models import MemoryConfig
from deepseek_tui.engine.context import estimated_input_tokens
from deepseek_tui.engine.handle import SendMessageOp
from deepseek_tui.engine.memory import MemorySession
from deepseek_tui.engine.transcript import Transcript, read_transcript
from deepseek_tui.protocol.messages import Message, MessageOrigin
from deepseek_tui.state.memory import MemoryStore
from deepseek_tui.state.memory_capture import capture_candidates
from tests.test_audit_tool_pipeline import _engine
from tests.test_project_memory import save


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    root = tmp_path / "project"
    root.mkdir()
    return root


async def test_failed_turn_does_not_persist_recall(workspace):
    save(MemoryStore(workspace), "接口测试需要 Redis")
    engine, client = await _engine(workspace, [])  # no reply -> request fails mid-turn
    engine.transcript = Transcript(workspace / "engine.jsonl")
    try:
        try:
            await engine._handle_send_message(SendMessageOp(content="怎么运行接口测试？"))
        except Exception:
            pass
        leaked = [m for m in engine.session_messages if m.origin is MessageOrigin.MEMORY_RECALL]
        assert client.requests
        assert any(m.origin is MessageOrigin.MEMORY_RECALL for m in client.requests[0].messages)
        assert not leaked
        assert all(
            m.origin is not MessageOrigin.MEMORY_RECALL
            for m in read_transcript(engine.transcript.path).messages()
        )
    finally:
        await engine.shutdown_session()


def test_forget_then_explicit_remember_is_allowed(workspace):
    store = MemoryStore(workspace)
    e = save(store, "use pnpm for frontend")
    store.write(action="forget", source={}, entry_id=e.id, revision=e.revision)
    save(store, "use pnpm for frontend")  # user changed mind and asks again


def test_update_then_revert_is_allowed(workspace):
    store = MemoryStore(workspace)
    e = save(store, "use pnpm")
    e = store.write(
        action="update", source={}, entry_id=e.id, revision=e.revision, content="use npm"
    )
    store.write(action="update", source={}, entry_id=e.id, revision=e.revision, content="use pnpm")


def test_explicit_remember_promotes_candidate(workspace):
    store = MemoryStore(workspace)
    store.write(action="propose", source={"type": "x"}, content="always run ruff before commit")
    e = save(store, "always run ruff before commit")
    assert e.status == "active", e.status


def test_single_common_term_does_not_trigger_search_recall(workspace):
    store = MemoryStore(workspace)
    save(store, "发布前必须运行 make release-check")
    hits = store.recall("帮我看看这个运行时报错")  # unrelated query sharing only bigram 运行
    assert hits == [], [h.content for h in hits]


def test_substring_does_not_trigger_search_recall(workspace):
    store = MemoryStore(workspace)
    save(store, "The happy path test lives in tests/e2e")
    hits = store.recall("py version?")  # 'py' substring of 'happy'
    assert hits == [], [h.content for h in hits]


def test_accepted_candidate_survives_origin_log_growth(workspace):
    from deepseek_tui.state import memory_capture

    log = Transcript(workspace / "t.jsonl")
    log.record(
        "commit",
        [Message.user("以后本项目的接口测试都使用本地 Redis。", origin=MessageOrigin.REAL_USER)],
        turn_id="t1",
    )
    capture_candidates(workspace, log.path)
    store = MemoryStore(workspace)
    c = store.read(status="candidate")[0]
    store.write(action="accept", source={}, entry_id=c.id, revision=c.revision)
    assert store.recall("接口测试 Redis")
    for i in range(memory_capture.MAX_RECORDS):
        log.record(
            "commit", [Message.user(f"msg {i}", origin=MessageOrigin.REAL_USER)], turn_id=f"x{i}"
        )
    assert store.recall("接口测试 Redis"), store.stale_reason(store.read()[0])


def test_topic_conflict_is_rejected_without_silencing_original(workspace):
    store = MemoryStore(workspace)
    save(store, "frontend package manager: pnpm", topic="pkg")
    with pytest.raises(ValueError, match=f"id={store.read()[0].id}"):
        save(store, "frontend package manager: bun", topic="pkg")
    assert store.recall("frontend package manager"), "both silently withheld"


def test_applicability_does_not_disable_recall(workspace):
    store = MemoryStore(workspace)
    save(store, "run tests with --offline", applicability="when running the test suite")
    assert store.recall("run tests --offline")


async def test_cancelled_turn_does_not_persist_recall(workspace, monkeypatch):
    save(MemoryStore(workspace), "接口测试需要 Redis")
    engine, client = await _engine(workspace, [])
    engine.transcript = Transcript(workspace / "cancelled.jsonl")
    requested = asyncio.Event()

    async def stream(request):
        assert any(m.origin is MessageOrigin.MEMORY_RECALL for m in request.messages)
        requested.set()
        await asyncio.Event().wait()
        yield  # Keep the streaming interface; cancellation happens before a response.

    monkeypatch.setattr(client, "stream_chat_completion", stream)
    task = asyncio.create_task(engine._handle_send_message(SendMessageOp(content="接口测试")))
    try:
        await asyncio.wait_for(requested.wait(), timeout=5)
        task.cancel()
        await task  # The engine consumes cancellation and finalizes the interrupted turn.
        assert any(m.origin is MessageOrigin.REAL_USER for m in engine.session_messages)
        assert all(m.origin is not MessageOrigin.MEMORY_RECALL for m in engine.session_messages)
        assert all(
            m.origin is not MessageOrigin.MEMORY_RECALL
            for m in read_transcript(engine.transcript.path).messages()
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.shutdown_session()


@pytest.mark.parametrize("budget", [512, 4000])
async def test_followup_recall_with_small_and_over_budget_stores(workspace, budget):
    store = MemoryStore(workspace)
    target = save(store, "frontend tests require pnpm", applicability="on supported versions")
    others = [save(store, f"unrelated astronomy constraint {n}") for n in range(3)]
    messages = [
        Message.user("Run frontend tests", origin=MessageOrigin.REAL_USER),
        Message.assistant("Ready."),
        Message.user("继续", origin=MessageOrigin.REAL_USER),
    ]
    session = MemorySession(workspace, MemoryConfig(max_recall_chars=budget))
    await session.recall(messages, "继续")
    recalled = next(m for m in messages if m.origin is MessageOrigin.MEMORY_RECALL)
    assert target.id in recalled.text_content()
    assert "on supported versions" in recalled.text_content()
    assert "source" not in recalled.text_content()
    assert len(recalled.text_content()) <= budget
    assert all((e.id in recalled.text_content()) == (budget == 4000) for e in others)


async def test_recall_cache_reuses_conditions_and_notices_memory_changes(workspace):
    store = MemoryStore(workspace)
    save(store, "test command v1")
    session = MemorySession(workspace, MemoryConfig())
    session.store = store
    messages = [Message.user("继续", origin=MessageOrigin.REAL_USER)]
    with patch.object(store, "eligible", wraps=store.eligible) as check:
        await session.recall(messages, "继续")
        await session.recall(messages, "继续")
        assert check.call_count == 1
        assert sum(m.origin is MessageOrigin.MEMORY_RECALL for m in messages) == 1
        added = save(store, "new command v2")
        await session.recall(messages, "继续")
        assert check.call_count == 2
        assert any(added.id in m.text_content() for m in messages)
        session.invalidate()
        await session.recall(messages, "继续")
        assert check.call_count == 3


async def test_mutating_tool_invalidates_cached_file_conditions(workspace):
    from deepseek_tui.protocol.responses import ToolCall

    (workspace / "version.txt").write_text("old")
    entry = save(MemoryStore(workspace), "test requires legacy mode", files=["version.txt"])
    engine, client = await _engine(
        workspace,
        [
            ToolCall(
                id="edit", name="write_file", arguments={"path": "version.txt", "content": "new"}
            ),
            "Done.",
        ],
    )
    engine._handle_approval_flow = AsyncMock(return_value=False)
    try:
        await engine._run_conversation(
            [Message.user("Update version", origin=MessageOrigin.REAL_USER)], "test", "sys", None
        )
        assert (workspace / "version.txt").read_text() == "new"
        assert any(entry.id in m.text_content() for m in client.requests[0].messages)
        assert all(
            entry.id not in m.text_content()
            for m in client.requests[1].messages
            if m.origin is MessageOrigin.MEMORY_RECALL
        )
    finally:
        await engine.shutdown_session()


def test_branch_is_resolved_once_for_multiple_entries(workspace):
    import subprocess

    store = MemoryStore(workspace)
    for n in range(3):
        save(store, f"branch rule {n}", branch="main")
    with patch("deepseek_tui.state.memory.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="main\n")
        assert len(store.eligible()) == 3
        assert run.call_count == 1


async def test_recall_respects_estimated_token_budget(workspace):
    save(MemoryStore(workspace), "接口测试需要 Redis")
    session = MemorySession(workspace, MemoryConfig())
    messages = [Message.user("继续", origin=MessageOrigin.REAL_USER)]
    await session.recall(messages, "继续")
    needed = estimated_input_tokens([messages[0]])
    await session.recall(messages, "继续", token_budget=needed - 1)
    assert len(messages) == 1
    await session.recall(messages, "继续", token_budget=needed)
    assert messages[0].origin is MessageOrigin.MEMORY_RECALL


def test_tombstones_do_not_exhaust_live_capacity(workspace):
    from deepseek_tui.state.memory import MemoryState
    from deepseek_tui.utils import write_json_atomic

    store = MemoryStore(workspace)
    entry = save(store, "original")
    deleted = [
        entry.model_copy(update={"id": f"old-{n}", "status": "deleted"}) for n in range(1000)
    ]
    state = MemoryState(entries=deleted, blocked_fingerprints=[f"old-{n}" for n in range(1000)])
    write_json_atomic(store.path, state.model_dump(mode="json"))
    new = save(store, "new command")
    store.write(action="update", source={}, entry_id=new.id, revision=1, content="newer command")
    store.write(action="forget", source={}, entry_id=new.id, revision=2)
    assert save(store, "still writable").status == "active"
    state = store._load()
    assert len(state.blocked_fingerprints) == 1000
    assert sum(e.status == "deleted" for e in state.entries) == 1000


async def test_full_mode_is_compact_and_leads_for_prefix_cache(workspace):
    store = MemoryStore(workspace)
    ids = [save(store, f"规则{n}：接口测试前需要先启动本地 Redis").id for n in range(40)]
    session = MemorySession(workspace, MemoryConfig())
    history = [Message.user("帮我看看天气", origin=MessageOrigin.REAL_USER)]
    await session.recall(history, "帮我看看天气")
    first = history[0]
    assert first.origin is MessageOrigin.MEMORY_RECALL
    assert all(entry_id in first.text_content() for entry_id in ids)
    history += [Message.assistant("Ready."), Message.user("继续", origin=MessageOrigin.REAL_USER)]
    await session.recall(history, "继续")
    assert history[0].text_content() == first.text_content()


async def test_over_budget_single_keyword_query_recalls(workspace):
    store = MemoryStore(workspace)
    for n in range(80):
        save(store, f"filler memory {n} about alpha{n} beta{n}")
    target = save(store, "frontend uses pnpm")
    session = MemorySession(workspace, MemoryConfig())
    messages = [Message.user("pnpm?", origin=MessageOrigin.REAL_USER)]
    await session.recall(messages, "pnpm?")
    assert messages[-1].origin is MessageOrigin.MEMORY_RECALL
    assert target.id in messages[-1].text_content()


def test_topic_conflict_includes_branch_stale_entries(workspace):
    store = MemoryStore(workspace)
    save(store, "package manager is bun", topic="pkg", branch="no-such-branch")
    with pytest.raises(ValueError, match="Topic already exists"):
        save(store, "package manager is pnpm", topic="pkg")
    save(store, "old pkg rule", topic="legacy", expires_at="2000-01-01T00:00:00Z")
    assert save(store, "new pkg rule", topic="legacy").status == "active"
