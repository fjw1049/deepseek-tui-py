"""ASGI fixtures for runtime API contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from deepseek_tui.app_server.runtime import AppRuntime
from deepseek_tui.app_server.server import build_fastapi_app
from deepseek_tui.config.models import Config, FeatureConfig


@pytest.fixture
def runtime_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
def runtime_app(runtime_data_dir: Path) -> object:
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=False,
            subagents=False,
            automations=False,
        ),
    )
    runtime = AppRuntime(config=config, working_directory=runtime_data_dir)
    return build_fastapi_app(
        runtime,
        http_mode=True,
        insecure_no_auth=True,
    )


@pytest.fixture
def authed_runtime_app(runtime_data_dir: Path) -> tuple[object, str]:
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=False,
            subagents=False,
            automations=False,
        ),
    )
    runtime = AppRuntime(config=config, working_directory=runtime_data_dir)
    token = "test-runtime-token"
    app = build_fastapi_app(
        runtime,
        http_mode=True,
        auth_token=token,
    )
    return app, token


@pytest.fixture
async def client(runtime_app: object) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=runtime_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def authed_client(
    authed_runtime_app: tuple[object, str],
) -> AsyncIterator[tuple[AsyncClient, str]]:
    app, token = authed_runtime_app
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
    ) as ac:
        yield ac, token
