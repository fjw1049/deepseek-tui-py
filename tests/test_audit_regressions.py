"""Cross-module regressions from the first four system audits."""

import asyncio
import json
import shlex
import sys

import pytest

from deepseek_tui.config.models import Config, HooksConfig, LifecycleHookEntry
from deepseek_tui.integrations.hooks import (
    HookContext,
    HookExecutor,
    _run_shell,
    aggregate_hook_decision,
    build_hook_dispatcher,
)
from deepseek_tui.policy.exec_policy import ExecPolicyConfig, RuleSet, TomlBackedPolicy
from deepseek_tui.policy.sandbox import ExecutionSandboxPolicy, suggest_elevation_policy
from deepseek_tui.server.approval import ElevationBridge, PendingElevationRecord
from deepseek_tui.tools.approval import build_approval_key
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.shell import check_command_policy
from deepseek_tui.tools.task import NewTaskRequest, TaskManager, TaskManagerConfig, TaskStatus
from deepseek_tui.tools.task.store import _load_state, _task_record_to_dict
from deepseek_tui.tools.durable_transcript import load_transcript


def manager(path):
    return TaskManager(TaskManagerConfig(data_dir=path, default_workspace=path.parent))


async def test_task_store_rejects_second_live_scheduler(tmp_path):
    first, second = manager(tmp_path), manager(tmp_path)
    await first.start()
    try:
        with pytest.raises(RuntimeError, match="active scheduler"):
            await second.start()
    finally:
        await first.shutdown()
    await second.start()
    await second.shutdown()


async def test_enqueue_failure_cannot_execute(tmp_path, monkeypatch):
    m = manager(tmp_path)

    def fail(_):
        raise OSError("synthetic disk error")

    monkeypatch.setattr(m, "_persist_task_locked", fail)
    try:
        with pytest.raises(OSError):
            await m.add_task(NewTaskRequest(prompt="must not run"))
        assert not m._tasks and not m._queue
    finally:
        await m.shutdown()


async def test_idempotent_enqueue_survives_restart(tmp_path):
    first = manager(tmp_path)
    task = await first.add_task(NewTaskRequest(prompt="once", idempotency_key="slot"))
    await first.shutdown()
    second = manager(tmp_path)
    try:
        duplicate = await second.add_task(NewTaskRequest(prompt="once", idempotency_key="slot"))
        assert duplicate.id == task.id
        assert len(list((tmp_path / "tasks").glob("*.json"))) == 1
    finally:
        await second.shutdown()


async def test_eviction_does_not_change_history_or_prefix_resolution(tmp_path):
    m = manager(tmp_path)
    try:
        records = [await m.add_task(NewTaskRequest(prompt=str(i))) for i in range(51)]
        m._queue.clear()
        for rec in records:
            rec.status = TaskStatus.COMPLETED
        m._persist_all_locked()
        m._evict_terminal_tasks_locked()
        assert len(await m.list_tasks()) == 51
        await m.get_task(records[0].id)
        assert len(await m.list_tasks()) == 51
        assert len(m._tasks) <= 50
        m._tasks = {records[0].id: records[0]}
        with pytest.raises(KeyError, match="Ambiguous"):
            await m.get_task("task_")
    finally:
        await m.shutdown()


async def test_corrupt_nested_task_record_is_isolated(tmp_path):
    m = manager(tmp_path)
    try:
        task = await m.add_task(NewTaskRequest(prompt="bad"))
        data = _task_record_to_dict(task)
        data["checklist"] = ["invalid"]
        (tmp_path / "tasks" / f"{task.id}.json").write_text(json.dumps(data))
        assert _load_state(tmp_path / "tasks", tmp_path / "queue.json")[0] == {}
    finally:
        await m.shutdown()


@pytest.mark.parametrize(
    "data", [{"schema_version": 999}, {"cursor": ["invalid"]}, {"messages": [None]}]
)
def test_invalid_transcript_is_not_silently_replayed(tmp_path, data):
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_transcript(path)


