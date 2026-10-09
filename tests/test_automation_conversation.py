"""Terminal automation results join chat context without copying task logs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from deepseek_tui.automation.pipeline import try_write_run_result
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.protocol.messages import Message, MessageOrigin
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeThreadManager,
    RuntimeThreadManagerConfig,
    TurnItemKind,
)
from deepseek_tui.server.threads.items import (
    automation_result_items,
    reconstruct_messages_from_turns,
)
from deepseek_tui.tools.automation import (
    AUTOMATION_MANAGER_KEY,
    AutomationManager,
    AutomationRunRecord,
    AutomationRunStatus,
    CreateAutomationRequest,
    CronCreateTool,
)
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.task import TaskStatus


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=False,
            subagents=False,
            automations=False,
        )
    )
    threads = RuntimeThreadManager(
        config=config,
        workspace=tmp_path,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tmp_path / "tasks"),
        llm_client=object(),
    )
    automations = AutomationManager.open(tmp_path / "automations")
    automations.thread_manager = threads
    task = SimpleNamespace(
        id="task_result",
        status=TaskStatus.COMPLETED,
        result_summary="检查了 20 项，发现两个问题。",
        error=None,
        thread_id=None,
        turn_id=None,
        started_at=None,
        ended_at="2026-10-08T10:00:00+00:00",
        timeline=["full execution log must not be copied"],
    )
    tasks = SimpleNamespace(get_task=AsyncMock(return_value=task))
    return SimpleNamespace(
        threads=threads,
        automations=automations,
        tasks=tasks,
        task=task,
        config=config,
        workspace=tmp_path,
    )


def _job(setup, *, thread_id=None, delivery=None):
    automation = setup.automations.create_automation(
        CreateAutomationRequest(
            name="项目检查",
            prompt="检查项目并给出报告。",
            schedule="0 9 * * *",
            cwds=[str(setup.workspace)],
            conversation_thread_id=thread_id,
            delivery=delivery,
        )
    )
    run = AutomationRunRecord(
        id="run_result",
        automation_id=automation.id,
        scheduled_for="2026-10-08T09:00:00+00:00",
        created_at="2026-10-08T09:00:00+00:00",
        status=AutomationRunStatus.COMPLETED,
        task_id=setup.task.id,
        ended_at=setup.task.ended_at,
        conversation_thread_id=thread_id,
    )
    setup.automations.save_run(run)
    return automation, run


@pytest.mark.asyncio
async def test_cron_created_in_chat_remembers_origin(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    context = ToolContext(
        working_directory=setup.workspace,
        metadata={
            AUTOMATION_MANAGER_KEY: setup.automations,
            "runtime_thread_id": thread.id,
        },
    )
    result = await CronCreateTool().execute(
        {
            "name": "项目检查",
            "prompt": "检查项目。",
            "schedule": "0 9 * * *",
        },
        context,
    )
    record = setup.automations.get_automation(result.content)
    assert record.conversation_thread_id == thread.id
    setup.tasks.add_task = AsyncMock(
        return_value=SimpleNamespace(
            id="task_result",
            started_at=None,
            thread_id=None,
            turn_id=None,
        )
    )
    run = await setup.automations.run_now(record.id, setup.tasks)
    assert run.conversation_thread_id == thread.id
    assert run.thread_id is None  # Execution origin and result destination stay separate.
    reloaded = AutomationManager.open(setup.automations.automations_dir)
    assert reloaded.get_automation(record.id).conversation_thread_id == thread.id
    assert reloaded.list_runs(record.id)[0].conversation_thread_id == thread.id


@pytest.mark.asyncio
async def test_result_survives_restart_and_retry_without_duplicate_logs(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    automation, run = _job(setup, thread_id=thread.id)
    assert await try_write_run_result(
        automation,
        run,
        setup.tasks,
        thread_manager=setup.threads,
    )
    assert run.conversation_written
    # Simulate a crash after the chat write but before save_run.
    stale = setup.automations.list_runs(automation.id)[0]
    assert not stale.conversation_written
    assert await try_write_run_result(
        automation,
        stale,
        setup.tasks,
        thread_manager=setup.threads,
    )
    setup.automations.save_run(stale)
    messages = reconstruct_messages_from_turns(setup.threads.store, thread.id)
    assert len(messages) == 1
    assert messages[0].origin == MessageOrigin.SYSTEM_REMINDER
    text = messages[0].content[0].text
    assert "两个问题" in text and "Task ID: task_result" in text
    assert "Run ID: run_result" in text and "检查项目并给出报告" in text
    assert "full execution log" not in text
    items = automation_result_items(setup.threads.store, thread.id)
    assert len(items) == 1 and items[0].metadata["task_id"] == setup.task.id
    events = setup.threads.store.iter_events(thread.id)
    assert any(event.event == "item.completed" for event in events)


@pytest.mark.asyncio
async def test_warm_chat_injects_result_once_and_preserves_current_context(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    automation, run = _job(setup, thread_id=thread.id)
    bridge = Message.user("Existing compacted context", origin=MessageOrigin.SYSTEM_REMINDER)
    engine = SimpleNamespace(session_messages=[bridge])

    def sync(messages, **kwargs):
        engine.session_messages = list(messages)

    engine.sync_session = sync
    state = SimpleNamespace(engine=engine, automation_result_ids=set())
    await try_write_run_result(automation, run, setup.tasks, thread_manager=setup.threads)
    assert engine.session_messages == [bridge]
    setup.threads._sync_pending_automation_results(state, thread)
    assert len(engine.session_messages) == 2
    assert engine.session_messages[0] == bridge
    assert "task_result" in engine.session_messages[1].content[0].text
    setup.threads._sync_pending_automation_results(state, thread)
    assert len(engine.session_messages) == 2


@pytest.mark.asyncio
async def test_live_chat_defers_result_until_turn_lease_released(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    automation, run = _job(setup, thread_id=thread.id)
    async with setup.threads._hold_thread_operation(thread.id):
        written = await asyncio.create_task(
            try_write_run_result(
                automation,
                run,
                setup.tasks,
                thread_manager=setup.threads,
            )
        )
        assert not written and not run.conversation_written
        assert not automation_result_items(setup.threads.store, thread.id)
    assert await try_write_run_result(
        automation,
        run,
        setup.tasks,
        thread_manager=setup.threads,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_status,run_status",
    [
        (TaskStatus.FAILED, AutomationRunStatus.FAILED),
        (TaskStatus.TIMED_OUT, AutomationRunStatus.FAILED),
        (TaskStatus.CANCELED, AutomationRunStatus.CANCELED),
    ],
)
async def test_terminal_failures_are_available_in_chat(setup, task_status, run_status):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    automation, run = _job(setup, thread_id=thread.id)
    setup.task.status = task_status
    setup.task.error = "Task timed out" if task_status is TaskStatus.TIMED_OUT else "执行未完成"
    setup.task.result_summary = None
    run.status = run_status
    assert await try_write_run_result(
        automation,
        run,
        setup.tasks,
        thread_manager=setup.threads,
    )
    item = automation_result_items(setup.threads.store, thread.id)[0]
    assert item.metadata["status"] == run_status.value
    assert "Task ID: task_result" in item.detail


@pytest.mark.asyncio
async def test_chat_uses_original_task_instruction_without_execution_playbook(setup):
    from deepseek_tui.automation.delivery import cron_execution_prefix

    thread = await setup.threads.create_thread(CreateThreadRequest())
    automation, run = _job(setup, thread_id=thread.id)
    setup.task.prompt = (
        cron_execution_prefix(automation.id, automation.name)
        + "<automation_digest>prefetched inbox</automation_digest>\n\n原始任务要求"
    )
    automation.prompt = "修改后的下一次任务要求"
    assert await try_write_run_result(
        automation,
        run,
        setup.tasks,
        thread_manager=setup.threads,
    )
    text = automation_result_items(setup.threads.store, thread.id)[0].detail
    assert "原始任务要求" in text
    assert "修改后的下一次任务要求" not in text
    assert "Tool usage" not in text and "prefetched inbox" not in text


@pytest.mark.asyncio
async def test_running_task_and_legacy_notice_do_not_enter_chat_context(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    automation, run = _job(setup, thread_id=thread.id)
    run.status = AutomationRunStatus.RUNNING
    setup.task.status = TaskStatus.RUNNING
    assert not await try_write_run_result(
        automation,
        run,
        setup.tasks,
        thread_manager=setup.threads,
    )
    await setup.threads.append_automation_notice(
        thread.id,
        automation_name="旧通知",
        summary="普通状态提示",
    )
    assert not reconstruct_messages_from_turns(setup.threads.store, thread.id)


@pytest.mark.asyncio
async def test_delivery_failure_does_not_lose_or_duplicate_chat_result(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    automation, _ = _job(
        setup,
        thread_id=thread.id,
        delivery={
            "mode": "feishu",
            "to": "configured",
            "best_effort": False,
        },
    )
    with patch(
        "deepseek_tui.automation.pipeline._FeishuSink.deliver",
        new=AsyncMock(side_effect=RuntimeError("offline")),
    ):
        await setup.automations.reconcile_run_statuses(setup.tasks)
        run = setup.automations.list_runs(automation.id)[0]
        assert run.conversation_written and not run.delivery_done
        await setup.automations.reconcile_run_statuses(setup.tasks)
    assert len(automation_result_items(setup.threads.store, thread.id)) == 1
    run = setup.automations.list_runs(automation.id)[0]
    assert run.delivery_attempts == 2


@pytest.mark.asyncio
async def test_resumed_run_posts_new_outcome_once(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    automation, run = _job(setup, thread_id=thread.id)
    run.status = AutomationRunStatus.FAILED
    setup.task.status = TaskStatus.FAILED
    setup.task.error = "execution failed"
    setup.automations.save_run(run)
    await setup.automations.reconcile_run_statuses(setup.tasks)
    setup.task.status = TaskStatus.COMPLETED
    setup.task.error = None
    setup.task.ended_at = "2026-10-08T10:05:00+00:00"
    await setup.automations.reconcile_run_statuses(setup.tasks)
    await setup.automations.reconcile_run_statuses(setup.tasks)
    items = automation_result_items(setup.threads.store, thread.id)
    assert [item.metadata["status"] for item in items] == ["failed", "completed"]
    assert setup.automations.list_runs(automation.id)[0].conversation_written


@pytest.mark.asyncio
async def test_chat_write_retries_even_after_external_delivery_done(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    automation, run = _job(setup, thread_id=thread.id)
    run.delivery_done = True
    setup.automations.save_run(run)
    with patch.object(
        setup.threads,
        "append_automation_result",
        new=AsyncMock(side_effect=OSError("write failed")),
    ):
        await setup.automations.reconcile_run_statuses(setup.tasks)
    assert not setup.automations.list_runs(automation.id)[0].conversation_written
    await setup.automations.reconcile_run_statuses(setup.tasks)
    assert setup.automations.list_runs(automation.id)[0].conversation_written


@pytest.mark.asyncio
async def test_discussion_api_lazily_creates_and_reuses_one_chat(setup):
    runtime = AppRuntime(config=setup.config, working_directory=setup.workspace)
    app = build_fastapi_app(runtime, http_mode=True, insecure_no_auth=True)
    setup.automations.thread_manager = app.state.thread_manager
    runtime._tool_runtime = SimpleNamespace(
        automation_manager=setup.automations,
        task_manager=setup.tasks,
    )
    automation, run = _job(setup)
    assert not app.state.thread_manager.store.list_threads()
    url = f"/v1/automations/{automation.id}/runs/{run.id}/discussion"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first, second = await asyncio.gather(client.post(url), client.post(url))
        assert first.status_code == second.status_code == 200
        thread_id = first.json()["thread_id"]
        assert second.json()["thread_id"] == thread_id
        assert len(app.state.thread_manager.store.list_threads()) == 1
        assert setup.automations.get_automation(automation.id).conversation_thread_id == thread_id
        assert len(automation_result_items(app.state.thread_manager.store, thread_id)) == 1
        run.id = "run_next_day"
        run.ended_at = "2026-10-09T10:00:00+00:00"
        setup.task.ended_at = run.ended_at
        setup.automations.save_run(run)
        third = await client.post(f"/v1/automations/{automation.id}/runs/{run.id}/discussion")
        assert third.status_code == 200 and third.json()["thread_id"] == thread_id
        assert len(automation_result_items(app.state.thread_manager.store, thread_id)) == 2
        run.id = "run_running"
        run.status = AutomationRunStatus.RUNNING
        setup.automations.save_run(run)
        rejected = await client.post(f"/v1/automations/{automation.id}/runs/{run.id}/discussion")
        assert rejected.status_code == 400


def test_old_records_have_no_implicit_conversation(setup):
    automation, run = _job(setup)
    automation_raw = automation.to_dict()
    automation_raw.pop("conversation_thread_id")
    run_raw = run.to_dict()
    run_raw.pop("conversation_thread_id")
    run_raw.pop("conversation_written")
    assert automation.from_dict(automation_raw).conversation_thread_id is None
    restored = run.from_dict(run_raw)
    assert restored.conversation_thread_id is None and not restored.conversation_written
    assert TurnItemKind.STATUS.value == "status"


@pytest.mark.asyncio
async def test_partial_chat_write_repairs_index_and_emits_result_on_retry(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    await setup.threads.append_automation_notice(
        thread.id,
        automation_name="已有通知",
        summary="已有聊天记录",
    )
    automation, run = _job(setup, thread_id=thread.id)
    with patch.object(setup.threads.store, "save_turn", side_effect=OSError("disk write")):
        assert not await try_write_run_result(
            automation,
            run,
            setup.tasks,
            thread_manager=setup.threads,
        )
    assert await try_write_run_result(
        automation,
        run,
        setup.tasks,
        thread_manager=setup.threads,
    )
    items = automation_result_items(setup.threads.store, thread.id)
    assert len(items) == 1
    turn = setup.threads.store.load_turn(items[0].turn_id)
    assert items[0].id in turn.item_ids
    events = list(setup.threads.store.iter_events(thread.id))
    assert any(event.event == "item.completed" and event.item_id == items[0].id for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["warm", "restart", "compact_then_restart"])
async def test_follow_up_model_request_contains_result_after_warmup_or_restart(setup, mode):
    from deepseek_tui.client.base import LLMClient, RetryConfig
    from deepseek_tui.protocol.messages import TextBlock
    from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta
    from deepseek_tui.server.threads import CompactThreadRequest, StartTurnRequest

    class Client(LLMClient):
        def __init__(self):
            super().__init__(RetryConfig(base_delay=0, max_delay=0))
            self.requests = []

        async def stream_chat_completion(self, request):
            self.requests.append(request.model_copy(deep=True))
            yield StreamTextDelta(text="这是本轮回答。")
            yield StreamDone()

    async def settle(manager, turn):
        for _ in range(200):
            if manager.store.load_turn(turn.id).status.value == "completed":
                state = manager._active.get(turn.thread_id)
                if state is not None and state.active_turn is None:
                    return
            await asyncio.sleep(0.01)
        raise AssertionError("chat turn did not complete")

    client = Client()
    manager = setup.threads
    manager._llm_client = client
    thread = await manager.create_thread(CreateThreadRequest(title="项目检查讨论"))
    try:
        first = await manager.start_turn(thread.id, StartTurnRequest(prompt="你好"))
        await settle(manager, first)
        automation, run = _job(setup, thread_id=thread.id)
        assert await try_write_run_result(
            automation,
            run,
            setup.tasks,
            thread_manager=manager,
        )
        if mode == "compact_then_restart":

            def compact(messages):
                return SimpleNamespace(
                    messages=list(messages),
                    success=True,
                    retries_used=0,
                    summary_prompt=None,
                )

            with patch.object(
                manager._active[thread.id].engine,
                "_run_compaction",
                new=AsyncMock(side_effect=compact),
            ):
                await manager.compact_thread(thread.id, CompactThreadRequest())
        if mode != "warm":
            await manager.aclose()
            manager = RuntimeThreadManager(
                config=setup.config,
                workspace=setup.workspace,
                manager_cfg=setup.threads.manager_cfg,
                llm_client=client,
            )
        second = await manager.start_turn(
            thread.id, StartTurnRequest(prompt="第二个问题是什么意思？")
        )
        await settle(manager, second)
        request = client.requests[-1]
        text = "\n".join(
            block.text
            for message in request.messages
            for block in message.content
            if isinstance(block, TextBlock)
        )
        assert "第二个问题是什么意思" in text
        assert text.count("Task ID: task_result") == 1
        assert "检查了 20 项" in text
    finally:
        await manager.aclose()
