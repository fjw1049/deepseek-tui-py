from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.task import NewTaskRequest, TaskManager, TaskManagerConfig, TaskStatus
from deepseek_tui.tools.task.resume import scope_key, task_scope
from deepseek_tui.tools.task.tools import TaskCreateTool


async def stopped(tmp_path, **kwargs):
    manager = TaskManager(TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path))
    record = await manager.add_task(NewTaskRequest(prompt="old task", auto_approve=False, **kwargs))
    await manager.cancel_task(record.id)
    return manager, record


@pytest.mark.parametrize(
    "field,value",
    [
        ("auto_approve", True),
        ("trust_mode", True),
        ("allow_shell", True),
        ("mode", "yolo"),
        ("workspace", "/outside"),
    ],
)
async def test_model_cannot_resume_higher_authority_even_with_injected_confirmation(
    tmp_path, field, value
):
    manager, record = await stopped(tmp_path)
    setattr(record, field, value)
    ctx = ToolContext(working_directory=tmp_path, task_manager=manager)
    with pytest.raises(ToolError, match="Tasks panel"):
        await TaskCreateTool().execute({"resume": record.id, "confirmation_key": "yes"}, ctx)
    assert record.status is TaskStatus.CANCELED


async def test_safe_resume_preserves_identity_workspace_and_authority(tmp_path):
    manager, record = await stopped(tmp_path, workspace=str(tmp_path / "nested"))
    original = task_scope(record)
    result = await TaskCreateTool().execute(
        {"resume": record.id}, ToolContext(working_directory=tmp_path, task_manager=manager)
    )
    assert result.success
    assert record.status is TaskStatus.QUEUED
    assert task_scope(record) == original
    assert await manager.get_task(record.id) is record


async def test_resume_cannot_bypass_plan_or_nested_task_guard(tmp_path):
    manager, record = await stopped(tmp_path)
    ctx = ToolContext(
        working_directory=tmp_path, task_manager=manager, metadata={"engine_mode": "plan"}
    )
    with pytest.raises(ToolError, match="Tasks panel"):
        await TaskCreateTool().execute({"resume": record.id}, ctx)
    ctx.active_task_id = "parent"
    with pytest.raises(ToolError, match="nest|inside|task"):
        await TaskCreateTool().execute({"resume": record.id}, ctx)
    assert record.status is TaskStatus.CANCELED


async def test_changed_scope_rejected_at_atomic_enqueue(tmp_path):
    manager, record = await stopped(tmp_path)
    reviewed = scope_key(task_scope(record))
    record.auto_approve = True
    with pytest.raises(RuntimeError, match="permissions changed"):
        await manager.resume_task(record.id, expected_scope=reviewed)
    assert record.status is TaskStatus.CANCELED


async def test_http_review_confirmation_and_stale_review(tmp_path):
    manager, record = await stopped(tmp_path)
    record.auto_approve = True
    runtime = AppRuntime(working_directory=tmp_path)
    runtime._tool_runtime = SimpleNamespace(task_manager=manager)
    first = await runtime.resume_task(record.id)
    assert first["code"] == "resume_confirmation_required"
    assert first["permission_changes"] == [
        {"field": "auto_approve", "current": False, "target": True}
    ]
    assert record.status is TaskStatus.CANCELED
    record.trust_mode = True
    stale = await runtime.resume_task(record.id, {"confirmation_key": first["confirmation_key"]})
    assert stale["code"] == "resume_confirmation_required"
    assert record.status is TaskStatus.CANCELED
    result = await runtime.resume_task(record.id, {"confirmation_key": stale["confirmation_key"]})
    assert result["ok"]
    assert result["task"]["id"] == record.id
    assert record.auto_approve and record.trust_mode
    assert record.status is TaskStatus.QUEUED


async def test_http_checks_selected_thread_not_origin_and_rejects_missing_thread(tmp_path):
    manager, record = await stopped(tmp_path)
    record.auto_approve = True

    def load_thread(thread_id):
        if thread_id != "selected":
            raise FileNotFoundError(thread_id)
        return SimpleNamespace(
            workspace=str(tmp_path),
            mode="plan",
            allow_shell=False,
            trust_mode=False,
            auto_approve=False,
            env_mode="local",
            worktree_path=None,
        )

    manager.thread_manager = SimpleNamespace(store=SimpleNamespace(load_thread=load_thread))
    runtime = AppRuntime(working_directory=tmp_path)
    runtime._tool_runtime = SimpleNamespace(task_manager=manager)
    result = await runtime.resume_task(record.id, {"thread_id": "selected"})
    assert result["code"] == "resume_confirmation_required"
    assert {c["field"] for c in result["permission_changes"]} == {"auto_approve", "mode"}
    assert not (await runtime.resume_task(record.id, {"thread_id": "missing"}))["ok"]
    assert record.status is TaskStatus.CANCELED


@pytest.mark.parametrize(
    "auto,trust,shell,mode",
    [(False, False, False, "plan"), (True, False, True, "agent"), (True, True, True, "agent")],
)
async def test_executor_uses_stored_authority_before_attaching_child_agents(
    tmp_path, monkeypatch, auto, trust, shell, mode
):
    import asyncio

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.dispatch import _run_task_engine_turn
    from deepseek_tui.tools.task.models import ExecutionTask

    global_cfg = Config(allow_shell=not shell, approval_policy="auto" if not auto else "on-request")
    global_cfg.features.exec_policy = False
    monkeypatch.setattr("deepseek_tui.config.loader.ConfigLoader.load", lambda self: global_cfg)
    monkeypatch.setattr(
        "deepseek_tui.client.factory.build_llm_client",
        lambda cfg: SimpleNamespace(close=AsyncMock()),
    )

    async def create_runtime(**kw):
        assert kw["config"].allow_shell == shell
        assert kw["mode"] == mode
        # Simulate legacy runtime auto -> trust mapping before task override.
        return SimpleNamespace(context=SimpleNamespace(trust_mode=True), shutdown=AsyncMock())

    monkeypatch.setattr("deepseek_tui.tools.runtime.create_tool_runtime", create_runtime)

    class ReachedEngine(Exception):
        pass

    async def create_engine(**kw):
        assert kw["mode"] == mode
        assert kw["config"].approval_policy == ("auto" if auto else "on-request")
        assert kw["config"].features.exec_policy is False
        assert kw["tool_runtime"].context.trust_mode == trust
        raise ReachedEngine

    monkeypatch.setattr("deepseek_tui.engine.orchestrator.Engine.create", create_engine)
    task = ExecutionTask(
        id="task_saved",
        prompt="continue",
        model="deepseek-chat",
        workspace=str(tmp_path),
        mode_label=mode,
        allow_shell=shell,
        trust_mode=trust,
        auto_approve=auto,
    )
    with pytest.raises(ReachedEngine):
        await _run_task_engine_turn(task, asyncio.Event())


async def test_detached_task_can_be_reviewed_after_origin_thread_is_deleted(tmp_path):
    manager, record = await stopped(tmp_path)
    record.thread_id = "deleted-origin"
    record.auto_approve = True
    manager.thread_manager = SimpleNamespace(
        store=SimpleNamespace(
            load_thread=lambda _: pytest.fail("No selected thread should not load the old origin")
        )
    )
    runtime = AppRuntime(
        working_directory=tmp_path, tool_runtime=SimpleNamespace(task_manager=manager)
    )
    review = await runtime.resume_task(record.id)
    assert review["code"] == "resume_confirmation_required"
    result = await runtime.resume_task(record.id, {"confirmation_key": review["confirmation_key"]})
    assert result["ok"]
    assert record.thread_id == "deleted-origin"