def test_multiline_shell_preserves_deny(tmp_path):
    policy = TomlBackedPolicy(ExecPolicyConfig(rules={"test": RuleSet(deny=["printf blocked"])}))
    with pytest.raises(ToolError, match="forbidden"):
        check_command_policy(
            "echo ready\nprintf blocked", ToolContext(working_directory=tmp_path, policy=policy)
        )


def test_network_elevation_keeps_readonly(tmp_path):
    policy = suggest_elevation_policy(
        ExecutionSandboxPolicy.read_only(), "network denied", workspace=tmp_path
    )
    assert policy.kind == "read-only" and policy.has_network_access()
    assert policy.get_writable_roots(tmp_path) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("cwds", ["/other"]),
        ("timezone", "UTC"),
        ("run_now", True),
        ("paused", True),
        ("run_at", "2027-01-01"),
    ],
)
def test_cron_grants_include_execution_parameters(field, value):
    args = {"name": "daily", "schedule": "0 9 * * *", "prompt": "report"}
    assert build_approval_key("cron_create", args) != build_approval_key(
        "cron_create", args | {field: value}
    )


async def test_elevation_cannot_replace_request_and_cleans_done_records():
    bridge = ElevationBridge()
    future = bridge.register(
        "id",
        meta=PendingElevationRecord(
            thread_id="thread", tool_name="exec_shell", reason="test", elevation_kind="network"
        ),
    )
    with pytest.raises(ValueError, match="Duplicate"):
        bridge.register("id")
    future.cancel()
    bridge.cancel_for_thread("thread")
    assert not bridge._pending and not bridge._meta


async def test_required_hook_error_blocks_guard_chain(tmp_path):
    executor = HookExecutor(
        HooksConfig(
            hooks=[
                LifecycleHookEntry(
                    event="tool_call_before", command="exit 1", continue_on_error=False
                ),
                LifecycleHookEntry(event="tool_call_before", command="exit 2"),
            ]
        ),
        tmp_path,
    )
    assert aggregate_hook_decision(await executor.execute("tool_call_before")).blocked


@pytest.mark.parametrize("required", [False, True])
async def test_unknown_hook_condition_is_isolated(tmp_path, required):
    executor = HookExecutor(
        HooksConfig(hooks=[
            LifecycleHookEntry(
                event="tool_call_before", command="exit 1", name="invalid",
                condition={"type": "typo"}, continue_on_error=not required,
            ),
            LifecycleHookEntry(event="tool_call_before", command="printf valid", name="valid"),
        ]),
        tmp_path,
    )
    results = await executor.execute("tool_call_before")
    assert not results[0].success
    assert results[0].blocked is required
    expected = ["invalid"] if required else ["invalid", "valid"]
    assert [result.name for result in results] == expected
    if not required:
        assert results[1].stdout == "valid"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
@pytest.mark.parametrize("cancel", [False, True])
async def test_hook_cancellation_and_timeout_stop_descendants(tmp_path, cancel):
    marker, ready = tmp_path / "marker", tmp_path / "ready"
    script = tmp_path / "child.py"
    script.write_text(
        f"import pathlib,time\npathlib.Path({str(ready)!r}).touch()\ntime.sleep(0.3)\npathlib.Path({str(marker)!r}).touch()\n"
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} & wait"
    task = asyncio.create_task(_run_shell(command, timeout=2 if cancel else 0.1))
    if cancel:
        async with asyncio.timeout(2):
            while not ready.exists():
                await asyncio.sleep(0.005)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else asyncio.TimeoutError):
        await task
    await asyncio.sleep(0.35)
    assert not marker.exists()


async def test_hook_output_is_bounded(tmp_path):
    code = 'import sys;sys.stdout.write("x"*1048576)'
    with pytest.raises(ValueError, match="exceeded"):
        await _run_shell(f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}", timeout=2)


