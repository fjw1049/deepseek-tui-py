import json

import pytest
from httpx import ASGITransport, AsyncClient

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.mobile.settings import router
from deepseek_tui.server.runtime import AppRuntime


@pytest.fixture
async def settings_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = AppRuntime(
        config=Config(
            features=FeatureConfig(mcp=False, tasks=False, automations=False, subagents=False)
        ),
        working_directory=workspace,
    )
    app = build_fastapi_app(runtime, http_mode=True, auth_token="test-settings")
    if not any(r.path == "/v1/mobile-settings/mcp" for r in app.routes):
        app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer test-settings"},
    ) as client:
        yield client, tmp_path


@pytest.mark.asyncio
async def test_skills_read_install_untrusted_delete_and_builtin_guard(settings_client):
    client, root = settings_client
    source = root / "sample"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: Sample\ndescription: Test skill\n---\n# Instructions"
    )
    (source / ".trusted").touch()
    endpoint = "/v1/mobile-settings/skills"
    assert (
        await client.post(endpoint + "/install", json={"source": str(source)})
    ).status_code == 400
    response = await client.post(
        endpoint + "/install", json={"source": str(source), "confirm": True}
    )
    assert response.status_code == 201, response.text
    target = root / "home" / "skills" / "sample"
    assert not (target / ".trusted").exists()
    response = await client.get(endpoint + "/sample")
    assert response.json()["content"].endswith("# Instructions")
    (target / ".system-installed-version").touch()
    assert (
        await client.request("DELETE", endpoint + "/sample", json={"confirm": True})
    ).status_code == 403
    (target / ".system-installed-version").unlink()
    assert (
        await client.request("DELETE", endpoint + "/sample", json={"confirm": True})
    ).status_code == 200
    (root / "home" / "skills" / "outside").symlink_to(source, target_is_directory=True)
    assert (await client.get(endpoint + "/outside")).status_code == 403
    unauth = await client.get(endpoint, headers={"Authorization": "Bearer wrong"})
    assert unauth.status_code == 401


@pytest.mark.asyncio
async def test_memory_revision_conflict_and_project_scope(settings_client):
    client, root = settings_client
    thread = (await client.post("/v1/threads", json={"title": "memory"})).json()
    path = f"/v1/mobile-settings/threads/{thread['id']}/memories"
    response = await client.post(path, json={"content": "Use pytest", "kind": "preference"})
    assert response.status_code == 200, response.text
    entry = response.json()
    updated = await client.patch(
        path + "/" + entry["id"],
        json={"content": "Use offline pytest", "revision": entry["revision"]},
    )
    assert updated.status_code == 200, updated.text
    assert (
        await client.patch(
            path + "/" + entry["id"], json={"content": "stale", "revision": entry["revision"]}
        )
    ).status_code == 409
    records = (await client.get(path)).json()["entries"]
    assert records[0]["content"] == "Use offline pytest"
    assert (
        await client.request(
            "DELETE",
            path + "/" + entry["id"],
            json={"revision": updated.json()["revision"], "confirm": True},
        )
    ).status_code == 200
    assert (await client.get(path)).json()["entries"] == []


@pytest.mark.asyncio
async def test_mcp_preserves_secrets_redacts_reads_and_rejects_stale_save(settings_client):
    client, root = settings_client
    path = root / "home" / "mcp.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "docs": {
                        "url": "https://example.test/mcp?token=secret-query",
                        "headers": {"Authorization": "secret-header"},
                        "env": {"TOKEN": "secret-env"},
                        "enabled": False,
                    }
                }
            }
        )
    )
    endpoint = "/v1/mobile-settings/mcp"
    before = await client.get(endpoint)
    assert before.status_code == 200, before.text
    for secret in ("secret-query", "secret-header", "secret-env"):
        assert secret not in before.text
    revision = before.json()["revision"]
    saved = await client.patch(
        endpoint + "/docs",
        json={
            "revision": revision,
            "enabled": True,
            "headers": {"X-New": "new-secret"},
            "confirm": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["restart_required"] is True
    disk = json.loads(path.read_text())["mcpServers"]["docs"]
    assert disk["headers"] == {"Authorization": "secret-header", "X-New": "new-secret"}
    assert disk["env"]["TOKEN"] == "secret-env"
    assert "new-secret" not in saved.text
    assert (
        await client.patch(
            endpoint + "/docs", json={"revision": revision, "enabled": False, "confirm": True}
        )
    ).status_code == 409
    current = saved.json()["revision"]
    response = await client.patch(
        endpoint + "/local",
        json={
            "revision": current,
            "transport": "stdio",
            "command": "nonexistent-do-not-execute",
            "args": ["--offline"],
            "env": {"TOKEN": "private"},
            "confirm": True,
        },
    )
    assert response.status_code == 200, response.text
    assert "private" not in response.text
