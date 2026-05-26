from __future__ import annotations

import pytest
from httpx import AsyncClient

from deepseek_tui.app_server.runtime_threads import (
    file_change_completion_detail,
    tool_item_metadata,
)


def test_tool_item_metadata_edit_file() -> None:
    meta = tool_item_metadata("edit_file", {"path": "src/main.py"})
    assert meta == {"path": "src/main.py"}


def test_tool_item_metadata_non_file_tool() -> None:
    assert tool_item_metadata("grep", {"pattern": "foo"}) is None


def test_file_change_completion_detail_edit_file() -> None:
    detail = file_change_completion_detail(
        "edit_file",
        {"path": "src/main.py", "search": "foo", "replace": "bar"},
        "ok",
    )
    assert "--- a/src/main.py" in detail
    assert "-foo" in detail
    assert "+bar" in detail


def test_file_change_completion_detail_apply_patch() -> None:
    patch = "--- a/x.txt\n+++ b/x.txt\n@@\n-old\n+new\n"
    detail = file_change_completion_detail(
        "apply_patch",
        {"patch": patch},
        "Applied 1/1 file(s)",
    )
    assert detail == patch


def test_file_change_completion_detail_write_file() -> None:
    detail = file_change_completion_detail(
        "write_file",
        {"path": "notes.txt", "content": "hello\nworld"},
        "ok",
    )
    assert "+++ b/notes.txt" in detail
    assert "+hello" in detail
    assert "+world" in detail


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