def test_hook_config_and_file_dialect(tmp_path):
    assert build_hook_dispatcher(Config(hooks=HooksConfig(enabled=False, stdout=True))).sinks == []
    ex = HookExecutor(HooksConfig(default_timeout_secs=60), tmp_path)
    assert ex._timeout(LifecycleHookEntry(event="x", command="true", timeout_secs=1)) == 1
    assert ex._timeout(LifecycleHookEntry(event="x", command="true")) == 60
    ctx = HookContext(tool_name="write_file", tool_args='{"path":"x","content":"v"}')
    assert ctx.to_stdin_payload("tool_call_before", "claude")["tool_input"]["file_path"] == "x"
    assert "DEEPSEEK_TOOL_ARGS" not in HookContext(tool_args="x" * 200000).to_env_vars()


@pytest.mark.parametrize("operation", ["resume", "cancel"])
async def test_failed_task_transition_preserves_memory_and_queue(tmp_path, monkeypatch, operation):
    m = manager(tmp_path)
    try:
        record = await m.add_task(NewTaskRequest(prompt="transition"))
        if operation == "resume":
            record.status = TaskStatus.CANCELED
            m._queue.clear()
            m._persist_all_locked()
        before = _task_record_to_dict(record)
        queue = list(m._queue)

        def fail(_):
            raise OSError("synthetic disk error")

        monkeypatch.setattr(m, "_persist_task_locked", fail)
        with pytest.raises(OSError):
            await (m.resume_task(record.id) if operation == "resume" else m.cancel_task(record.id))
        assert _task_record_to_dict(record) == before
        assert list(m._queue) == queue
    finally:
        await m.shutdown()


async def test_completed_receipt_avoids_reexecution_even_with_bad_transcript(tmp_path, monkeypatch):
    from deepseek_tui.engine.dispatch import _run_task_engine_turn
    from deepseek_tui.tools.task.models import ExecutionTask
    from deepseek_tui.tools.durable_transcript import task_transcript_path
    from unittest.mock import Mock

    m = manager(tmp_path)
    record = await m.add_task(NewTaskRequest(prompt="already finished"))
    receipt = tmp_path / "completions" / f"{record.id}.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps({"task_id": record.id, "summary": "saved result"}))
    transcript = task_transcript_path(tmp_path, record.id)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("not json")
    build = Mock(side_effect=AssertionError("must not create another client"))
    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", build)
    try:
        result = await _run_task_engine_turn(
            ExecutionTask(
                id=record.id,
                prompt=record.prompt,
                model=record.model,
                workspace=record.workspace,
                mode_label=record.mode,
                allow_shell=False,
                trust_mode=False,
                auto_approve=False,
                task_manager=m,
            ),
            asyncio.Event(),
        )
        assert result.summary == "saved result" and result.error is None
        build.assert_not_called()
    finally:
        await m.shutdown()


def test_network_hard_deny_overrides_session_approval(tmp_path):
    from deepseek_tui.policy.network import Decision, NetworkPolicy, NetworkPolicyDecider

    decider = NetworkPolicyDecider(
        NetworkPolicy(allow=["allowed.example"], deny=["blocked.example"]),
        audit_path=tmp_path / "network.log",
    )
    assert decider.evaluate("https://allowed.example") is Decision.ALLOW
    decider.approve("blocked.example")
    assert decider.evaluate("https://blocked.example") is Decision.DENY


