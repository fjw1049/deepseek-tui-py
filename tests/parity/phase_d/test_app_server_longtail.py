"""Parity tests for app-server long-tail routes.

Mirrors a subset of Rust ``runtime_api.rs`` (runtime_api.rs:297-341)
that overlaps with existing CLI thread/task/skill commands. Covers
the 7 routes added in the 2026-05-10 integration debt sweep:
``/skills``, ``/tasks``, ``/tasks/{id}``, ``/tasks/{id}/cancel``,
``/apps/mcp/servers``, ``/apps/mcp/tools``, ``/workspace/status``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio

from deepseek_tui.app_server import AppRuntime, build_fastapi_app


@pytest_asyncio.fixture
async def runtime(tmp_path: Path) -> AsyncIterator[AppRuntime]:
    rt = await AppRuntime.create(working_directory=tmp_path)
    try:
        yield rt
    finally:
        await rt.shutdown()


@pytest_asyncio.fixture
async def client(runtime: AppRuntime) -> AsyncIterator[httpx.AsyncClient]:
    app = build_fastapi_app(runtime)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


class TestSkillsRoute:
    async def test_get_skills_returns_ok_with_empty_list_for_unconfigured_workspace(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """Mirror Rust ``list_skills`` (runtime_api.rs:657)."""
        r = await client.get("/skills")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert isinstance(body["skills"], list)
        assert isinstance(body["warnings"], list)

    async def test_skills_picks_up_workspace_skill_directory(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """Drop a skill in <workspace>/.deepseek/skills/X/SKILL.md and
        verify the route picks it up."""
        skill_dir = tmp_path / ".deepseek" / "skills" / "demo"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: demo\ndescription: A demo\n---\nbody",
            encoding="utf-8",
        )
        r = await client.get("/skills")
        body = r.json()
        names = [s["name"] for s in body["skills"]]
        assert "demo" in names


class TestWorkspaceStatusRoute:
    async def test_returns_workspace_metadata(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        r = await client.get("/workspace/status")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        ws = body["workspace"]
        assert ws["cwd"] == str(tmp_path.resolve())
        assert ws["provider"] == "deepseek"
        assert ws["thread_count"] == 0


class TestTasksRoute:
    async def test_list_tasks_when_manager_unavailable_returns_error(
        self, client: httpx.AsyncClient, runtime: AppRuntime
    ) -> None:
        if (
            runtime._tool_runtime is not None
            and runtime._tool_runtime.task_manager is not None
        ):
            r = await client.get("/tasks")
            body = r.json()
            assert body["ok"] is True
            assert "tasks" in body
            return
        r = await client.get("/tasks")
        body = r.json()
        assert body["ok"] is False

    async def test_get_unknown_task_returns_error(
        self, client: httpx.AsyncClient, runtime: AppRuntime
    ) -> None:
        if (
            runtime._tool_runtime is None
            or runtime._tool_runtime.task_manager is None
        ):
            r = await client.get("/tasks/unknown")
            body = r.json()
            assert body["ok"] is False
            return
        r = await client.get("/tasks/this-task-does-not-exist")
        body = r.json()
        assert body["ok"] is False
        assert "not found" in body["error"].lower()

    async def test_cancel_unknown_task_returns_error(
        self, client: httpx.AsyncClient, runtime: AppRuntime
    ) -> None:
        if (
            runtime._tool_runtime is None
            or runtime._tool_runtime.task_manager is None
        ):
            r = await client.post("/tasks/unknown/cancel")
            body = r.json()
            assert body["ok"] is False
            return
        r = await client.post("/tasks/this-task-does-not-exist/cancel")
        body = r.json()
        assert body["ok"] is False


class TestMcpRoutes:
    async def test_list_mcp_servers_returns_ok_or_disabled(
        self, client: httpx.AsyncClient
    ) -> None:
        r = await client.get("/apps/mcp/servers")
        body = r.json()
        assert "ok" in body

    async def test_list_mcp_tools_returns_ok_or_disabled(
        self, client: httpx.AsyncClient
    ) -> None:
        r = await client.get("/apps/mcp/tools")
        body = r.json()
        assert "ok" in body
