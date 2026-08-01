"""P1 durable-resume trigger APIs: task resume + thread agent resume."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeThreadManager,
    RuntimeThreadManagerConfig,
)
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.subagent import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentStatusKind,
    SubAgentType,
)
from deepseek_tui.tools.task.models import NewTaskRequest, TaskStatus


async def _hang_until_cancel(agent, cancel):
    await cancel.wait()
    raise asyncio.CancelledError


@pytest.fixture
def resume_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    threads = tmp_path / "threads"
    tasks = tmp_path / "tasks"
    home = tmp_path / "home"
    threads.mkdir()
    tasks.mkdir()
    home.mkdir()
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    monkeypatch.delenv("DEEPSEEK_RUNTIME_TOKEN", raising=False)
    monkeypatch.setattr(
        "deepseek_tui.config.paths.user_threads_dir",
        lambda: threads,
    )
    monkeypatch.setattr(
        "deepseek_tui.config.paths.user_tasks_dir",
        lambda: tasks,
    )
    return tmp_path


@pytest.fixture
async def tasks_runtime(
    resume_data_dir: Path,
) -> AsyncIterator[tuple[AppRuntime, AsyncClient]]:
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=True,
            subagents=False,
            automations=False,
        ),
    )
    runtime = await AppRuntime.create(config=config, working_directory=resume_data_dir)
    app = build_fastapi_app(runtime, http_mode=True, insecure_no_auth=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield runtime, ac
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_http_resume_task_success(
    tasks_runtime: tuple[AppRuntime, AsyncClient],
) -> None:
    runtime, client = tasks_runtime
    assert runtime.tool_runtime is not None
    assert runtime.tool_runtime.task_manager is not None
    tm = runtime.tool_runtime.task_manager
    task = await tm.add_task(NewTaskRequest(prompt="resume via http"))
    async with tm._lock:
        record = tm._tasks[task.id]
        record.status = TaskStatus.FAILED
        record.error = "boom"
        tm._queue.clear()
        tm._persist_all_locked()

    r = await client.post(f"/v1/tasks/{task.id}/resume")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == task.id
    assert body["status"] == "queued"


@pytest.mark.asyncio
async def test_http_resume_task_conflict_completed(
    tasks_runtime: tuple[AppRuntime, AsyncClient],
) -> None:
    runtime, client = tasks_runtime
    assert runtime.tool_runtime is not None
    assert runtime.tool_runtime.task_manager is not None
    tm = runtime.tool_runtime.task_manager
    task = await tm.add_task(NewTaskRequest(prompt="already done"))
    async with tm._lock:
        record = tm._tasks[task.id]
        record.status = TaskStatus.COMPLETED
        tm._queue.clear()
        tm._persist_all_locked()

    r = await client.post(f"/v1/tasks/{task.id}/resume")
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_http_resume_task_not_found(
    tasks_runtime: tuple[AppRuntime, AsyncClient],
) -> None:
    _runtime, client = tasks_runtime
    r = await client.post("/v1/tasks/task_missing/resume")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_http_resume_workflow_success(
    tasks_runtime: tuple[AppRuntime, AsyncClient],
) -> None:
    from deepseek_tui.workflow.models import WorkflowSnapshot, parse_workflow_spec
    from deepseek_tui.workflow.store import checkpoint_run, create_run

    runtime, client = tasks_runtime
    workspace = Path(runtime.working_directory)
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "http-resume", "description": "d"},
            "policy": {"on_error": "continue"},
            "graph": {
                "nodes": [{"id": "a", "type": "agent", "label": "a", "prompt": "A"}],
                "edges": [],
            },
        }
    )
    record = create_run(spec, task="t", workspace=workspace)
    checkpoint_run(
        record,
        completed_step_ids=[],
        outputs={},
        snapshot=WorkflowSnapshot(name="http-resume", description="d"),
        logs=[],
        status="interrupted",
        workspace=workspace,
        agent_bindings={
            "a": {"agent_id": "agent_x", "status": "cancelled", "mode": "spawn"}
        },
    )

    r = await client.post(
        f"/v1/workflow/{record.run_id}/resume",
        json={"detach": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["run_id"] == record.run_id
    assert isinstance(body.get("task_id"), str) and body["task_id"]


@pytest.mark.asyncio
async def test_http_resume_workflow_not_found(
    tasks_runtime: tuple[AppRuntime, AsyncClient],
) -> None:
    _runtime, client = tasks_runtime
    r = await client.post(
        "/v1/workflow/wf_missing/resume",
        json={"detach": True},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_http_resume_workflow_completed_conflict(
    tasks_runtime: tuple[AppRuntime, AsyncClient],
) -> None:
    from deepseek_tui.workflow.models import WorkflowSnapshot, parse_workflow_spec
    from deepseek_tui.workflow.store import checkpoint_run, create_run

    runtime, client = tasks_runtime
    workspace = Path(runtime.working_directory)
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "done", "description": "d"},
            "policy": {"on_error": "continue"},
            "graph": {
                "nodes": [{"id": "a", "type": "agent", "label": "a", "prompt": "A"}],
                "edges": [],
            },
        }
    )
    record = create_run(spec, task="t", workspace=workspace)
    checkpoint_run(
        record,
        completed_step_ids=["a"],
        outputs={},
        snapshot=WorkflowSnapshot(name="done", description="d"),
        logs=[],
        status="completed",
        workspace=workspace,
    )
    r = await client.post(
        f"/v1/workflow/{record.run_id}/resume",
        json={"detach": True},
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_resume_subagent_via_thread_manager(
    resume_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib

    sub_mgr = SubAgentManager(
        workspace=resume_data_dir,
        executor=_hang_until_cancel,
    )
    snap = await sub_mgr.spawn(
        SpawnRequest(
            prompt="work",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="work"),
        )
    )
    await asyncio.sleep(0.05)
    await sub_mgr.cancel(snap.agent_id)
    cancelled = await sub_mgr.get_result(snap.agent_id)
    assert cancelled.status.kind is SubAgentStatusKind.CANCELLED

    async def fake_create(**kwargs: object) -> SimpleNamespace:
        wd = kwargs.get("working_directory", resume_data_dir)
        ctx = ToolContext(working_directory=Path(wd))  # type: ignore[arg-type]
        ctx.subagent_manager = sub_mgr
        return SimpleNamespace(
            tool_context=ctx,
            run=AsyncMock(),
            session_messages=[],
            sync_session=lambda *a, **k: None,
            client=None,
            turn_loop=SimpleNamespace(client=None),
            mode="agent",
        )

    monkeypatch.setattr("deepseek_tui.engine.orchestrator.Engine.create", fake_create)

    tasks_dir = resume_data_dir / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    mgr = RuntimeThreadManager(
        config=Config(
            features=FeatureConfig(
                mcp=False, tasks=False, subagents=True, automations=False
            )
        ),
        workspace=resume_data_dir,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tasks_dir),
        llm_client=object(),
    )
    thread = await mgr.create_thread(CreateThreadRequest())
    payload = await mgr.resume_subagent(thread.id, snap.agent_id)
    assert payload["agent_id"] == snap.agent_id
    assert payload["status"]["kind"] == "running"

    with pytest.raises(RuntimeError, match="already running"):
        await mgr.resume_subagent(thread.id, snap.agent_id)

    await sub_mgr.cancel(snap.agent_id)
    async with mgr._active_lock:
        state = mgr._active.get(thread.id)
        if state is not None:
            state.engine_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state.engine_task
            mgr._active.pop(thread.id, None)


@pytest.mark.asyncio
async def test_resume_subagent_unknown_agent(
    resume_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib

    sub_mgr = SubAgentManager(
        workspace=resume_data_dir,
        executor=_hang_until_cancel,
    )

    async def fake_create(**kwargs: object) -> SimpleNamespace:
        wd = kwargs.get("working_directory", resume_data_dir)
        ctx = ToolContext(working_directory=Path(wd))  # type: ignore[arg-type]
        ctx.subagent_manager = sub_mgr
        return SimpleNamespace(
            tool_context=ctx,
            run=AsyncMock(),
            session_messages=[],
            sync_session=lambda *a, **k: None,
            client=None,
            turn_loop=SimpleNamespace(client=None),
            mode="agent",
        )

    monkeypatch.setattr("deepseek_tui.engine.orchestrator.Engine.create", fake_create)
    tasks_dir = resume_data_dir / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    mgr = RuntimeThreadManager(
        config=Config(
            features=FeatureConfig(
                mcp=False, tasks=False, subagents=True, automations=False
            )
        ),
        workspace=resume_data_dir,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tasks_dir),
        llm_client=object(),
    )
    thread = await mgr.create_thread(CreateThreadRequest())
    with pytest.raises(KeyError, match="Unknown agent"):
        await mgr.resume_subagent(thread.id, "agent_missing")

    async with mgr._active_lock:
        state = mgr._active.get(thread.id)
        if state is not None:
            state.engine_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state.engine_task
            mgr._active.pop(thread.id, None)
