"""Tests for workflow worktree isolation and detach enqueue."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.tools.task.manager import TaskManager
from deepseek_tui.tools.task.models import (
    ExecutionTask,
    NewTaskRequest,
    TaskExecutionResult,
    TaskManagerConfig,
    TaskStatus,
)
from deepseek_tui.tools.workflow import WorkflowTool
from deepseek_tui.workflow.detach import (
    encode_detach_prompt,
    execute_detached_workflow,
    is_workflow_detach_prompt,
    parse_detach_prompt,
    wrap_task_executor_for_workflow_detach,
)
from deepseek_tui.workflow.models import (
    WorkflowValidationError,
    parse_workflow_spec,
)
from deepseek_tui.workflow.store import create_run, load_run
from deepseek_tui.workflow.worktree import (
    WorkflowWorktreeError,
    ensure_run_worktree,
    find_git_root,
    worktree_branch_for_run,
)


def _git_init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _minimal_spec(*, worktree: str = "off") -> dict[str, Any]:
    return {
        "version": 1,
        "meta": {"name": "t", "description": "d"},
        "policy": {"worktree": worktree},
        "phases": [
            {
                "id": "p1",
                "title": "P",
                "steps": [
                    {
                        "id": "a1",
                        "type": "agent",
                        "label": "worker",
                        "prompt": "do {{task}}",
                    }
                ],
            }
        ],
    }


def test_parse_policy_worktree_default_off() -> None:
    spec = parse_workflow_spec(_minimal_spec())
    assert spec.policy.worktree == "off"


def test_parse_policy_worktree_on() -> None:
    spec = parse_workflow_spec(_minimal_spec(worktree="on"))
    assert spec.policy.worktree == "on"


def test_parse_policy_worktree_invalid() -> None:
    raw = _minimal_spec(worktree="maybe")
    with pytest.raises(WorkflowValidationError, match="worktree"):
        parse_workflow_spec(raw)


def test_find_git_root_none(tmp_path: Path) -> None:
    assert find_git_root(tmp_path) is None


def test_ensure_run_worktree_fails_outside_git(tmp_path: Path) -> None:
    with pytest.raises(WorkflowWorktreeError, match="git repository"):
        ensure_run_worktree("wf_test", workspace=tmp_path)


def test_ensure_run_worktree_creates_and_reuses(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_init(repo)
    run_id = "wf_abc123def456"
    info1 = ensure_run_worktree(run_id, workspace=repo)
    assert info1.path.is_dir()
    assert (info1.path / "README").is_file()
    assert info1.branch == worktree_branch_for_run(run_id)
    # Edit only inside worktree
    (info1.path / "only_in_tree.txt").write_text("x\n", encoding="utf-8")
    assert not (repo / "only_in_tree.txt").exists()

    info2 = ensure_run_worktree(
        run_id,
        workspace=repo,
        existing_path=str(info1.path),
        existing_branch=info1.branch,
    )
    assert info2.path == info1.path
    assert info2.branch == info1.branch
    assert (info2.path / "only_in_tree.txt").read_text(encoding="utf-8") == "x\n"


def test_detach_prompt_roundtrip(tmp_path: Path) -> None:
    prompt = encode_detach_prompt(run_id="wf_deadbeef0001", workspace=tmp_path)
    assert is_workflow_detach_prompt(prompt)
    parsed = parse_detach_prompt(prompt)
    assert parsed is not None
    assert parsed["run_id"] == "wf_deadbeef0001"
    assert Path(parsed["workspace"]) == tmp_path.resolve()


def test_detach_prompt_rejects_noise() -> None:
    assert parse_detach_prompt("please review the repo") is None
    assert not is_workflow_detach_prompt("hello")


@pytest.mark.asyncio
async def test_task_manager_detach_interceptor(tmp_path: Path) -> None:
    seen: list[str] = []

    async def inner(
        task: ExecutionTask, cancel: asyncio.Event
    ) -> TaskExecutionResult:
        seen.append("inner")
        return TaskExecutionResult(summary="inner-ok")

    async def fake_detach(
        task: ExecutionTask, cancel: asyncio.Event
    ) -> TaskExecutionResult:
        seen.append(f"detach:{parse_detach_prompt(task.prompt)!r}")
        return TaskExecutionResult(summary="detached-ok")

    wrapped = wrap_task_executor_for_workflow_detach(inner)

    # Patch execute_detached_workflow used inside wrap — call wrap's path by
    # temporarily replacing the module function via monkeypatch on import site.
    import deepseek_tui.workflow.detach as detach_mod

    original = detach_mod.execute_detached_workflow
    detach_mod.execute_detached_workflow = fake_detach  # type: ignore[assignment]
    try:
        cfg = TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path)
        mgr = TaskManager(cfg, executor=wrapped)
        await mgr.start()
        try:
            normal = await mgr.add_task(NewTaskRequest(prompt="normal work"))
            det = await mgr.add_task(
                NewTaskRequest(
                    prompt=encode_detach_prompt(run_id="wf_x", workspace=tmp_path)
                )
            )
            for _ in range(50):
                n = await mgr.get_task(normal.id)
                d = await mgr.get_task(det.id)
                if n.status.is_terminal() and d.status.is_terminal():
                    break
                await asyncio.sleep(0.05)
            n = await mgr.get_task(normal.id)
            d = await mgr.get_task(det.id)
            assert n.status is TaskStatus.COMPLETED
            assert d.status is TaskStatus.COMPLETED
            assert d.result_summary == "detached-ok"
            assert "inner" in seen
            assert any(s.startswith("detach:") for s in seen)
        finally:
            await mgr.shutdown()
    finally:
        detach_mod.execute_detached_workflow = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_workflow_tool_detach_enqueues(tmp_path: Path) -> None:
    _git_init(tmp_path)

    cfg = TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path)
    # Never run real detach — just park jobs in queue then cancel workers early.
    async def park(
        task: ExecutionTask, cancel: asyncio.Event
    ) -> TaskExecutionResult:
        await cancel.wait()
        return TaskExecutionResult(summary="", error="canceled")

    mgr = TaskManager(
        cfg, executor=wrap_task_executor_for_workflow_detach(park)
    )
    await mgr.start()

    from deepseek_tui.tools.registry import ToolContext

    class _FakeManager:
        loop_runtime = object()

    ctx = ToolContext(
        working_directory=tmp_path,
        task_manager=mgr,
        subagent_manager=_FakeManager(),  # type: ignore[arg-type]
        metadata={},
    )
    tool = WorkflowTool()
    result = await tool.execute(
        {
            "spec": _minimal_spec(worktree="on"),
            "task": "fix tests",
            "detach": True,
        },
        ctx,
    )
    assert result.success
    meta = result.metadata["workflow"]
    assert meta["detached"] is True
    assert meta["run_id"].startswith("wf_")
    assert meta["task_id"].startswith("task_")
    assert "worktree_path" in meta
    assert Path(meta["worktree_path"]).is_dir()

    record = load_run(meta["run_id"], workspace=tmp_path)
    assert record.task_id == meta["task_id"]
    assert record.worktree_path == meta["worktree_path"]
    assert record.worktree_branch == meta["worktree_branch"]

    # Resume must reuse the same worktree path
    info = ensure_run_worktree(
        record.run_id,
        workspace=tmp_path,
        existing_path=record.worktree_path,
        existing_branch=record.worktree_branch,
    )
    assert str(info.path) == record.worktree_path

    await mgr.shutdown()


@pytest.mark.asyncio
async def test_workflow_tool_worktree_on_non_git_fails(tmp_path: Path) -> None:
    from deepseek_tui.tools.registry import ToolContext, ToolError

    class _FakeRuntime:
        spawn_depth = 0

    class _FakeManager:
        loop_runtime = _FakeRuntime()

    ctx = ToolContext(
        working_directory=tmp_path,
        subagent_manager=_FakeManager(),  # type: ignore[arg-type]
        metadata={},
    )
    tool = WorkflowTool()
    with pytest.raises(ToolError, match="git repository"):
        await tool.execute(
            {"spec": _minimal_spec(worktree="on"), "task": "x"},
            ctx,
        )


@pytest.mark.asyncio
async def test_execute_detached_workflow_cancel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git_init(tmp_path)
    spec = parse_workflow_spec(_minimal_spec())
    record = create_run(spec, task="t", workspace=tmp_path)

    async def boom_run_workflow(*_a: Any, **_k: Any) -> Any:
        from deepseek_tui.workflow.models import WorkflowAbortedError

        raise WorkflowAbortedError("workflow cancelled")

    class _Mgr:
        async def shutdown(self) -> None:
            return None

        def attach_loop_runtime(self, *_a: Any, **_k: Any) -> None:
            return None

        def attach_parent_cancel(self, *_a: Any, **_k: Any) -> None:
            return None

    monkeypatch.setattr(
        "deepseek_tui.workflow.runtime.run_workflow",
        boom_run_workflow,
    )
    monkeypatch.setattr(
        "deepseek_tui.tools.runtime.build_subagent_manager",
        lambda *_a, **_k: (_Mgr(), None),
    )
    monkeypatch.setattr(
        "deepseek_tui.client.factory.build_llm_client",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        "deepseek_tui.config.loader.ConfigLoader.load",
        lambda self: __import__(
            "deepseek_tui.config.models", fromlist=["Config"]
        ).Config(),
    )

    task = ExecutionTask(
        id="task_test",
        prompt=encode_detach_prompt(run_id=record.run_id, workspace=tmp_path),
        model="deepseek-chat",
        workspace=str(tmp_path),
        mode_label="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=True,
    )
    cancel = asyncio.Event()
    out = await execute_detached_workflow(task, cancel)
    assert out.error == "cancelled"
    reloaded = load_run(record.run_id, workspace=tmp_path)
    assert reloaded.status == "cancelled"


@pytest.mark.asyncio
async def test_execute_detached_workflow_holds_and_releases_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the detach path used to skip acquire_run_lease entirely,
    leaving the >ACTIVE_RUN_STALE_SECONDS window open to double-drive (a sync
    resume or a second requeued detach task could race on run.json). It must
    now hold the run lease while driving and release it on completion."""
    import os

    from deepseek_tui.workflow.models import WorkflowRunResult, WorkflowSnapshot
    from deepseek_tui.workflow.store import lease_path

    _git_init(tmp_path)
    spec = parse_workflow_spec(_minimal_spec())
    record = create_run(spec, task="t", workspace=tmp_path)

    lease_observed: dict[str, Any] = {}

    async def probing_run_workflow(*_a: Any, **_k: Any) -> Any:
        # While detach is driving, lease.json must exist and name this pid.
        raw = json.loads(lease_path(record.run_id, workspace=tmp_path).read_text())
        lease_observed["owner_pid"] = raw.get("owner_pid")
        lease_observed["has_heartbeat"] = "heartbeat_at" in raw
        return WorkflowRunResult(
            meta=spec.meta,
            result={"ok": True},
            snapshot=WorkflowSnapshot(
                name=spec.meta.name, description=spec.meta.description
            ),
            logs=[],
            duration_ms=10,
            errors=[],
        )

    class _Mgr:
        async def shutdown(self) -> None:
            return None

        def attach_loop_runtime(self, *_a: Any, **_k: Any) -> None:
            return None

        def attach_parent_cancel(self, *_a: Any, **_k: Any) -> None:
            return None

    monkeypatch.setattr(
        "deepseek_tui.workflow.runtime.run_workflow",
        probing_run_workflow,
    )
    monkeypatch.setattr(
        "deepseek_tui.tools.runtime.build_subagent_manager",
        lambda *_a, **_k: (_Mgr(), None),
    )
    monkeypatch.setattr(
        "deepseek_tui.client.factory.build_llm_client",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        "deepseek_tui.config.loader.ConfigLoader.load",
        lambda self: __import__(
            "deepseek_tui.config.models", fromlist=["Config"]
        ).Config(),
    )

    task = ExecutionTask(
        id="task_lease",
        prompt=encode_detach_prompt(run_id=record.run_id, workspace=tmp_path),
        model="deepseek-chat",
        workspace=str(tmp_path),
        mode_label="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=True,
    )
    cancel = asyncio.Event()
    out = await execute_detached_workflow(task, cancel)
    assert out.error is None, out.error
    assert lease_observed.get("owner_pid") == os.getpid()
    assert lease_observed.get("has_heartbeat") is True
    # After completion the lease must be released.
    assert not lease_path(record.run_id, workspace=tmp_path).is_file()
