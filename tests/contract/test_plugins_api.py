"""Contract tests for /v1/plugins list + lifecycle routes."""

from __future__ import annotations

import json
from pathlib import Path

from httpx import AsyncClient


def _make_plugin_source(root: Path, name: str = "demo-plugin") -> Path:
    plugin = root / name
    (plugin / ".deepseek-plugin").mkdir(parents=True)
    (plugin / ".deepseek-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "0.1.0",
                "description": "demo",
                "skills": "./skills",
                "hooks": [{"event": "session_start", "command": "echo hi"}],
            }
        ),
        encoding="utf-8",
    )
    skill = plugin / "skills" / "greeter"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: greeter\ndescription: Greets.\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return plugin


async def test_plugins_empty_list(client: AsyncClient) -> None:
    resp = await client.get("/v1/plugins")
    assert resp.status_code == 200
    assert resp.json() == {"plugins": []}


async def test_plugins_install_lifecycle(
    client: AsyncClient, runtime_data_dir: Path
) -> None:
    src = _make_plugin_source(runtime_data_dir / "src")

    resp = await client.post(
        "/v1/plugins/install", json={"spec": str(src), "trust": False}
    )
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "installed"

    resp = await client.get("/v1/plugins")
    plugins = resp.json()["plugins"]
    assert len(plugins) == 1
    row = plugins[0]
    assert row["name"] == "demo-plugin"
    assert row["enabled"] is True
    assert row["trusted"] is False
    assert row["components"] == {
        "skills": True,
        "hooks": True,
        "mcp_servers": False,
    }

    resp = await client.post(
        "/v1/plugins/demo-plugin/action", json={"action": "trust"}
    )
    assert resp.status_code == 200
    resp = await client.post(
        "/v1/plugins/demo-plugin/action", json={"action": "disable"}
    )
    assert resp.status_code == 200

    resp = await client.get("/v1/plugins")
    row = resp.json()["plugins"][0]
    assert row["trusted"] is True
    assert row["enabled"] is False

    resp = await client.request("DELETE", "/v1/plugins/demo-plugin", json={})
    assert resp.status_code == 200
    resp = await client.get("/v1/plugins")
    assert resp.json()["plugins"] == []


async def test_plugins_install_requires_spec(client: AsyncClient) -> None:
    resp = await client.post("/v1/plugins/install", json={})
    assert resp.status_code == 400


async def test_plugins_install_invalid_source(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/plugins/install", json={"spec": "not-a-real-source"}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "plugin_install_failed"


async def test_plugins_unknown_action_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/plugins/whatever/action", json={"action": "explode"}
    )
    assert resp.status_code == 400


async def test_plugins_action_missing_plugin_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/plugins/missing/action", json={"action": "trust"}
    )
    assert resp.status_code == 404
    resp = await client.request("DELETE", "/v1/plugins/missing", json={})
    assert resp.status_code == 404


async def test_plugins_registry_route(
    client: AsyncClient, monkeypatch
) -> None:
    from deepseek_tui.integrations import plugins as plugins_mod

    doc = plugins_mod.PluginRegistryDocument.from_json(
        json.dumps(
            {
                "plugins": {
                    "demo": {
                        "source": "github:owner/demo",
                        "description": "A demo",
                        "permissions": ["read"],
                    }
                }
            }
        )
    )
    monkeypatch.setattr(plugins_mod, "fetch_plugin_registry", lambda url=None: doc)
    resp = await client.get("/v1/plugins/registry")
    assert resp.status_code == 200
    rows = resp.json()["plugins"]
    assert rows == [
        {
            "name": "demo",
            "source": "github:owner/demo",
            "description": "A demo",
            "version": "",
            "components": [],
            "permissions": ["read"],
        }
    ]


async def test_plugins_registry_unavailable(
    client: AsyncClient, monkeypatch
) -> None:
    from deepseek_tui.integrations import plugins as plugins_mod

    monkeypatch.setattr(plugins_mod, "fetch_plugin_registry", lambda url=None: None)
    resp = await client.get("/v1/plugins/registry")
    assert resp.status_code == 503


def _make_marketplace_repo(root: Path, name: str = "demo-market") -> Path:
    repo = root / "market-repo"
    _make_plugin_source(repo / "plugins", "alpha")
    _make_plugin_source(repo / "plugins", "beta")
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {
                "name": name,
                "plugins": [
                    {"name": "alpha", "source": "./plugins/alpha"},
                    {"name": "beta", "source": "./plugins/beta"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return repo


async def test_marketplaces_lifecycle(
    client: AsyncClient, runtime_data_dir: Path
) -> None:
    resp = await client.get("/v1/plugins/marketplaces")
    assert resp.status_code == 200
    assert resp.json() == {"marketplaces": []}

    repo = _make_marketplace_repo(runtime_data_dir)
    resp = await client.post("/v1/plugins/marketplaces", json={"spec": str(repo)})
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "installed"

    resp = await client.get("/v1/plugins/marketplaces")
    rows = resp.json()["marketplaces"]
    assert len(rows) == 1
    assert rows[0]["name"] == "demo-market"
    assert {p["name"] for p in rows[0]["plugins"]} == {"alpha", "beta"}
    assert rows[0]["plugins"][0]["spec"] == "alpha@demo-market"

    # Install a single plugin through the marketplace spec.
    resp = await client.post(
        "/v1/plugins/install", json={"spec": "alpha@demo-market"}
    )
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "installed"
    resp = await client.get("/v1/plugins")
    assert [r["name"] for r in resp.json()["plugins"]] == ["alpha"]

    # Local marketplaces are tracked in place; update is a no-op success.
    resp = await client.post("/v1/plugins/marketplaces/demo-market/update")
    assert resp.status_code == 200

    resp = await client.request(
        "DELETE", "/v1/plugins/marketplaces/demo-market"
    )
    assert resp.status_code == 200
    resp = await client.get("/v1/plugins/marketplaces")
    assert resp.json() == {"marketplaces": []}
    # The local checkout is never deleted.
    assert repo.is_dir()


async def test_marketplaces_add_requires_spec(client: AsyncClient) -> None:
    resp = await client.post("/v1/plugins/marketplaces", json={})
    assert resp.status_code == 400


async def test_marketplaces_missing_404(client: AsyncClient) -> None:
    resp = await client.request("DELETE", "/v1/plugins/marketplaces/nope")
    assert resp.status_code == 404
    resp = await client.post("/v1/plugins/marketplaces/nope/update")
    assert resp.status_code == 404


async def test_plugins_project_scope(
    client: AsyncClient, runtime_data_dir: Path
) -> None:
    src = _make_plugin_source(runtime_data_dir / "src2", name="proj-plugin")
    resp = await client.post(
        "/v1/plugins/install",
        json={
            "spec": str(src),
            "scope": "project",
            "workspace": str(runtime_data_dir),
        },
    )
    assert resp.status_code == 200
    assert (
        runtime_data_dir / ".deepseek" / "plugins" / "proj-plugin"
    ).is_dir()

    resp = await client.get("/v1/plugins")
    rows = resp.json()["plugins"]
    assert [r["scope"] for r in rows if r["name"] == "proj-plugin"] == ["project"]
