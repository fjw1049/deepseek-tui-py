"""Tests for automation tool profiles and current_time offset coercion."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from deepseek_tui.engine.prompts import (
    AUTOMATION_COMPOSER_HEADING,
    TOOL_PROFILE_AUTOMATION_COMPOSER,
    TOOL_PROFILE_CRON,
    detect_tool_profile_from_prompt,
    filter_tools_for_profile,
)
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.time_tools import CurrentTimeTool


def test_detect_automation_composer_profile() -> None:
    prompt = f"{AUTOMATION_COMPOSER_HEADING}\n\nuser text"
    assert detect_tool_profile_from_prompt(prompt) == TOOL_PROFILE_AUTOMATION_COMPOSER


def test_detect_cron_profile() -> None:
    assert detect_tool_profile_from_prompt("[cron:abc name] do work") == TOOL_PROFILE_CRON


def test_composer_profile_filters_tools() -> None:
    catalog = [
        {"type": "function", "function": {"name": "current_time", "parameters": {}}},
        {"type": "function", "function": {"name": "automation_create", "parameters": {}}},
        {"type": "function", "function": {"name": "web_search", "parameters": {}}},
        {"type": "function", "function": {"name": "mcp_bing_search", "parameters": {}}},
    ]
    out = filter_tools_for_profile(catalog, TOOL_PROFILE_AUTOMATION_COMPOSER)
    names = {t["function"]["name"] for t in out}
    assert names == {"current_time", "automation_create"}


def test_cron_profile_keeps_search_tools() -> None:
    catalog = [
        {"type": "function", "function": {"name": "web_search", "parameters": {}}},
        {"type": "function", "function": {"name": "exec_shell", "parameters": {}}},
        {"type": "function", "function": {"name": "mcp_bing_cn_search", "parameters": {}}},
    ]
    out = filter_tools_for_profile(catalog, TOOL_PROFILE_CRON)
    names = {t["function"]["name"] for t in out}
    assert "web_search" in names
    assert "mcp_bing_cn_search" in names
    assert "exec_shell" not in names


@pytest.mark.asyncio
async def test_current_time_accepts_scalar_offset_minutes() -> None:
    tool = CurrentTimeTool()
    ctx = ToolContext(working_directory=".")
    result = await tool.execute(
        {"timezone": "Asia/Shanghai", "offset_minutes": 2},
        ctx,
    )
    assert result.success is True
    assert "in_2min_utc" in result.content


def test_stale_running_task_detection() -> None:
    from deepseek_tui.tools.task import (
        STALE_RUNNING_TASK_SECONDS,
        TaskRecord,
        TaskStatus,
        _is_stale_running_task,
    )

    # Just inside the window → still eligible for restart re-queue.
    recent = (
        datetime.now(timezone.utc)
        - timedelta(seconds=STALE_RUNNING_TASK_SECONDS - 60)
    ).isoformat()
    fresh = TaskRecord(
        schema_version=2,
        id="task_fresh",
        prompt="x",
        model="m",
        workspace="/tmp",
        mode="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=True,
        status=TaskStatus.RUNNING,
        created_at=recent,
        started_at=recent,
    )
    assert _is_stale_running_task(fresh) is False

    old = (
        datetime.now(timezone.utc)
        - timedelta(seconds=STALE_RUNNING_TASK_SECONDS + 60)
    ).isoformat()
    task = TaskRecord(
        schema_version=2,
        id="task_x",
        prompt="x",
        model="m",
        workspace="/tmp",
        mode="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=True,
        status=TaskStatus.RUNNING,
        created_at=old,
        started_at=old,
    )
    assert _is_stale_running_task(task) is True
