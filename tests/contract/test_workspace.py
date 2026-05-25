from __future__ import annotations

import pytest
from httpx import AsyncClient

from deepseek_tui.app_server.runtime_threads import tool_item_metadata


def test_tool_item_metadata_edit_file() -> None:
    meta = tool_item_metadata("edit_file", {"path": "src/main.py"})
    assert meta == {"path": "src/main.py"}


def test_tool_item_metadata_non_file_tool() -> None:
    assert tool_item_metadata("grep", {"pattern": "foo"}) is None


@pytest.mark.asyncio
async def test_workspace_status(client: AsyncClient) -> None:
    r = await client.get("/v1/workspace/status")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert "workspace" in body
    runtime_api = body.get("runtime_api")
    assert isinstance(runtime_api, dict)
    assert runtime_api.get("service") == "deepseek-runtime-api"
    assert runtime_api.get("mode") == "http"
    assert isinstance(runtime_api.get("python_version"), str)
