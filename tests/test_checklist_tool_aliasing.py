"""Regression guard: the checklist tool exposes ONE canonical name.

These tools used to be registered twice — under canonical ``checklist_*``
names and legacy ``todo_*`` aliases — so the model's catalog carried two
identical tools sharing one store, which made models flail between them.
The aliases were removed, and the ``checklist_write`` / ``checklist_list``
pair was later merged into a single ``checklist`` tool (``todos`` present →
write, omitted → read). This guards against re-introducing duplicates and
confirms the merged tool still works against the shared in-memory store,
including the schema-hidden legacy ``items`` argument alias.
"""

from __future__ import annotations

import pytest

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolContext,
    ToolError,
    build_default_registry,
)

_LEGACY_NAMES = [
    "todo_write",
    "todo_add",
    "todo_update",
    "todo_list",
    "checklist_write",
    "checklist_list",
]
_CANONICAL_NAME = "checklist"


def test_only_canonical_name_registered() -> None:
    """Canonical ``checklist`` present; all legacy names gone."""
    names = set(build_default_registry(mode="agent").names())
    assert _CANONICAL_NAME in names, f"canonical {_CANONICAL_NAME!r} missing"
    for legacy in _LEGACY_NAMES:
        assert legacy not in names, f"legacy name {legacy!r} should be removed"


def test_registered_in_plan_mode_too() -> None:
    """``checklist`` is registered unconditionally, including plan mode."""
    names = set(build_default_registry(mode="plan").names())
    assert _CANONICAL_NAME in names


def test_no_duplicate_checklist_tools_in_catalog() -> None:
    """No checklist tool name appears more than once in the catalog."""
    names = build_default_registry(mode="agent").names()
    checklist_names = [n for n in names if "checklist" in n or n.startswith("todo_")]
    assert len(checklist_names) == len(set(checklist_names)), checklist_names
    assert checklist_names == [_CANONICAL_NAME]


def test_schema_exposes_write_and_update_params() -> None:
    """Schema shows the write + merge-by-id update surface.

    ``todos`` (full-list write) plus the ``op``/``id``/``status``/``content``
    single-item update fields. The legacy ``items`` alias stays hidden.
    """
    registry = build_default_registry(mode="agent")
    assert registry.contains(_CANONICAL_NAME)
    tool = registry.get(_CANONICAL_NAME)
    properties = tool.input_schema().get("properties", {})
    assert set(properties) == {"op", "todos", "id", "status", "content"}
    assert "items" not in properties


def test_canonical_name_is_registered() -> None:
    """The model sees exactly one checklist tool."""
    names = set(build_default_registry().names())
    assert _CANONICAL_NAME in names
    for legacy in _LEGACY_NAMES:
        assert legacy not in names


@pytest.mark.asyncio
async def test_write_then_read_shares_one_store(tmp_path) -> None:
    """``todos`` present writes; ``todos`` omitted reads the same store."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)

    written = await registry.execute(
        _CANONICAL_NAME,
        {
            "todos": [
                {"content": "A", "status": "completed"},
                {"content": "B", "status": "in_progress"},
            ]
        },
        context,
    )
    assert written.success
    # Write path forwards the durable snapshot.
    assert "task_updates" in written.metadata

    listed = await registry.execute(_CANONICAL_NAME, {}, context)
    assert listed.success
    assert [it["content"] for it in listed.metadata["items"]] == ["A", "B"]
    assert [it["status"] for it in listed.metadata["items"]] == [
        "completed",
        "in_progress",
    ]
    # Read path does not forward task_updates.
    assert "task_updates" not in listed.metadata


@pytest.mark.asyncio
async def test_legacy_items_alias_maps_to_todos(tmp_path) -> None:
    """Legacy ``items`` (array of strings) still writes, as pending todos."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)

    result = await registry.execute(
        _CANONICAL_NAME, {"items": ["alpha", "beta"]}, context
    )
    assert result.success
    assert [it["content"] for it in result.metadata["items"]] == ["alpha", "beta"]
    assert all(
        it["status"] == "pending" for it in result.metadata["items"]
    )


