"""cron_create / cron_list / cron_delete — the merged automation tool surface
(A5: the eight ``automation_*`` tools folded into the Claude-style cron trio).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.engine.dispatch import normalize_legacy_tool_call
from deepseek_tui.tools.automation import (
    AUTOMATION_MANAGER_KEY,
    AutomationManager,
    CronCreateTool,
    CronDeleteTool,
    CronListTool,
)
from deepseek_tui.tools.registry import ToolContext, ToolError, ToolRegistry
from deepseek_tui.tools.task.manager import TaskManager
from deepseek_tui.tools.task.models import TaskExecutionResult, TaskManagerConfig

_CREATE_INPUT = {
    "name": "hourly",
    "prompt": "do work",
    "schedule": "0 * * * *",
}


def _context(
    tmp_path: Path, *, task_manager: TaskManager | None = None
) -> ToolContext:
    manager = AutomationManager.open(tmp_path / "automations")
    metadata: dict[str, object] = {AUTOMATION_MANAGER_KEY: manager}
    if task_manager is not None:
        metadata["task_manager"] = task_manager
    return ToolContext(working_directory=tmp_path, metadata=metadata)  # type: ignore[arg-type]


def _manager(ctx: ToolContext) -> AutomationManager:
    return ctx.metadata[AUTOMATION_MANAGER_KEY]  # type: ignore[return-value]


def test_resolve_delivery_rejects_unknown_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepseek_tui.tools.automation import _resolve_delivery

    monkeypatch.setattr(
        "deepseek_tui.automation.inbox.default_feishu_chat_id_from_config",
        lambda: "oc_allowed",
    )
    with pytest.raises(ToolError, match="configured"):
        _resolve_delivery({"mode": "feishu", "to": "oc_stranger"})


def test_resolve_delivery_accepts_and_fills_configured_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepseek_tui.tools.automation import _resolve_delivery

    monkeypatch.setattr(
        "deepseek_tui.automation.inbox.default_feishu_chat_id_from_config",
        lambda: "oc_allowed",
    )
    assert _resolve_delivery({"mode": "feishu", "to": "oc_allowed"})["to"] == (
        "oc_allowed"
    )
    assert _resolve_delivery({"mode": "feishu"})["to"] == "oc_allowed"


def test_resolve_delivery_rejects_when_no_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepseek_tui.tools.automation import _resolve_delivery

    monkeypatch.setattr(
        "deepseek_tui.automation.inbox.default_mail_to_from_config",
        lambda: None,
    )
    with pytest.raises(ToolError, match="configured"):
        _resolve_delivery({"mode": "email", "to": "evil@example.com"})


@pytest.mark.asyncio
async def test_cron_create_rejects_stranger_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "deepseek_tui.automation.inbox.default_feishu_chat_id_from_config",
        lambda: "oc_allowed",
    )
    ctx = _context(tmp_path)
    with pytest.raises(ToolError, match="configured"):
        await CronCreateTool().execute(
            {**_CREATE_INPUT, "delivery": {"mode": "feishu", "to": "oc_evil"}},
            ctx,
        )


@pytest.mark.asyncio
async def test_cron_create_registers_job(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    result = await CronCreateTool().execute(dict(_CREATE_INPUT), ctx)
    assert result.success is True
    record = _manager(ctx).get_automation(result.content)
    assert record.name == "hourly"
    assert record.next_run_at is not None
    assert "run" not in result.metadata


@pytest.mark.asyncio
async def test_cron_create_run_now_enqueues_a_run(tmp_path: Path) -> None:
    async def executor(task, cancel):  # noqa: ANN001
        return TaskExecutionResult(summary="done")

    cfg = TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path)
    task_manager = TaskManager(cfg, executor=executor)
    await task_manager.start()
    try:
        ctx = _context(tmp_path, task_manager=task_manager)
        result = await CronCreateTool().execute(
            {**_CREATE_INPUT, "run_now": True}, ctx
        )
        assert result.success is True
        assert "queued run" in result.content
        assert result.metadata["run"]["task_id"]
        runs = _manager(ctx).list_runs(result.metadata["automation"]["id"])
        assert len(runs) == 1
    finally:
        await task_manager.shutdown()


@pytest.mark.asyncio
async def test_cron_create_run_now_requires_task_manager(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    with pytest.raises(ToolError, match="TaskManager"):
        await CronCreateTool().execute({**_CREATE_INPUT, "run_now": True}, ctx)


@pytest.mark.asyncio
async def test_cron_list_lists_and_reads_detail(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    created = await CronCreateTool().execute(dict(_CREATE_INPUT), ctx)
    automation_id = created.content

    listed = await CronListTool().execute({}, ctx)
    assert listed.metadata["count"] == 1
    assert automation_id[:8] in listed.content

    detail = await CronListTool().execute({"automation_id": automation_id}, ctx)
    assert detail.metadata["automation"]["id"] == automation_id
    assert "prompt:   do work" in detail.content
    assert "schedule: 0 * * * *" in detail.content
    assert detail.metadata["runs"] == []


@pytest.mark.asyncio
async def test_cron_list_unknown_id_errors(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    with pytest.raises(ToolError, match="not found"):
        await CronListTool().execute({"automation_id": "nope"}, ctx)


@pytest.mark.asyncio
async def test_cron_delete_wipes_job_and_history(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    created = await CronCreateTool().execute(dict(_CREATE_INPUT), ctx)
    automation_id = created.content
    result = await CronDeleteTool().execute({"automation_id": automation_id}, ctx)
    assert result.success is True
    with pytest.raises(KeyError):
        _manager(ctx).get_automation(automation_id)


@pytest.mark.asyncio
async def test_cron_tools_error_without_manager(tmp_path: Path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="AutomationManager"):
        await CronListTool().execute({}, ctx)


@pytest.mark.asyncio
async def test_legacy_automation_create_executes_via_forwarding(
    tmp_path: Path,
) -> None:
    """A legacy automation_create call, after normalization, runs the merged
    cron_create handler against the registry."""
    registry = ToolRegistry()
    registry.register(CronCreateTool())
    registry.register(CronListTool())
    ctx = _context(tmp_path)

    name, args = normalize_legacy_tool_call("automation_create", dict(_CREATE_INPUT))
    created = await registry.execute(name, args, ctx)
    assert created.success is True

    name, args = normalize_legacy_tool_call(
        "automation_read", {"automation_id": created.content}
    )
    detail = await registry.execute(name, args, ctx)
    assert detail.success is True
    assert detail.metadata["automation"]["id"] == created.content
