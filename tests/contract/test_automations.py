"""Contract tests for /v1/automations and /v1/triggers."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.config.models import Config, FeatureConfig


@pytest.mark.asyncio
async def test_list_automations_unconfigured_returns_503(client: AsyncClient) -> None:
    r = await client.get("/v1/automations")
    assert r.status_code == 503, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("action, expected_state", [("received", "sent"), ("retry", "pending")])
async def test_resolve_delivery_contract(runtime_data_dir, monkeypatch, action, expected_state):
    from deepseek_tui.tools.automation import AutomationRunRecord, AutomationRunStatus, CreateAutomationRequest

    monkeypatch.setenv("DEEPSEEK_AUTOMATIONS_DIR", str(runtime_data_dir / "automations-home"))
    runtime = await AppRuntime.create(
        config=Config(features=FeatureConfig(mcp=False, tasks=True, subagents=False, automations=True)),
        working_directory=runtime_data_dir,
    )
    manager = runtime._tool_runtime.automation_manager
    automation = manager.create_automation(CreateAutomationRequest(name="report", prompt="report", schedule="0 * * * *"))
    run = AutomationRunRecord(id="r1", automation_id=automation.id, scheduled_for="", created_at="",
                              status=AutomationRunStatus.COMPLETED, delivery_state="uncertain", delivery_attempts=1)
    manager.save_run(run)
    app = build_fastapi_app(runtime, http_mode=True, insecure_no_auth=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path = f"/v1/automations/{automation.id}/runs/r1/delivery"
        response = await client.post(path, json={"action": "unknown"})
        assert response.status_code == 422
        response = await client.post(path, json={"action": action})
        assert response.status_code == 200, response.text
        assert response.json()["delivery_state"] == expected_state
        assert manager.list_runs(automation.id)[0].delivery_state == expected_state
        # A stale/double click cannot reset an already resolved delivery.
        response = await client.post(path, json={"action": action})
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_pending_delivery_includes_http_trigger_runs(runtime_data_dir, monkeypatch):
    from deepseek_tui.tools.automation import AutomationRunRecord, AutomationRunStatus, HTTP_TRIGGER_RUNS_KEY

    monkeypatch.setenv("DEEPSEEK_AUTOMATIONS_DIR", str(runtime_data_dir / "automations-home"))
    runtime = await AppRuntime.create(
        config=Config(features=FeatureConfig(mcp=False, tasks=True, subagents=False, automations=True)),
        working_directory=runtime_data_dir,
    )
    manager = runtime._tool_runtime.automation_manager
    manager.save_run(AutomationRunRecord(id="trigger-run", automation_id=HTTP_TRIGGER_RUNS_KEY,
        scheduled_for="", created_at="", status=AutomationRunStatus.COMPLETED, delivery_state="uncertain"))
    app = build_fastapi_app(runtime, http_mode=True, insecure_no_auth=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/automations/deliveries/pending")
        assert response.status_code == 200, response.text
        assert [run["id"] for run in response.json()] == ["trigger-run"]
        response = await client.post(f"/v1/automations/{HTTP_TRIGGER_RUNS_KEY}/runs/trigger-run/delivery", json={"action": "received"})
        assert response.status_code == 200, response.text
        assert (await client.get("/v1/automations/deliveries/pending")).json() == []


@pytest.fixture
async def automations_client(
    runtime_data_dir, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    # Isolate from the developer's real ~/.deepseek automations store.
    monkeypatch.setenv(
        "DEEPSEEK_AUTOMATIONS_DIR", str(runtime_data_dir / "automations-home")
    )
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=True,
            subagents=False,
            automations=True,
        ),
    )
    runtime = await AppRuntime.create(config=config, working_directory=runtime_data_dir)
    app = build_fastapi_app(
        runtime,
        http_mode=True,
        insecure_no_auth=True,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_automations_crud_and_trigger(automations_client: AsyncClient) -> None:
    r = await automations_client.get("/v1/automations")
    assert r.status_code == 200
    assert r.json() == []

    body = {
        "name": "test-job",
        "prompt": "say hi",
        "schedule": "0 * * * *",
        "delivery": {"mode": "silent"},
    }
    r = await automations_client.post("/v1/automations", json=body)
    assert r.status_code == 201, r.text
    created = r.json()
    automation_id = created["id"]
    assert created["name"] == "test-job"

    r = await automations_client.get(f"/v1/automations/{automation_id}")
    assert r.status_code == 200
    assert r.json()["id"] == automation_id

    r = await automations_client.post("/v1/triggers", json={"prompt": "ping"})
    assert r.status_code == 200, r.text
    trigger = r.json()
    assert trigger["status"] == "enqueued"
    assert trigger.get("task_id")

    r = await automations_client.delete(f"/v1/automations/{automation_id}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_resume_completed_one_shot_returns_400(
    runtime_data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming an already-ran one-shot is a caller error → 400, not 500."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv(
        "DEEPSEEK_AUTOMATIONS_DIR", str(runtime_data_dir / "automations-home")
    )
    config = Config(
        features=FeatureConfig(
            mcp=False, tasks=True, subagents=False, automations=True
        ),
    )
    runtime = await AppRuntime.create(config=config, working_directory=runtime_data_dir)
    app = build_fastapi_app(runtime, http_mode=True, insecure_no_auth=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        r = await ac.post(
            "/v1/automations", json={"name": "one-shot", "prompt": "p", "run_at": past}
        )
        assert r.status_code == 201, r.text
        automation_id = r.json()["id"]

        # Drive the one-shot to COMPLETED through the scheduler tick.
        manager = runtime._tool_runtime.automation_manager  # noqa: SLF001
        task_manager = runtime._tool_runtime.task_manager  # noqa: SLF001
        await manager.scheduler_tick(task_manager)

        r = await ac.post(f"/v1/automations/{automation_id}/resume")
        assert r.status_code == 400, r.text
        assert "already ran" in r.json()["detail"]["message"]