# ---------------------------------------------------------------------------
# merge-by-id update (op="update") — the Claude-aligned progress path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_flips_one_item_by_id(tmp_path) -> None:
    """op='update' changes only the addressed item; ids stay stable."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)

    await registry.execute(
        _CANONICAL_NAME,
        {"todos": [{"content": "A"}, {"content": "B"}, {"content": "C"}]},
        context,
    )
    result = await registry.execute(
        _CANONICAL_NAME, {"op": "update", "id": 1, "status": "completed"}, context
    )
    assert result.success

    listed = await registry.execute(_CANONICAL_NAME, {}, context)
    items = listed.metadata["items"]
    # Only item 1 changed; contents and ids untouched.
    assert [it["content"] for it in items] == ["A", "B", "C"]
    assert [it["status"] for it in items] == ["completed", "pending", "pending"]
    assert [it["id"] for it in items] == [1, 2, 3]


@pytest.mark.asyncio
async def test_update_unknown_id_errors(tmp_path) -> None:
    """Updating an id that isn't in the list raises rather than appending."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)
    await registry.execute(
        _CANONICAL_NAME, {"todos": [{"content": "only one"}]}, context
    )
    with pytest.raises(ToolError):
        await registry.execute(
            _CANONICAL_NAME, {"op": "update", "id": 99, "status": "completed"}, context
        )


@pytest.mark.asyncio
async def test_update_can_cancel(tmp_path) -> None:
    """The new ``cancelled`` status is accepted on update."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)
    await registry.execute(
        _CANONICAL_NAME, {"todos": [{"content": "drop me"}]}, context
    )
    result = await registry.execute(
        _CANONICAL_NAME, {"op": "update", "id": 1, "status": "cancelled"}, context
    )
    assert result.success
    assert result.metadata["items"][0]["status"] == "cancelled"


def test_status_only_update_is_prompt_free() -> None:
    """A status-only update is AUTO; writes and content-changing updates SUGGEST."""
    tool = build_default_registry(mode="agent").get(_CANONICAL_NAME)
    # Pure status flip → AUTO.
    assert (
        tool.approval_requirement_for_input(
            {"op": "update", "id": 1, "status": "completed"}
        )
        == ApprovalRequirement.AUTO
    )
    # Update that rewrites content → SUGGEST.
    assert (
        tool.approval_requirement_for_input(
            {"op": "update", "id": 1, "content": "new text"}
        )
        == ApprovalRequirement.SUGGEST
    )
    # Full-list write → SUGGEST.
    assert (
        tool.approval_requirement_for_input({"todos": [{"content": "x"}]})
        == ApprovalRequirement.SUGGEST
    )
    # Pure read → AUTO.
    assert tool.approval_requirement_for_input({}) == ApprovalRequirement.AUTO


@pytest.mark.asyncio
async def test_identical_rewrite_is_noop(tmp_path) -> None:
    """Re-writing the exact same list is a no-op (debounce duplicate spam)."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)
    todos = [
        {"content": "A", "status": "completed"},
        {"content": "B", "status": "in_progress"},
    ]
    first = await registry.execute(_CANONICAL_NAME, {"todos": todos}, context)
    assert "task_updates" in first.metadata  # real write forwards

    second = await registry.execute(_CANONICAL_NAME, {"todos": list(todos)}, context)
    assert second.success
    # No-op: does not re-forward the durable snapshot, and marks itself unchanged.
    assert "task_updates" not in second.metadata
    assert "unchanged" in second.content.lower()

    # A genuine change still writes (and forwards) normally.
    changed = await registry.execute(
        _CANONICAL_NAME,
        {"todos": [{"content": "A", "status": "completed"}, {"content": "B", "status": "completed"}]},
        context,
    )
    assert "task_updates" in changed.metadata


def test_description_carries_completion_gate() -> None:
    """The Claude-aligned completion discipline is stated in the description."""
    tool = build_default_registry(mode="agent").get(_CANONICAL_NAME)
    desc = tool.description().lower()
    assert "fully accomplished" in desc
    assert "op=" in desc or 'op="update"' in desc
