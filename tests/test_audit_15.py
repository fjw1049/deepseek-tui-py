"""Regression contracts for audit 15 TUI state and lifecycle boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from rich.text import Text

from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.messages import Message, MessageOrigin
from deepseek_tui.tools.subagent import MailboxMessage
from deepseek_tui.tui import commands
from deepseek_tui.tui.app import DeepSeekTUI
from deepseek_tui.tui.cards import AgentLifecycle, DelegateCard, apply_to_delegate
from deepseek_tui.tui.dialogs import _collect_files
from deepseek_tui.tui.session_restore import apply_messages_to_engine
from deepseek_tui.tui.tool_cell import parse_unified_diff
from deepseek_tui.tui.transcript import Transcript


async def test_clear_awaits_action():
    app = SimpleNamespace(action_new_session=AsyncMock(return_value=True))
    result = await commands.dispatch_async("/clear", app)
    app.action_new_session.assert_awaited_once()
    assert result.error == ""


def test_config_keeps_other_table_and_quotes(tmp_path, monkeypatch):
    import tomllib

    config = tmp_path / "config.toml"
    config.write_text('model = "old"\n[providers.demo]\nmodel = "keep"\n')
    monkeypatch.setattr("deepseek_tui.config.paths.user_config_path", lambda: config)
    commands._config_write("model", 'quote"break')
    commands._config_write("ui.locale", "en")
    data = tomllib.loads(config.read_text())
    assert data["model"] == 'quote"break'
    assert data["providers"]["demo"]["model"] == "keep"
    assert data["ui"]["locale"] == "en"


def test_restore_clears_old_summary_and_goal():
    engine = SimpleNamespace(_compaction_summary_prompt="old", goal_service=Mock())
    apply_messages_to_engine(engine, [Message.user("new")])
    assert engine._compaction_summary_prompt is None
    engine.goal_service.restore.assert_called_once_with(None, None)


@pytest.mark.parametrize("split", range(1, 60))
def test_sentinel_chunk_boundaries(monkeypatch, split):
    transcript = Transcript()
    for name in ("_hide_welcome", "_mount_cell", "_scroll_end_safe"):
        monkeypatch.setattr(transcript, name, Mock())
    source = "hi <deepseek:subagent.done>secret</deepseek:subagent.done>bye"
    transcript.append_delta(source[:split])
    transcript.append_delta(source[split:])
    assert transcript._current_assistant.content_text == "hi bye"


def test_diff_body_resembling_header():
    files = parse_unified_diff("--- a/f\n+++ b/f\n@@ -1 +1 @@\n--- old\n+++ new\n")
    assert len(files) == 1
    assert files[0].additions == files[0].deletions == 1


def test_card_markup_and_terminal_replay():
    card = DelegateCard("a", "reviewer", AgentLifecycle.COMPLETED, "[/unknown]")
    assert "[/unknown]" in Text.from_markup(card.render_text()).plain
    apply_to_delegate(card, MailboxMessage.progress("a", "late"))
    assert card.status is AgentLifecycle.COMPLETED


def test_picker_glob_and_pruning(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.txt").write_text("")
    excluded = tmp_path / "node_modules"
    excluded.mkdir()
    (excluded / "c.py").write_text("")
    assert _collect_files(tmp_path, 10, "*.py", {"node_modules"}) == [("a.py", "a.py")]


def test_export_includes_visible_history(tmp_path):
    target = tmp_path / "chat.md"
    app = SimpleNamespace(
        _engine=SimpleNamespace(
            session_messages=[
                Message.user("hello"),
                Message.assistant("answer"),
                Message.user("internal", origin=MessageOrigin.SYSTEM_REMINDER),
            ]
        )
    )
    result = commands.cmd_export(str(target), app)
    assert not result.error
    assert "hello" in target.read_text() and "answer" in target.read_text()
    assert "internal" not in target.read_text()


async def test_compaction_does_not_overwrite_concurrent_change():
    entered, resume = asyncio.Event(), asyncio.Event()
    old, new = Message.user("old"), Message.user("new")

    async def compact(messages):
        entered.set()
        await resume.wait()
        return SimpleNamespace(success=True, messages=messages)

    engine = SimpleNamespace(
        session_messages=[old], _run_compaction=compact, _cycle_session_id="session"
    )
    app = SimpleNamespace(_engine=engine, _session_busy_reason=lambda: None)
    task = asyncio.create_task(commands.dispatch_async("/compact", app))
    await entered.wait()
    engine.session_messages.append(new)
    resume.set()
    result = await task
    assert result.error
    assert engine.session_messages == [old, new]


async def test_new_session_rejects_queued_work():
    app = DeepSeekTUI(handle=EngineHandle())
    app._engine = SimpleNamespace(session_messages=[Message.user("keep")])
    app.query_one = lambda _: Mock()
    await app.handle.send_message("queued")
    assert not await app.action_new_session()
    assert app._engine.session_messages[0].content[0].text == "keep"


async def test_session_change_waits_for_startup_but_allows_its_restore():
    app = DeepSeekTUI(handle=EngineHandle())
    app._engine_starting = True
    assert "starting" in app._session_busy_reason()
    app._startup_owner = asyncio.current_task()
    assert app._session_busy_reason() is None


class QuietTUI(DeepSeekTUI):
    async def _start_engine(self):
        pass

    async def on_mount(self):
        pass


async def test_persistent_listener_delivers_after_completion():
    from deepseek_tui.engine.events import SessionActivityEvent, TurnCompleteEvent

    app = QuietTUI(handle=EngineHandle())
    async with app.run_test() as pilot:
        task = app.start_task(app._listen_events())
        await app.handle.emit(TurnCompleteEvent(None, running_subagents=1))
        await app.handle.emit(SessionActivityEvent(0, 0, "BACKGROUND_FINISHED"))
        await pilot.pause()
        assert not task.done()
        assert "BACKGROUND_FINISHED" in "\n".join(app.query_one(Transcript)._messages)
        await app.handle.emit(TurnCompleteEvent(None, success=False, error_message="failed"))
        await pilot.pause()
        from deepseek_tui.tui.status import StatusBar

        assert app.query_one(StatusBar)._status == "failed"


async def test_shutdown_stops_producer_before_close_and_is_idempotent():
    order = []

    async def producer():
        try:
            await asyncio.Event().wait()
        finally:
            order.append("stop")

    async def close():
        order.append("close")

    app = QuietTUI(handle=EngineHandle())
    engine = SimpleNamespace(shutdown=AsyncMock(side_effect=close))
    app._engine = engine
    app._engine_task = asyncio.create_task(producer())
    await asyncio.sleep(0)
    await asyncio.gather(app._shutdown_runtime(), app._shutdown_runtime())
    assert order == ["stop", "close"]
    engine.shutdown.assert_awaited_once()


async def test_cancel_approval_keeps_unrelated_overlay():
    from textual.screen import ModalScreen

    from deepseek_tui.tools.approval import ApprovalRequest, RiskLevel, ToolCategory
    from deepseek_tui.tui.dialogs import ApprovalDialog
    from deepseek_tui.tui.session_restore import TUIApprovalHandler

    app = QuietTUI(handle=EngineHandle())
    async with app.run_test() as pilot:
        pending = asyncio.create_task(
            TUIApprovalHandler(app).request_approval(
                "tool", ApprovalRequest("read_file", RiskLevel.LOW, ToolCategory.READ_ONLY, "test")
            )
        )
        await pilot.pause()
        approval = app.screen
        assert isinstance(approval, ApprovalDialog)
        overlay = ModalScreen()
        await app.push_screen(overlay)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert app.screen is overlay
        overlay.dismiss()
        await pilot.pause()
        assert approval not in app.screen_stack


async def test_cross_workspace_resume_keeps_old_messages(tmp_path):
    app = QuietTUI(handle=EngineHandle())
    original = [Message.user("keep")]
    app._engine = SimpleNamespace(
        session_messages=original, tool_context=SimpleNamespace(working_directory=tmp_path)
    )
    store = Mock()
    store.load_thread.return_value = SimpleNamespace(
        worktree_path=None, workspace=str(tmp_path / "other")
    )
    app._thread_store = store
    with pytest.raises(ValueError, match="workspace"):
        app._load_runtime_thread("other")
    assert app._engine.session_messages is original


def test_session_reset_clears_plan_approval_and_read_stamps(monkeypatch):
    app = QuietTUI(handle=EngineHandle())
    metadata = {"approved_plan": True, "plan_text": "old", "plan_steps": ["old"]}
    engine = SimpleNamespace(
        tool_context=SimpleNamespace(metadata=metadata, file_reads={"old": (1, 1)}),
        tool_snapshots={"old": "snapshot"},
        set_active_plugin=Mock(),
    )
    app._engine = engine
    monkeypatch.setattr(app, "query_one", Mock(return_value=Mock()))
    app._reset_session_view()
    assert "approved_plan" not in metadata
    assert "plan_text" not in metadata and "plan_steps" not in metadata
    assert engine.tool_context.file_reads == {}
    assert engine.tool_snapshots == {}


@pytest.mark.parametrize("fork", [False, True])
async def test_restore_plan_approval_belongs_to_original_thread(tmp_path, monkeypatch, fork):
    from datetime import datetime, timezone

    app = QuietTUI(handle=EngineHandle())
    app._engine = SimpleNamespace(
        tool_context=SimpleNamespace(working_directory=tmp_path, metadata={}),
        goal_service=Mock(),
    )
    thread = SimpleNamespace(
        id="saved",
        workspace=str(tmp_path),
        worktree_path=None,
        provider=app.config.provider,
        model=app.config.model,
        mode="agent",
        goal=None,
        goal_queue=[],
        approved_plan=True,
        created_at=datetime.now(timezone.utc),
    )
    app._thread_store = Mock()
    app._thread_store.load_thread.return_value = thread
    app._thread_store.list_turns_for_thread.return_value = []
    monkeypatch.setattr(
        "deepseek_tui.server.threads.reconstruct_messages_from_turns",
        lambda *_: [Message.user("saved")],
    )
    monkeypatch.setattr(app, "query_one", Mock(return_value=Mock()))
    monkeypatch.setattr(app, "_adopt_session", Mock())
    monkeypatch.setattr(app, "_reset_session_view", Mock())
    app._load_runtime_thread("saved", fork=fork)
    assert app._engine.tool_context.metadata["approved_plan"] is (not fork)


def test_turn_count_aggregation_reads_each_record_once(tmp_path, monkeypatch):
    import json

    from deepseek_tui.server.threads.store import RuntimeThreadStore

    store = RuntimeThreadStore(tmp_path)
    for i in range(9):
        (store._turns_dir / f"turn{i}.json").write_text(
            json.dumps(
                {
                    "id": f"turn{i}",
                    "thread_id": f"thread{i % 3}",
                    "created_at": "2026-09-28T00:00:00Z",
                    "status": "completed",
                    "input_summary": "hi",
                }
            )
        )
    reader = Mock(wraps=store._load_listing_record)
    monkeypatch.setattr(store, "_load_listing_record", reader)
    assert store.count_turns_by_thread() == {"thread0": 3, "thread1": 3, "thread2": 3}
    assert reader.call_count == 9
    reader.reset_mock()
    assert {
        tid: len(store.list_turns_for_thread(tid)) for tid in ("thread0", "thread1", "thread2")
    } == {"thread0": 3, "thread1": 3, "thread2": 3}
    assert reader.call_count == 27


async def test_worker_cancellation_waits_for_io():
    import threading

    from deepseek_tui.tui.lifecycle import run_io

    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def work():
        loop.call_soon_threadsafe(entered.set)
        release.wait(timeout=3)

    task = asyncio.create_task(run_io(work))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_failed_start_closes_created_client(monkeypatch):
    app = QuietTUI(handle=EngineHandle())
    client = SimpleNamespace(close=AsyncMock())
    app._build_client = lambda: client
    app.query_one = lambda _: Mock()
    monkeypatch.setattr(
        "deepseek_tui.engine.orchestrator.Engine.create",
        AsyncMock(side_effect=RuntimeError("create failed")),
    )
    await DeepSeekTUI._start_engine(app)
    client.close.assert_awaited_once()
    assert app._engine is None and app._engine_task is None


async def test_onboarding_persists_before_marker(monkeypatch):
    app = QuietTUI(handle=EngineHandle())
    app._build_client = lambda: None
    app.query_one = lambda _: Mock()
    callbacks = []
    app.push_screen = lambda screen, callback: callbacks.append(callback)
    order = []
    monkeypatch.setattr(
        "deepseek_tui.state.secrets.write_api_key",
        lambda provider, key: order.append(("save", provider, key)),
    )
    monkeypatch.setattr(
        "deepseek_tui.tui.onboarding.mark_onboarded", lambda: order.append(("marker",))
    )
    await DeepSeekTUI._start_engine(app)
    callbacks[0]("fake-test-key")
    assert order == [("save", app.config.provider, "fake-test-key"), ("marker",)]
    await app._shutdown_runtime()


def test_provider_build_failure_rolls_back(monkeypatch):
    from deepseek_tui.config.models import Config

    config = Config(provider="deepseek", model="original")
    app = SimpleNamespace(
        config=config,
        _engine=object(),
        _session_busy_reason=lambda: None,
        _build_client=Mock(side_effect=ValueError("bad build")),
    )
    with pytest.raises(ValueError, match="bad build"):
        commands.cmd_provider("openai", app)
    assert config.provider == "deepseek" and config.model == "original"


async def test_session_lease_blocks_other_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    a, b = QuietTUI(handle=EngineHandle()), QuietTUI(handle=EngineHandle())
    a._adopt_session("shared")
    try:
        with pytest.raises(ValueError, match="already in use"):
            b._adopt_session("shared")
    finally:
        await a._shutdown_runtime()
    b._adopt_session("shared")
    await b._shutdown_runtime()
