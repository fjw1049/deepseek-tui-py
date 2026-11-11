"""Task kind decides the run policy; the prompt text no longer does."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.tools.task import (
    RUN_POLICIES,
    ExecutionTask,
    NewTaskRequest,
    TaskExecutionResult,
    TaskKind,
    TaskManager,
    TaskManagerConfig,
    TaskStatus,
)


def _manager(tmp_path: Path, executor) -> TaskManager:  # noqa: ANN001
    return TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path, worker_count=2),
        executor=executor,
    )


@pytest.mark.asyncio
async def test_kind_survives_a_restart_and_legacy_records_are_classified(tmp_path):
    manager = _manager(tmp_path, AsyncMock())
    await manager.start()
    task = await manager.add_task(NewTaskRequest(prompt="tidy", kind=TaskKind.CRON))
    await manager.shutdown()

    path = tmp_path / "data" / "tasks" / f"{task.id}.json"
    assert json.loads(path.read_text())["kind"] == "cron"

    legacy = json.loads(path.read_text())
    legacy.pop("kind")
    legacy["id"] = "task_legacy1"
    legacy["prompt"] = "[cron:abc daily] tidy"
    (path.parent / "task_legacy1.json").write_text(json.dumps(legacy))

    reopened = _manager(tmp_path, AsyncMock())
    await reopened.start()
    try:
        assert (await reopened.get_task(task.id)).kind is TaskKind.CRON
        assert (await reopened.get_task("task_legacy1")).kind is TaskKind.CRON
    finally:
        await reopened.shutdown()


@pytest.mark.asyncio
async def test_cron_tasks_run_one_at_a_time_without_a_prompt_prefix(tmp_path):
    release = asyncio.Event()
    started: list[str] = []

    async def executor(task, cancel):  # noqa: ANN001
        started.append(task.id)
        await release.wait()
        return TaskExecutionResult(summary="done")

    manager = _manager(tmp_path, executor)
    await manager.start()
    try:
        a = await manager.add_task(NewTaskRequest(prompt="job a", kind=TaskKind.CRON))
        b = await manager.add_task(NewTaskRequest(prompt="job b", kind=TaskKind.CRON))
        plain = await manager.add_task(NewTaskRequest(prompt="job c"))
        for _ in range(100):
            if len(started) >= 2:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.1)
        statuses = {t: (await manager.get_task(t)).status for t in (a.id, b.id, plain.id)}
        assert sorted(s.value for s in statuses.values()) == ["queued", "running", "running"]
        assert statuses[plain.id] is TaskStatus.RUNNING
        release.set()
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [TaskKind.CRON, TaskKind.TASK])
async def test_executor_takes_limits_and_profile_from_the_kind(tmp_path, monkeypatch, kind):
    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.dispatch import _run_task_engine_turn

    from deepseek_tui.client.base import LLMClient, RetryConfig

    class Idle(LLMClient):
        def __init__(self) -> None:
            super().__init__(RetryConfig(base_delay=0, max_delay=0))

        async def stream_chat_completion(self, request):  # noqa: ANN001
            raise AssertionError("not reached")
            yield  # pragma: no cover

    monkeypatch.setattr(
        "deepseek_tui.client.factory.build_llm_client", lambda config: Idle()
    )
    seen: dict = {}

    class Reached(Exception):
        pass

    async def run_single_turn(self, content, **kwargs):  # noqa: ANN001
        seen["profile"] = self.pinned_tool_profile
        seen["rounds"] = self.max_tool_round_trips
        raise Reached

    monkeypatch.setattr(
        "deepseek_tui.engine.orchestrator.Engine.run_single_turn", run_single_turn
    )
    task = ExecutionTask(
        id="task_kindtest", prompt="tidy the folder", model="deepseek-chat",
        workspace=str(tmp_path), mode_label="agent", allow_shell=False,
        trust_mode=False, auto_approve=True, config=Config(), kind=kind,
    )
    with pytest.raises(Reached):
        await _run_task_engine_turn(task, asyncio.Event())

    assert seen["profile"] == RUN_POLICIES[kind].tool_profile
    assert seen["rounds"] == RUN_POLICIES[kind].max_rounds


@pytest.mark.asyncio
async def test_pinned_profile_applies_to_a_turn_whose_prompt_has_no_marker(
    tmp_path: Path, isolated_config
) -> None:
    """A resumed cron run is sent CONTINUE_NUDGE, not the [cron:] prompt."""
    from deepseek_tui.client.base import LLMClient, RetryConfig
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta
    from deepseek_tui.tools.durable_transcript import CONTINUE_NUDGE

    class Client(LLMClient):
        def __init__(self) -> None:
            super().__init__(RetryConfig(base_delay=0, max_delay=0))
            self.tools: list[str] = []

        async def stream_chat_completion(self, request):  # noqa: ANN001
            self.tools = [
                (t.get("function") or t).get("name") for t in (request.tools or [])
            ]
            yield StreamTextDelta(text="done")
            yield StreamDone()

    client = Client()
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle, client=client, config=isolated_config,
        working_directory=tmp_path, task_data_dir=tmp_path / "tasks",
    )
    try:
        engine.pinned_tool_profile = RUN_POLICIES[TaskKind.CRON].tool_profile
        await engine.run_single_turn(CONTINUE_NUDGE)
    finally:
        await engine.shutdown_session()
        handle.drain_events()

    assert client.tools, "the turn reached the model"
    assert "agent" in client.tools
    assert "task_create" not in client.tools
    assert "read_file" in client.tools



@pytest.mark.asyncio
async def test_catalog_parses_an_unchanged_record_only_once(tmp_path, monkeypatch):
    import deepseek_tui.tools.task.manager as manager_mod

    manager = _manager(tmp_path, AsyncMock())
    for i in range(3):
        await manager.add_task(NewTaskRequest(prompt=f"job {i}"))
    manager._tasks.clear()  # noqa: SLF001 — as after eviction: history is on disk
    calls = 0
    real = manager_mod._task_record_from_dict

    def counting(data):  # noqa: ANN001
        nonlocal calls
        calls += 1
        return real(data)

    monkeypatch.setattr(manager_mod, "_task_record_from_dict", counting)
    assert len(await manager.list_tasks()) == 3
    first = calls
    assert len(await manager.list_tasks()) == 3
    assert first == 3 and calls == first


@pytest.mark.asyncio
async def test_task_list_defaults_to_this_workspace_and_a_bounded_count(tmp_path):
    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.task import TaskListTool

    here, elsewhere = tmp_path / "here", tmp_path / "elsewhere"
    here.mkdir()
    elsewhere.mkdir()
    manager = _manager(tmp_path, AsyncMock())
    for i in range(25):
        await manager.add_task(NewTaskRequest(prompt=f"here {i}", workspace=str(here)))
    await manager.add_task(NewTaskRequest(prompt="other project", workspace=str(elsewhere)))
    ctx = ToolContext(working_directory=here, task_manager=manager)

    listed = await TaskListTool().execute({"kind": "task"}, ctx)
    assert len(listed.metadata["tasks"]) == 20
    assert "5 older not shown" in listed.content
    assert "other project" not in listed.content

    everywhere = await TaskListTool().execute(
        {"kind": "task", "all_workspaces": True, "limit": 100}, ctx
    )
    assert len(everywhere.metadata["tasks"]) == 26


@pytest.mark.asyncio
async def test_reconcile_does_not_reread_finished_tasks_from_disk(tmp_path, monkeypatch):
    from deepseek_tui.tools.automation import (
        AutomationManager,
        AutomationRunRecord,
        AutomationRunStatus,
        CreateAutomationRequest,
    )

    automations = AutomationManager.open(tmp_path / "automations")
    job = automations.create_automation(CreateAutomationRequest(
        name="n", prompt="p", schedule="0 9 * * *", cwds=[str(tmp_path)],
    ))
    automations.save_run(AutomationRunRecord(
        id="r1", automation_id=job.id, scheduled_for="2026-01-01T00:00:00+00:00",
        status=AutomationRunStatus.FAILED, created_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:01:00+00:00", task_id="task_gone",
        delivery_done=True,
    ))
    manager = _manager(tmp_path, AsyncMock())
    get_task = AsyncMock(side_effect=AssertionError("disk read"))
    monkeypatch.setattr(manager, "get_task", get_task)

    await automations.reconcile_run_statuses(manager)

    get_task.assert_not_awaited()
