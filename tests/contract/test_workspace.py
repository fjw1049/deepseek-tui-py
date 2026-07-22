from __future__ import annotations

import pytest
from httpx import AsyncClient

from deepseek_tui.server.threads import (
    TurnItemKind,
    file_change_completion_detail,
    tool_item_metadata,
    tool_kind_for_name,
    tool_started_metadata,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("write_file", TurnItemKind.FILE_CHANGE),
        ("edit_file", TurnItemKind.FILE_CHANGE),
        ("apply_patch", TurnItemKind.FILE_CHANGE),
        ("exec_shell", TurnItemKind.COMMAND_EXECUTION),
        ("exec_shell_wait", TurnItemKind.COMMAND_EXECUTION),
        ("checklist_write", TurnItemKind.TOOL_CALL),
        ("checklist_update", TurnItemKind.TOOL_CALL),
        ("checklist_add", TurnItemKind.TOOL_CALL),
        ("todo_write", TurnItemKind.TOOL_CALL),
        ("update_plan", TurnItemKind.TOOL_CALL),
        ("read_file", TurnItemKind.TOOL_CALL),
        ("grep_files", TurnItemKind.TOOL_CALL),
    ],
)
def test_tool_kind_for_name_uses_exact_file_tools(
    name: str, expected: TurnItemKind
) -> None:
    assert tool_kind_for_name(name) == expected


def test_tool_item_metadata_checklist_write_is_todo_not_file_path() -> None:
    meta = tool_item_metadata(
        "checklist_write",
        {"todos": [{"id": 1, "content": "fix kind", "status": "pending"}]},
    )
    assert meta is not None
    assert meta.get("tool_name") == "checklist_write"
    assert "path" not in meta
    assert meta.get("items")


def test_tool_item_metadata_edit_file() -> None:
    meta = tool_item_metadata("edit_file", {"path": "src/main.py"})
    assert meta == {"path": "src/main.py"}


def test_tool_item_metadata_non_file_tool() -> None:
    assert tool_item_metadata("grep", {"pattern": "foo"}) is None


def test_tool_started_metadata_persists_tool_input_for_read_tools() -> None:
    # Without this, list_dir/grep rows lose their descriptor after a reload.
    assert tool_started_metadata("list_dir", {"path": "src"}) == {
        "tool_input": {"path": "src"}
    }
    assert tool_started_metadata("grep", {"pattern": "TODO"}) == {
        "tool_input": {"pattern": "TODO"}
    }


def test_tool_started_metadata_merges_file_path_with_tool_input() -> None:
    assert tool_started_metadata("edit_file", {"path": "src/main.py"}) == {
        "path": "src/main.py",
        "tool_input": {"path": "src/main.py"},
    }


def test_tool_started_metadata_handles_json_string_args() -> None:
    assert tool_started_metadata("read_file", '{"path": "a.py"}') == {
        "tool_input": {"path": "a.py"}
    }


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


def test_file_change_completion_detail_prefers_mutation_metadata() -> None:
    patch = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@\n-old\n+new\n"
    detail = file_change_completion_detail(
        "edit_file",
        {"path": "x.py", "search": "ignored", "replace": "ignored"},
        "Replaced 1 occurrence(s)",
        {"mutation": {"unified_diff": patch, "path": "x.py"}},
    )
    assert detail == patch


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
