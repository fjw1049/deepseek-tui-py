"""The transcript replays to exactly what the model received."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.events import HarnessInterventionEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.transcript import Transcript, read_transcript
from deepseek_tui.protocol.messages import Message, MessageOrigin
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeThreadManagerConfig,
    RuntimeThreadStore,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
    load_thread_messages,
)
from tests.engine.test_browser_primary_loop import ScriptedClient


def dumps(messages: list[Message]) -> list[dict]:
    return [message.model_dump(mode="json") for message in messages]


async def live_engine(tmp_path: Path, replies: list) -> tuple[Engine, ScriptedClient]:
    client = ScriptedClient(replies)
    engine = await Engine.create(
        handle=EngineHandle(), client=client, working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False)),
        start_mcp=False,
    )
    engine.transcript = Transcript(tmp_path / "t.jsonl")
    return engine, client


def test_a_round_that_only_appended_stores_only_the_new_messages(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    log = Transcript(path)
    first = [Message.user("one")]
    log.record("request", first, turn_id="turn_1", round_idx=0)
    log.record("request", [*first, Message.assistant("two")], turn_id="turn_1", round_idx=1)

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(r["keep"], len(r["messages"])) for r in records] == [(0, 1), (1, 1)]


def test_a_rewritten_history_replays_as_rewritten(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    log = Transcript(path)
    log.record("request", [Message.user("a"), Message.assistant("long tool body")], turn_id="t")
    pruned = [Message.user("a"), Message.assistant("[pruned]")]
    log.record("request", pruned, turn_id="t")

    assert dumps(read_transcript(path).messages()) == dumps(pruned)


def test_a_writer_reopened_on_the_log_continues_its_prefix(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    messages = [Message.user("a")]
    Transcript(path).record("commit", messages, turn_id="t")
    Transcript(path).record("commit", [*messages, Message.user("b")], turn_id="u")

    assert json.loads(path.read_text().splitlines()[1])["keep"] == 1


def test_a_torn_final_line_loses_only_that_record(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    messages = [Message.user("a")]
    Transcript(path).record("commit", messages, turn_id="t")
    with path.open("a") as stream:
        stream.write('{"seq": 2, "type": "req')

    Transcript(path).record("commit", [*messages, Message.user("b")], turn_id="u")

    assert [m.text_content() for m in read_transcript(path).messages()] == ["a", "b"]


def test_rollback_returns_to_the_last_kept_turn(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    log = Transcript(path)
    kept = [Message.user("a")]
    log.record("commit", kept, turn_id="keep")
    log.record("commit", [*kept, Message.user("b")], turn_id="drop")

    log.rollback({"keep"})

    state = read_transcript(path)
    assert dumps(state.messages()) == dumps(kept) and state.turn_ids == ["keep"]
    log.record("commit", [*kept, Message.user("c")], turn_id="next")
    assert [m.text_content() for m in read_transcript(path).messages()] == ["a", "c"]


def test_a_transient_reminder_is_dropped_if_the_turn_never_commits(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    goal = Message.user("<system-reminder>goal</system-reminder>")
    Transcript(path).record(
        "request", [Message.user("a"), goal, Message.assistant("b")], turn_id="t", transient=[1]
    )

    assert [m.text_content() for m in read_transcript(path).messages()] == ["a", "b"]


async def test_each_request_replays_to_what_the_client_received(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    call = ToolCall(id="call_1", name="read_file", arguments={"path": "a.txt"})
    engine, client = await live_engine(tmp_path, [call, "done"])
    engine.tool_context.metadata["turn_latency_turn_id"] = "turn_1"
    try:
        messages = [Message.user("read it")]
        await engine._run_conversation(messages, "test", "sys", None)
    finally:
        await engine.shutdown_session()

    records = [json.loads(line) for line in (tmp_path / "t.jsonl").read_text().splitlines()]
    replayed: list[dict] = []
    for record, request in zip(records, client.requests, strict=True):
        replayed[record["keep"]:] = record["messages"]
        assert replayed == dumps(request.messages)
        assert record["turn_id"] == "turn_1"


async def test_reminders_keep_their_origin_in_the_log(tmp_path: Path) -> None:
    from deepseek_tui.engine import reminders

    engine, _ = await live_engine(tmp_path, ["done"])
    engine.tool_context.metadata["turn_latency_turn_id"] = "turn_1"
    try:
        messages = [
            Message.user("go"),
            reminders.reminder_message(reminders.PLAN_NUDGE, "ground the plan"),
        ]
        await engine._run_conversation(messages, "test", "sys", None)
    finally:
        await engine.shutdown_session()

    replayed = read_transcript(tmp_path / "t.jsonl").messages()
    assert replayed[1].origin is MessageOrigin.SYSTEM_REMINDER


async def test_interventions_reach_the_event_stream(tmp_path: Path) -> None:
    from deepseek_tui.engine import reminders

    engine, _ = await live_engine(tmp_path, ["done"])
    try:
        await engine._run_conversation(
            [Message.user("go")], "test", "sys", None
        )
        reminders.reminder_message(reminders.PLAN_NUDGE, "ground the plan")
    finally:
        await engine.shutdown_session()

    events = [e for e in engine.handle.drain_events() if isinstance(e, HarnessInterventionEvent)]
    assert [(e.kind, e.reason, e.outcome) for e in events] == [
        ("reminder", "plan_nudge", "injected"),
    ]
    assert events[0].tokens_affected > 0


async def test_pending_state_reminder_is_recorded_once(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from tests.engine.test_ui_task_turns import FakeDesktopTool

    engine, _ = await live_engine(tmp_path, [
        ToolCall(id="look", name="cua_js", arguments={"code": "1"}),
        "stopping",
        "stopping",
    ])
    engine.tool_registry.register(FakeDesktopTool())
    engine._prepare_cua = AsyncMock()  # Injected desktop, no runtime lifecycle.
    engine.tool_context.metadata["cua_session"] = SimpleNamespace(
        unresolved=True, outside_change=False, reset_reason="")
    try:
        await engine._run_conversation([Message.user("go")], "test", "sys", None)
    finally:
        await engine.shutdown_session()

    events = [e for e in engine.handle.drain_events() if isinstance(e, HarnessInterventionEvent)]
    assert [e.reason for e in events if e.kind == "reminder"].count("pending_state") == 1
    assert not any(e.kind == "tool_list" for e in events)


@pytest.fixture
def store(runtime_data_dir) -> RuntimeThreadStore:
    cfg = RuntimeThreadManagerConfig.from_task_data_dir(runtime_data_dir / "tasks")
    return RuntimeThreadStore(cfg.data_dir)


def add_turn(store: RuntimeThreadStore, thread_id: str, turn_id: str, text: str) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    item_id = f"item_{turn_id}"
    store.save_item(TurnItemRecord(
        id=item_id, turn_id=turn_id, kind=TurnItemKind.USER_MESSAGE,
        status=TurnItemLifecycleStatus.COMPLETED, summary=text, detail=text, started_at=now,
    ))
    store.save_turn(TurnRecord(
        id=turn_id, thread_id=thread_id, status=RuntimeTurnStatus.COMPLETED, input_summary=text,
        created_at=now, started_at=now, item_ids=[item_id],
    ))


@pytest.fixture
def thread_id(runtime_app) -> str:
    return "thr_abcdef01"


def make_thread(store: RuntimeThreadStore, thread_id: str) -> None:
    from datetime import datetime, timezone

    from deepseek_tui.server.threads import ThreadRecord

    now = datetime.now(timezone.utc)
    store.save_thread(ThreadRecord(
        id=thread_id, title="t", workspace="/tmp", model="m", provider="p",
        created_at=now, updated_at=now,
    ))


def test_history_comes_from_the_transcript_when_it_covers_the_turns(
    store: RuntimeThreadStore, thread_id: str
) -> None:
    make_thread(store, thread_id)
    add_turn(store, thread_id, "turn_aaaaaaaa", "from items")
    sent = [Message.user("as the model saw it")]
    Transcript(store.transcript_path(thread_id)).record("commit", sent, turn_id="turn_aaaaaaaa")

    assert dumps(load_thread_messages(store, thread_id)) == dumps(sent)


def test_history_without_a_transcript_is_rebuilt_from_items(
    store: RuntimeThreadStore, thread_id: str
) -> None:
    make_thread(store, thread_id)
    add_turn(store, thread_id, "turn_aaaaaaaa", "from items")

    assert [m.text_content() for m in load_thread_messages(store, thread_id)] == ["from items"]


def test_a_log_holding_only_a_sync_does_not_double_the_rebuilt_history(
    store: RuntimeThreadStore, thread_id: str
) -> None:
    # A thread older than the transcript: first load records the rebuilt history.
    make_thread(store, thread_id)
    add_turn(store, thread_id, "turn_aaaaaaaa", "old turn")
    Transcript(store.transcript_path(thread_id)).record(
        "sync", load_thread_messages(store, thread_id)
    )

    assert [m.text_content() for m in load_thread_messages(store, thread_id)] == ["old turn"]


def test_turns_past_the_log_are_appended_from_items(
    store: RuntimeThreadStore, thread_id: str
) -> None:
    make_thread(store, thread_id)
    add_turn(store, thread_id, "turn_aaaaaaaa", "first")
    add_turn(store, thread_id, "turn_bbbbbbbb", "cancelled before any request")
    Transcript(store.transcript_path(thread_id)).record(
        "commit", [Message.user("first")], turn_id="turn_aaaaaaaa"
    )

    assert [m.text_content() for m in load_thread_messages(store, thread_id)] == [
        "first", "cancelled before any request",
    ]


def test_a_log_naming_a_deleted_turn_is_not_trusted(
    store: RuntimeThreadStore, thread_id: str
) -> None:
    make_thread(store, thread_id)
    add_turn(store, thread_id, "turn_aaaaaaaa", "from items")
    Transcript(store.transcript_path(thread_id)).record(
        "commit", [Message.user("stale")], turn_id="turn_gone"
    )

    assert [m.text_content() for m in load_thread_messages(store, thread_id)] == ["from items"]


def test_deleting_a_thread_deletes_its_transcript(
    store: RuntimeThreadStore, thread_id: str
) -> None:
    make_thread(store, thread_id)
    path = store.transcript_path(thread_id)
    Transcript(path).record("commit", [Message.user("a")], turn_id="t")

    store.delete_thread(thread_id)

    assert not path.exists()


async def test_a_live_turn_writes_interventions_to_the_thread_events(
    runtime_app: object, tmp_path: Path
) -> None:
    import asyncio
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.events import TurnCompleteEvent
    from deepseek_tui.server.threads import _ActiveThreadState
    from deepseek_tui.tools.registry import ToolContext

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    manager._recover_missing_final_answer = AsyncMock(return_value=None)
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    now = datetime.now(timezone.utc)
    manager.store.save_turn(TurnRecord(
        id="turn_cccccccc", thread_id=thread.id, status=RuntimeTurnStatus.IN_PROGRESS,
        input_summary="t", created_at=now, started_at=now,
    ))
    engine = SimpleNamespace(tool_context=ToolContext(working_directory=tmp_path))
    idle = asyncio.create_task(asyncio.sleep(3600))
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, engine, idle)
    ready = asyncio.get_running_loop().create_future()

    async def pump() -> None:
        await asyncio.wait_for(asyncio.shield(ready), timeout=5)
        await handle.emit(HarnessInterventionEvent(
            kind="compaction", reason="pressure", outcome="failed", round_idx=3,
            failure_reason="Too few unpinned messages", model_calls=0,
        ))
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, "turn_cccccccc", handle, "agent", ready)
    finally:
        await task
        idle.cancel()
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    events = [e for e in manager.store.iter_events(thread.id)
              if e.event == "harness.intervention"]
    assert len(events) == 1
    assert events[0].turn_id == "turn_cccccccc"
    assert events[0].payload == {
        "kind": "compaction", "reason": "pressure", "outcome": "failed",
        "round_idx": 3, "tokens_affected": 0,
        "failure_reason": "Too few unpinned messages", "model_calls": 0,
    }