async def test_never_policy_cannot_be_overridden_by_child_autoapproval(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from deepseek_tui.engine.handle import AutoApprovalHandler
    from deepseek_tui.tools.file import WriteFileTool
    from deepseek_tui.tools.registry import ToolRegistry
    from deepseek_tui.tools.subagent.loop import _execute_subagent_tool

    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.execute = AsyncMock()
    result = await _execute_subagent_tool(
        registry,
        ToolContext(working_directory=tmp_path),
        tool_name="write_file",
        tool_input={"path": "x", "content": "x"},
        auto_approve=True,
        runtime=SimpleNamespace(
            config=Config(approval_policy="never"), approval_handler=AutoApprovalHandler()
        ),
    )
    assert result.startswith("Error:")
    registry.execute.assert_not_awaited()


async def test_automation_reconciles_old_runs_and_unsent_terminal_runs(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from deepseek_tui.tools.automation import (
        AutomationManager,
        AutomationRunRecord,
        AutomationRunStatus,
        CreateAutomationRequest,
    )

    m = AutomationManager(tmp_path)
    job = m.create_automation(
        CreateAutomationRequest(
            name="report",
            prompt="report",
            schedule="0 9 * * *",
            timezone="UTC",
            delivery={"mode": "feishu", "to": "synthetic", "best_effort": False},
        )
    )
    for i in range(102):
        run = AutomationRunRecord(
            id=str(i),
            automation_id=job.id,
            scheduled_for="2026-09-27T00:00:00Z",
            created_at=f"2026-09-27T00:{i // 60:02}:{i % 60:02}Z",
            task_id="task",
            status=AutomationRunStatus.RUNNING if i == 0 else AutomationRunStatus.COMPLETED,
            delivery_done=i > 1,
        )
        m.save_run(run)
    deliver = AsyncMock()
    monkeypatch.setattr("deepseek_tui.automation.pipeline._FeishuSink.deliver", deliver)
    tasks = SimpleNamespace(
        get_task=AsyncMock(
            return_value=SimpleNamespace(
                status=TaskStatus.COMPLETED,
                result_summary="report",
                error=None,
                thread_id=None,
                turn_id=None,
                started_at=None,
                ended_at=None,
            )
        )
    )
    await m.reconcile_run_statuses(tasks)
    runs = {run.id: run for run in m.list_runs(job.id)}
    assert runs["0"].status is AutomationRunStatus.COMPLETED
    assert runs["0"].delivery_done and runs["1"].delivery_done
    assert deliver.await_count == 2


async def test_concurrent_scheduler_ticks_enqueue_one_slot(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from deepseek_tui.tools.automation import AutomationManager, CreateAutomationRequest

    m = AutomationManager(tmp_path)
    job = m.create_automation(
        CreateAutomationRequest(
            name="once",
            prompt="report",
            timezone="UTC",
            run_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        )
    )
    calls = []

    async def enqueue(automation, run, tasks):
        calls.append(run.id)
        # Dispatch intent must exist even while downstream I/O yields.
        assert m.list_runs(job.id)[0].id == run.id
        await asyncio.sleep(0)
        run.task_id = "task"

    monkeypatch.setattr(m, "_enqueue_run_task", enqueue)
    await asyncio.gather(m.scheduler_tick(None), m.scheduler_tick(None))
    assert len(calls) == 1
    assert len(m.list_runs(job.id)) == 1


@pytest.mark.parametrize("raw", ["not json", "[]", '{"cursor": []}'])
def test_corrupt_transcript_cannot_restart_original_prompt(tmp_path, raw):
    path = tmp_path / "transcript.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        load_transcript(path)


async def test_direct_tool_transport_runs_guard_on_canonical_name(tmp_path):
    from unittest.mock import AsyncMock
    from deepseek_tui.server.runtime import AppRuntime

    runtime = AppRuntime(
        working_directory=tmp_path,
        config=Config(
            hooks=HooksConfig(
                hooks=[
                    LifecycleHookEntry(
                        event="tool_call_before",
                        command="exit 2",
                        condition={"type": "tool_name", "name": "task_stop"},
                    )
                ]
            )
        ),
    )
    runtime._handle_tool_impl = AsyncMock()
    try:
        response = await runtime.handle_tool(
            {
                "call": {"name": "task_cancel", "arguments": {"task_id": "synthetic"}},
            }
        )
        assert response["ok"] is False
        runtime._handle_tool_impl.assert_not_awaited()
    finally:
        await runtime.shutdown()
